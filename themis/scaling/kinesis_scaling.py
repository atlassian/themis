import logging
import themis.config
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
    shard = get_largest_shard(stream)
    result = []
    if shard:
        result.append(shard)
    else:
        # re-load and save stream config
        kinesis_monitoring.save_modified_stream(stream)
    return result


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


def get_largest_shard(stream):
    shards = stream.shards
    max_shard = None
    for shard in shards:
        if not max_shard or shard.length() < max_shard.length():
            max_shard = shard
    return max_shard


def add_history_entry(stream, state, action):
    return database.history_add(section=SECTION_KINESIS, resource=stream.id, state=state, action=action)


def perform_scaling(kinesis_stream):
    downscale = get_downscale_shards(kinesis_stream)
    upscale = get_upscale_shards(kinesis_stream)
    action = 'NOTHING'
    role = kinesis_monitoring.get_iam_role_for_stream(kinesis_stream)
    kinesis_client = aws_common.connect_kinesis(role=role)
    try:
        if downscale:
            action = 'DOWNSCALE(-%s)' % len(downscale)
            for shard_pair in downscale:
                LOG.info('Merging shards %s and %s of Kinesis stream %s' %
                    (shard_pair.shard1.id, shard_pair.shard2.id, kinesis_stream.id))
                kinesis_client.merge_shards(StreamName=kinesis_stream.id,
                    ShardToMerge=shard_pair.shard1.id, AdjacentShardToMerge=shard_pair.shard2.id)
        elif upscale:
            action = 'UPSCALE(+%s)' % len(upscale)
            for shard in upscale:
                LOG.info('Splitting shard %s of Kinesis stream %s' % (shard.id, kinesis_stream.id))
                new_start_key = shard.center_key()
                kinesis_client.split_shard(StreamName=kinesis_stream.id,
                    ShardToSplit=shard.id, NewStartingHashKey=new_start_key)
    except Exception, e:
        LOG.warning('Unable to re-scale stream %s: %s' % (kinesis_stream.id, e))
    # record whether this stream has been changed
    kinesis_monitoring.STREAMS_CHANGED[kinesis_stream.id] = bool(downscale or upscale)
    # add monitoring data record in history DB
    state = kinesis_stream.monitoring_data
    entry = add_history_entry(kinesis_stream, state=state, action=action)
    return entry


def execute_dsl_string(dsl_str, context, config=None):
    return expr.execute_dsl_string(dsl_str, context=context, config=config)
