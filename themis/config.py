import os
import json
import re
import threading
from themis.util import common
from themis.util.common import run, now
from themis.model.aws_model import *
from themis.constants import *


# config file location
CONFIG_FILE_LOCATION = os.path.join(os.getcwd(), 'themis.config.json')
RESOURCES_FILE_LOCATION = os.path.join(os.getcwd(), 'themis.resources.json')

# configuration sections
SECTION_GLOBAL = 'general'
SECTION_EMR = 'emr'
SECTION_KINESIS = 'kinesis'

# set this to override config for testing
TEST_CONFIG = None

# logger
LOG = common.get_logger(__name__)

# global config pointer
CONFIG = None

# maps config keys to their descriptions
ALL_DESCRIPTIONS = {}

# in-memory cache for various config values
# CONFIG_CACHE = {}

# configuration change listeners
CONFIG_LISTENERS = set()

# seconds to cache the config for
CONFIG_CACHE_DURATION = 10
last_config_load_time = 0


class ConfigObject(JsonObject):
    def get(self, *keys, **kwargs):
        default = kwargs.get('default')
        if len(keys) > 1:
            first_key = keys[0]
            remaining_keys = keys[1:]
            item = self.__dict__.get(first_key)
            if item is None:
                return default
            return item.get(*remaining_keys, **kwargs)
        key = keys[0]
        result = self.__dict__.get(key)
        if result is None:
            return default
        return result

    def set(self, key, value):
        self.__dict__[key] = value

    @classmethod
    def from_json(cls, j):
        result = cls()
        for k, v in j.iteritems():
            result.set(k, v)
        return result


class SystemConfiguration(ConfigObject):
    """Main configuration class representing the content of file themis.config.json"""

    def __init__(self):
        self.general = GeneralConfiguration()
        self.emr = EmrConfiguration()
        self.kinesis = KinesisConfiguration()

    @classmethod
    def from_json(cls, j):
        result = SystemConfiguration()
        result.general = GeneralConfiguration.from_json(j.get('general'))
        result.emr = EmrConfiguration.from_json(j.get('emr'))
        result.kinesis = KinesisConfiguration.from_json(j.get('kinesis'))
        return result


class GeneralConfiguration(ConfigObject):
    CONFIG_ITEMS = {
        'ssh_keys': 'Comma-separated list of SSH public key files to use for connecting to the clusters.',
        # TODO move to EMR config?
        'autoscaling_clusters': 'Comma-separated list of cluster IDs to auto-scale',
        # TODO move to Kinesis config?
        'autoscaling_kinesis_streams': 'Comma-separated list of Kinesis stream names to auto-scale',
        'scaling_loop_interval': 'Loop interval seconds',
        'monitoring_time_window': 'Time period (seconds) of historical monitoring data to consider for scaling'
    }

    def __init__(self):
        self.ssh_keys = '~/.ssh/atl-ai-etl-prod.pem,~/.ssh/atl-ai-etl-dev.pem,~/.ssh/ai-etl.pem'
        self.autoscaling_clusters = ''
        self.autoscaling_kinesis_streams = ''
        self.monitoring_time_window = 60 * 10
        self.scaling_loop_interval = LOOP_SLEEP_TIMEOUT_SECS

    def get_autoscaling_clusters(self):
        return re.split(r'\s*,\s*', self.autoscaling_clusters)

    def get_autoscaling_kinesis_streams(self):
        return re.split(r'\s*,\s*', self.autoscaling_kinesis_streams)


class EmrConfiguration(ConfigObject):

    def get(self, *keys, **kwargs):
        result = super(EmrConfiguration, self).get(*keys, **kwargs)
        if result is None and len(keys) == 1:
            # return default config
            result = EmrClusterConfiguration()
            self.set(keys[0], result)
        return result

    def set(self, key, value):
        if isinstance(value, dict):
            value = EmrClusterConfiguration.from_dict(value)
        return super(EmrConfiguration, self).set(key, value)


class EmrClusterConfiguration(ConfigObject):
    CONFIG_ITEMS = {
        'downscale_expr': 'Trigger cluster downscaling by the number of nodes this expression evaluates to',
        'upscale_expr': 'Trigger cluster upscaling by the number of nodes this expression evaluates to',
        'time_based_scaling': """A JSON string that maps date regular expressions to minimum number of nodes. \
            Dates to match against are formatted as "%a %Y-%m-%d %H:%M:%S". \
            Example config: { "(Mon|Tue|Wed|Thu|Fri).01:.*:.*": 1 }""".replace('    ', ''),
        'group_or_preferred_market': """Comma separated list of task instance groups and/or instance markets to \
            increase/decrease depending on order, e.g., "ig-12345,SPOT,ON_DEMAND" means to autoscale task group \
            ig-12345 if available, otherwise any SPOT group, or if necessary ON_DEMAND groups""".replace('    ', ''),
        'baseline_nodes': 'Number of baseline nodes to use for comparing costs and calculating savings',
        'custom_domain_name': 'Custom domain name to apply to all nodes in cluster (override aws-cli result)'
    }

    def __init__(self):
        self.downscale_expr = """1 if \
            (tasknodes.running and tasknodes.active and tasknodes.count.nodes > time_based.minimum.nodes(now) \
            and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) \
            else 0""".replace('    ', '')
        self.upscale_expr = """(time_based.minimum.nodes(now) - tasknodes.count.nodes) if \
            (time_based.enabled and time_based.minimum.nodes(now) > tasknodes.count.nodes) \
            else (3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
            and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0)""".replace('    ', '')
        self.time_based_scaling = '{}'
        self.group_or_preferred_market = ('"%s" if tasknodes.count.nodes < 15 ' +
            'else "%s"') % (MARKET_ON_DEMAND, MARKET_SPOT)
        self.baseline_nodes = '20'
        self.custom_domain_name = ''


