import json
import re
import themis.model.resources_model
import themis.model.kinesis_model
import themis.monitoring.resources
import themis.config
from themis.model.aws_model import *
from themis.config import *
from themis.util.common import *
from themis.util import timeseries, math_util, aws_common

# logger
LOG = get_logger(__name__)

# constants
MONITORING_METRICS_ALL = 'ALL'
STREAM_LEVEL_METRICS = [
    'IncomingBytes', 'IncomingRecords', 'GetRecords.IteratorAgeMilliseconds',
    'ReadProvisionedThroughputExceeded', 'WriteProvisionedThroughputExceeded',
    'GetRecords.IteratorAgeMilliseconds']
SHARD_LEVEL_METRICS = ['IncomingBytes', 'IncomingRecords', 'IteratorAgeMilliseconds',
    'OutgoingBytes', 'OutgoingRecords', 'ReadProvisionedThroughputExceeded',
    'WriteProvisionedThroughputExceeded']

# get CloudWatch data from the last 20 minutes by default
CW_METRICS_TIMEWINDOW = 60 * 20
CW_METRICS_PERIOD = 60

# Maps a metric regex to the corresponding CloudWatch statistic to use. The first match is used.
CW_STATISTICS_BY_METRIC = (
    (r'.*IteratorAge.*', 'Maximum'),
    (r'.*', 'Sum')
)

# track which streams have been changed (scaled) in the previous iteration
STREAMS_CHANGED = {}


def update_config(old_config, new_config, section, resource=None):
    if section != SECTION_KINESIS:
        return
    if resource:
        old_value = old_config.enable_enhanced_monitoring
        new_value = new_config.enable_enhanced_monitoring
        if new_value != old_value:
            if new_value:
                # enable monitoring
                enable_shard_monitoring(resource)
            else:
                # disable monitoring
                disable_shard_monitoring(resource)


themis.config.CONFIG_LISTENERS.add(update_config)


def reload_resource(resource):
    stream_id = resource if isinstance(resource, basestring) else resource.id
    stream = retrieve_stream_details(stream_id)
    themis.monitoring.resources.save_resource(SECTION_KINESIS, stream)
    return stream


def update_resources(resource_config):
    for res in resource_config:
        enabled = themis.config.get_value('enable_enhanced_monitoring',
            section=SECTION_KINESIS, resource=res.id)
        if enabled == 'true':
            res.enhanced_monitoring = [MONITORING_METRICS_ALL]
    return resource_config


def get_statistic_for_metric(metric):
    for stat in CW_STATISTICS_BY_METRIC:
        if re.match(stat[0], metric):
            return stat[1]
    return None


def get_cloudwatch_metrics(metric, namespace, dimensions, role=None,
        time_window=CW_METRICS_TIMEWINDOW, period=CW_METRICS_PERIOD, fill_zeros=True):
    start_time, end_time = get_start_and_end(diff_secs=time_window, format=None)
    metric_names = metric if isinstance(metric, basestring) else ','.join(metric)
    cloudwatch_client = aws_common.connect_cloudwatch(role=role)
    statistic = get_statistic_for_metric(metric)
    datapoints = cloudwatch_client.get_metric_statistics(Namespace=namespace, MetricName=metric_names,
        StartTime=start_time, EndTime=end_time, Period=period, Dimensions=dimensions,
        Statistics=[statistic])
    datapoints = datapoints['Datapoints']

    # sort datapoints by timestamp
    datapoints.sort(key=lambda item: item['Timestamp'])
    # fill empty slots with zeros
    if fill_zeros:
        # make sure we don't fill in zeros at the very end of the
        # series (data may be missing due to Cloudwatch delay)
        time_window_to_fill = time_window - 2 * period
        timeseries.fillup_with_zeros(datapoints, start_time=start_time,
            time_window=time_window_to_fill, period=period, statistic=statistic)

    return datapoints


def get_iam_role_for_stream(stream):
    if not isinstance(stream, basestring):
        stream = stream.id
    return themis.config.get_value('role_to_assume', section=SECTION_KINESIS, resource=stream)


def enable_shard_monitoring(stream, metrics=['ALL']):
    if not isinstance(stream, basestring):
        stream = stream.id
    role = get_iam_role_for_stream(stream)
    kinesis_client = aws_common.connect_kinesis(role=role)
    return kinesis_client.enable_enhanced_monitoring(StreamName=stream, ShardLevelMetrics=metrics)


def disable_shard_monitoring(stream, metrics=['ALL']):
    if not isinstance(stream, basestring):
        stream = stream.id
    role = get_iam_role_for_stream(stream)
    kinesis_client = aws_common.connect_kinesis(role=role)
    return kinesis_client.disable_enhanced_monitoring(StreamName=stream, ShardLevelMetrics=metrics)


def get_kinesis_cloudwatch_metrics(stream, metric, shard=None):
    dimensions = [{'Name': 'StreamName', 'Value': stream.id}]
    if shard:
        shard = shard if isinstance(shard, basestring) else shard['id'] if isinstance(shard, dict) else shard.id
        dimensions.append({'Name': 'ShardId', 'Value': shard})
    role = get_iam_role_for_stream(stream)
    return get_cloudwatch_metrics(metric=metric, namespace='AWS/Kinesis', dimensions=dimensions, role=role)


