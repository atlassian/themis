import logging
import themis.config
import time
from themis.util import expr, aws_common
from themis.constants import *
from themis.monitoring import database, kinesis_monitoring
import themis.monitoring.resources
from themis.config import *

LOG = logging.getLogger(__name__)


class ShardPair(object):
    def __init__(self, shard1, shard2):
        self.shard1 = shard1
        self.shard2 = shard2
        # TODO check if adjacent
        if long(shard2.start_key) < long(shard1.start_key):
            # swap shards
            self.shard1 = shard2
            self.shard2 = shard1

    def length(self):
        return self.shard1.length() + self.shard2.length()


def check_cooldown(stream, config=None):
    if not config:
        config = themis.config.get_config()
    cooloff = config.get(SECTION_KINESIS, stream.id, KEY_COOLOFF_TIME)
    history = database.history_get(section=SECTION_KINESIS, resource=stream.id, limit=1)
    if history:
        if ((time.time() - float(history[0]['timestamp']) / 1000.0) < float(cooloff)):
            return True
    return False


def get_downscale_shards(stream, config=None):
    if not config:
        config = themis.config.get_config()
    expr = config.get(SECTION_KINESIS, stream.id, KEY_STREAM_DOWNSCALE_EXPR)
    num_downsize = execute_dsl_string(expr, stream.monitoring_data, config=config)
    LOG.info("Kinesis Stream %s: num_downsize: %s" % (stream.id, num_downsize))
    if not isinstance(num_downsize, int) or num_downsize <= 0:
        return []
    result = []
    stream = kinesis_monitoring.retrieve_stream_details(stream.id)
    for i in range(0, num_downsize):
        min_pair = get_smallest_shard_pair(stream)
        if min_pair:
            result.append(min_pair)
        else:
            # re-load and save stream config
            kinesis_monitoring.save_modified_stream(stream)
    return result


def get_upscale_shards(stream, config=None):
    if not config:
        config = themis.config.get_config()
    expr = config.get(SECTION_KINESIS, stream.id, KEY_STREAM_UPSCALE_EXPR)
    num_upsize = execute_dsl_string(expr, stream.monitoring_data, config=config)
    LOG.info("Kinesis Stream %s: num_upsize: %s" % (stream.id, num_upsize))
    if not isinstance(num_upsize, int) or num_upsize <= 0:
        return []
    shards = get_largests_shards(stream, min(num_upsize - len(stream.shards), len(stream.shards)))
    if not shards:
        # re-load and save stream config
        kinesis_monitoring.save_modified_stream(stream)
    return shards


def get_smallest_shard_pair(stream):
    shards = stream.shards
    min_pair = None
    for i in range(0, len(shards) - 1):
        s1 = shards[i]
        s2 = shards[i + 1]
        size = s1.length() + s2.length()
        if not min_pair or size < min_pair.length():
            min_pair = ShardPair(s1, s2)
    return min_pair


def get_largests_shards(stream, num_upsize):
    shards = stream.shards
    ordered_shards = sorted(shards, key=lambda x: x.length)
    largest_shards = ordered_shards[:num_upsize]
    print(largest_shards)
    return largest_shards


def add_history_entry(stream, state, action):
    return database.history_add(section=SECTION_KINESIS, resource=stream.id, state=state, action=action)


def wait_for_active(client, stream):
    summary = client.describe_stream(StreamName=stream.id)
    while(summary['StreamDescription']['StreamStatus'] != 'ACTIVE'):
        time.sleep(3)
        summary = client.describe_stream(StreamName=stream.id)

def scale_down(downscale, kinesis_client, kinesis_stream):
    for shard_pair in downscale:
        LOG.info('Merging shards %s and %s of Kinesis stream %s' %
            (shard_pair.shard1.id, shard_pair.shard2.id, kinesis_stream.id))
        wait_for_active(kinesis_client, kinesis_stream)
        kinesis_client.merge_shards(StreamName=kinesis_stream.id,
            ShardToMerge=shard_pair.shard1.id, AdjacentShardToMerge=shard_pair.shard2.id)

def scale_up(upscale, kinesis_client, kinesis_stream):
    target_count = len(upscale) + len(kinesis_stream.shards)
    LOG.info("Trying to scale Kinesis stream %s to %d" % (shard.id, target_count))
    try:
        kinesis_client.update_shard_count(StreamName=kinesis_stream.id, 
            TargetShardCount=target_count,
            ScalingType='UNIFORM_SCALING')
    except Exception, e:
        LOG.warn("Failed to use Update Shard Count API, trying manually...")
        for shard in upscale:
            LOG.info('Splitting shard %s of Kinesis stream %s' % (shard.id, kinesis_stream.id))
            new_start_key = shard.center_key()
            wait_for_active(client=kinesis_client, stream=kinesis_stream)
            kinesis_client.split_shard(StreamName=kinesis_stream.id,
                ShardToSplit=shard.id, NewStartingHashKey=new_start_key)

def perform_scaling(kinesis_stream):
    if check_cooldown(kinesis_stream) == True:
        LOG.info('Cooling down scaling for Kinesis stream %s' % kinesis_stream.id)
        return
    downscale = get_downscale_shards(kinesis_stream)
    upscale = get_upscale_shards(kinesis_stream)
    action = 'NOTHING'
    role = kinesis_monitoring.get_iam_role_for_stream(kinesis_stream)
    kinesis_client = aws_common.connect_kinesis(role=role)
    try:
        if downscale:
            action = 'DOWNSCALE(-%s)' % len(downscale)
            scale_down(downscale)
        elif upscale:
            action = 'UPSCALE(+%s)' % len(upscale)
            scale_up(upscale)
            
    except Exception, e:
        LOG.warning('Unable to re-scale stream %s: %s' % (kinesis_stream.id, e))
        return
    # record whether this stream has been changed
    kinesis_monitoring.STREAMS_CHANGED[kinesis_stream.id] = bool(downscale or upscale)
    # add monitoring data record in history DB
    if bool(downscale or upscale):
        state = kinesis_stream.monitoring_data
        entry = add_history_entry(kinesis_stream, state=state, action=action)
        return entry
    return


def execute_dsl_string(dsl_str, context, config=None):
    return expr.execute_dsl_string(dsl_str, context=context, config=config)
