import json
from themis import config
import themis.model.resources_model
import themis.model.kinesis_model
from themis.model.aws_model import *
from themis.config import *
from themis.util.common import *

# logger
LOG = get_logger(__name__)


def update_config(old_config, new_config, section, resource=None):
    if section != SECTION_KINESIS:
        return
    if resource:
        key = 'enable_enhanced_monitoring'
        old_value = old_config.enable_enhanced_monitoring
        new_value = new_config['enable_enhanced_monitoring']
        if new_value != old_value:
            if new_value:
                # enable monitoring
                enable_shard_monitoring(resource)
            else:
                # disable monitoring
                disable_shard_monitoring(resource)


config.CONFIG_LISTENERS.add(update_config)


def get_cloudwatch_metrics(metric, namespace, dimensions, time_window=600, period=60):
    start_time, end_time = get_start_and_end(diff_secs=time_window, format="%Y-%m-%dT%H:%M:%S", escape=False)
    cmd = ("""aws cloudwatch get-metric-statistics --namespace=%s --metric-name=%s \
         --start-time=%s --end-time=%s --period=%s --statistics=Average --dimensions %s""" %
         (namespace, metric, start_time, end_time, period, dimensions))
    datapoints = json.loads(run(cmd))
    datapoints = datapoints['Datapoints']
    print(datapoints)
    return datapoints


def enable_shard_monitoring(stream, metrics='ALL'):
    if not isinstance(stream, basestring):
        stream = stream.id
    cmd = 'aws kinesis enable-enhanced-monitoring --stream-name %s --shard-level-metrics %s' % (stream, metrics)
    run(cmd)


def disable_shard_monitoring(stream, metrics='ALL'):
    if not isinstance(stream, basestring):
        stream = stream.id
    cmd = 'aws kinesis disable-enhanced-monitoring --stream-name %s --shard-level-metrics %s' % (stream, metrics)
    run(cmd)


def get_kinesis_cloudwatch_metrics(stream, metric):
    dimensions = 'Name=StreamName,Value=%s' % stream.id
    return get_cloudwatch_metrics(metric=metric, namespace='AWS/Kinesis', dimensions=dimensions)


def collect_info(stream, monitoring_interval_secs=600):
    result = {}
    shards = result['shards'] = []
    datapoints = get_kinesis_cloudwatch_metrics(stream=stream, metric='IncomingBytes')
    for shard in stream.shards:
        shard = shard.to_dict()
        shards.append(shard)
    result['datapoints'] = datapoints
    return result


def init_kinesis_config(run_parallel=False):
    cfg = themis.model.resources_model.ResourcesConfiguration()

    def init_kinesis_stream_config(stream_name):
        LOG.info('Getting details for Kinesis stream %s' % stream_name)
        out = run('aws kinesis describe-stream --stream-name %s' % stream_name)
        out = json.loads(out)
        stream_shards = out['StreamDescription']['Shards']
        stream = themis.model.kinesis_model.KinesisStream(stream_name)
        num_shards = len(stream_shards)
        for shard in stream_shards:
            key_range = shard['HashKeyRange']
            shard = themis.model.kinesis_model.KinesisShard(id=shard['ShardId'])
            shard.start_key = key_range['StartingHashKey']
            shard.end_key = key_range['EndingHashKey']
            stream.shards.append(shard)
        cfg.kinesis.append(stream)
        return stream

    # load Kinesis streams
    out = run('aws kinesis list-streams')
    out = json.loads(out)
    if run_parallel:
        common.parallelize(out['StreamNames'], init_kinesis_stream_config)
    else:
        for c in out['StreamNames']:
            init_kinesis_stream_config(c)
    return cfg