def replace_nan(value, default=0):
    if math.isnan(value):
        return default
    return value


def collect_info(stream, monitoring_interval_secs=600, config=None):
    result = {}
    # check if we need to re-load and save the stream details
    if STREAMS_CHANGED.get(stream.id):
        stream = save_modified_stream(stream)
    # start initializing the list of shards
    shards_list = result['shards_list'] = []
    for shard in stream.shards:
        shard = shard.to_dict()
        shards_list.append(shard)
    total = result['total'] = result['stream'] = {}
    shards = result['shards'] = {}
    shards['count'] = len(shards_list)
    metrics_map = {}

    # check if shard-level monitoring is enabled
    shard_monitoring_enabled = themis.config.get_value('enable_enhanced_monitoring',
        section=SECTION_KINESIS, resource=stream.id)

    for metric in STREAM_LEVEL_METRICS:
        metric_name = metric
        metric = metric.replace('.', '_')
        datapoints = get_kinesis_cloudwatch_metrics(stream=stream, metric=metric_name)
        series = timeseries.get_cloudwatch_timeseries(datapoints)
        shards[metric] = {}
        total[metric] = {}
        total[metric]['average'] = replace_nan(series.mean())
        total[metric]['max'] = replace_nan(series.max())
        total[metric]['min'] = replace_nan(series.min())
        total[metric]['sum'] = replace_nan(series.sum())
        total[metric]['last'] = series.values[-1] if len(series.values) > 0 else 0
    if shard_monitoring_enabled == 'true':
        for metric in SHARD_LEVEL_METRICS:
            # collect detailed shard-level monitoring metrics
            for shard in shards_list:
                datapoints = get_kinesis_cloudwatch_metrics(stream=stream, metric=metric, shard=shard)
                series = timeseries.get_cloudwatch_timeseries(datapoints)
                shard[metric] = {}
                shard[metric]['average'] = replace_nan(series.mean())
                shard[metric]['max'] = replace_nan(series.max())
                shard[metric]['min'] = replace_nan(series.min())
                shard[metric]['sum'] = replace_nan(series.sum())
                shard[metric]['last'] = series.values[-1] if len(series.values) > 0 else 0
                # append metrics to map
                if metric not in metrics_map:
                    # map for shard-level metrics
                    metrics_map[metric] = {}
                    metrics_map[metric]['average'] = []
                    metrics_map[metric]['max'] = []
                    metrics_map[metric]['min'] = []
                    metrics_map[metric]['sum'] = []
                metrics_map[metric]['average'].append(replace_nan(series.mean()))
                metrics_map[metric]['max'].append(replace_nan(series.max()))
                metrics_map[metric]['min'].append(replace_nan(series.min()))
                metrics_map[metric]['sum'].append(replace_nan(series.sum()))
    for m_name, m_lists in metrics_map.iteritems():
        shards[metric]['average'] = math_util.get_stats(m_lists['average'])['avg']
        shards[metric]['min'] = math_util.get_stats(m_lists['min'])['min']
        shards[metric]['max'] = math_util.get_stats(m_lists['max'])['max']
        shards[metric]['sum'] = math_util.get_stats(m_lists['sum'])['sum']
    remove_NaN(result, delete_values=False)
    return result


def retrieve_stream_details(stream_name, role=None):
    LOG.info('Getting details for Kinesis stream %s' % stream_name)
    if role is None:
        role = get_iam_role_for_stream(stream_name)
    kinesis_client = aws_common.connect_kinesis(role=role)
    out = kinesis_client.describe_stream(StreamName=stream_name)
    stream_shards = out['StreamDescription']['Shards']
    stream = themis.model.kinesis_model.KinesisStream(stream_name)
    num_shards = len(stream_shards)
    for shard in stream_shards:
        if 'EndingSequenceNumber' not in shard['SequenceNumberRange']:
            key_range = shard['HashKeyRange']
            shard = themis.model.kinesis_model.KinesisShard(id=shard['ShardId'])
            shard.start_key = key_range['StartingHashKey']
            shard.end_key = key_range['EndingHashKey']
            stream.shards.append(shard)
    return stream


def save_modified_stream(stream):
    stream = retrieve_stream_details(stream.id)
    themis.monitoring.resources.save_resource(SECTION_KINESIS, stream)
    return stream


def init_kinesis_config(run_parallel=False, role=None):
    cfg = themis.model.resources_model.ResourcesConfiguration()

    def init_kinesis_stream_config(stream_name):
        stream_config = retrieve_stream_details(stream_name, role=role)
        cfg.kinesis.append(stream_config)

    # load Kinesis streams
    kinesis_client = aws_common.connect_kinesis(role=role)
    try:
        out = kinesis_client.list_streams()
        if run_parallel:
            common.parallelize(out['StreamNames'], init_kinesis_stream_config)
        else:
            for c in out['StreamNames']:
                init_kinesis_stream_config(c)
    except Exception, e:
        LOG.info('Unable to list Kinesis streams using IAM role "%s"' % role)
    return cfg