class KinesisConfiguration(ConfigObject):
    CONFIG_ITEMS = {}

    def get(self, *keys, **kwargs):
        result = super(KinesisConfiguration, self).get(*keys, **kwargs)
        if result is None and len(keys) == 1:
            # return default config
            result = KinesisStreamConfiguration()
            self.set(keys[0], result)
        return result

    def set(self, key, value):
        if isinstance(value, dict):
            value = KinesisStreamConfiguration.from_dict(value)
        return super(KinesisConfiguration, self).set(key, value)


class KinesisStreamConfiguration(ConfigObject):
    CONFIG_ITEMS = {
        'enable_enhanced_monitoring': """Enable enhanced monitoring. A value of "true" \
            enables per-shard monitoring with ShardLevelMetrics=ALL""",
        'stream_upscale_expr': 'Trigger stream upscaling by the number of shards this expression evaluates to',
        'stream_downscale_expr': 'Trigger stream downscaling by the number of shards this expression evaluates to'
    }

    def __init__(self):
        self.enable_enhanced_monitoring = 'false'
        self.stream_downscale_expr = '1 if (shards.count > 1 and stream.IncomingBytes.average < 100000) else 0'
        self.stream_upscale_expr = '1 if (shards.count < 5 and stream.IncomingBytes.average > 100000) else 0'


ALL_CONFIG_CLASSES = [GeneralConfiguration, EmrClusterConfiguration, KinesisConfiguration]
# populate ALL_DESCRIPTIONS
for clazz in ALL_CONFIG_CLASSES:
    ALL_DESCRIPTIONS.update(clazz.CONFIG_ITEMS)


def convert_to_list(cfg):
    result = []
    for k, v in cfg.iteritems():
        result.append({KEY: k, VAL: v, DESC: ALL_DESCRIPTIONS.get(k)})
    return result


def convert_from_list(cfgs):
    result = {}
    for cfg in cfgs:
        result[cfg[KEY]] = cfg[VAL]
    return result


def get_config(force_load=False):
    global CONFIG, TEST_CONFIG, last_config_load_time
    if TEST_CONFIG:
        return TEST_CONFIG
    time_now = now()
    if (time_now - last_config_load_time) > CONFIG_CACHE_DURATION:
        force_load = True
    if CONFIG and not force_load:
        return CONFIG
    app_config = common.load_json_file(CONFIG_FILE_LOCATION)
    last_config_load_time = time_now
    if not app_config:
        app_config = SystemConfiguration()
        common.save_file(CONFIG_FILE_LOCATION, app_config.to_json())
    else:
        app_config = SystemConfiguration.from_json(app_config)
    CONFIG = app_config
    return app_config


def write(config, section=SECTION_GLOBAL, resource=None):
    # invalidate_cache(section)
    app_config = get_config(force_load=True)
    if resource:
        target_config = app_config.get(section)
        old_config = target_config.get(resource)
        target_config.set(resource, config)
        notify_listeners(old_config, config, section=section, resource=resource)
    else:
        old_config = app_config.get(section)
        app_config.set(section, config)
        notify_listeners(old_config, config, section=section)
    common.save_file(CONFIG_FILE_LOCATION, app_config.to_json())
    return config


def notify_listeners(old_config, new_config, section, resource=None):
    for listener in CONFIG_LISTENERS:
        listener(old_config=old_config, new_config=new_config, section=section, resource=resource)


def get_value(key, config=None, default=None, section=SECTION_GLOBAL, resource=None):
    if not config:
        config = get_config()
    keys = (section, key)
    if resource:
        keys = (section, resource, key)
    return config.get(*keys, default=default)


def set_value(key, new_value, section=SECTION_GLOBAL, resource=None, config=None):
    given_config = config
    if not config:
        config = get_config()
    target_config = config.get(section)
    if resource:
        target_config = target_config.get(resource)
    target_config.set(key, new_value)
    if not given_config:
        # write changes to config file
        write(target_config, section=section, resource=resource)
    return target_config


# def invalidate_cache(section):
#     if not section:
#         section = SECTION_GLOBAL
#     CONFIG_CACHE[section] = {}
