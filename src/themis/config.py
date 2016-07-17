import os
import json
import threading
from themis.util import common
from themis.util.common import run
from themis.constants import *

# config file location
ROOT_PATH = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..'))
CONFIG_FILE_LOCATION = os.path.join(ROOT_PATH, 'autoscaling.config.json')
CLUSTERS_FILE_LOCATION = os.path.join(ROOT_PATH, 'autoscaling.clusters.json')

# configuration sections
SECTION_GLOBAL = 'global'
SECTION_CLUSTER_TEMPLATE = 'cluster_template'

DEFAULT_APP_CONFIG = {
	SECTION_GLOBAL: [
		{KEY: KEY_SSH_KEYS, VAL: '~/.ssh/atl-ai-etl-prod.pem,~/.ssh/atl-ai-etl-dev.pem,~/.ssh/ai-etl.pem', DESC: 'Comma-separated list of SSH public key files to use for connecting to the clusters.'},
		{KEY: KEY_AUTOSCALING_CLUSTERS, VAL: '', DESC: 'Comma-separated list of cluster IDs to auto-scale'},
		{KEY: KEY_LOOP_INTERVAL_SECS, VAL: LOOP_SLEEP_TIMEOUT_SECS, DESC: 'Loop interval seconds'},
		{KEY: KEY_MONITORING_INTERVAL_SECS, VAL: 60 * 10, DESC: 'Time period (seconds) of historical monitoring data to consider for scaling decisions'}
	],
	SECTION_CLUSTER_TEMPLATE: [
		{KEY: KEY_DOWNSCALE_EXPR, VAL: """1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > time_based.minimum.nodes(now) and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) \
													else 0""", DESC: 'Trigger cluster downscaling by the number of nodes this expression evaluates to'},
		{KEY: KEY_UPSCALE_EXPR, VAL: """(time_based.minimum.nodes(now) - tasknodes.count.nodes) if (time_based.enabled and time_based.minimum.nodes(now) > tasknodes.count.nodes) \
		 											else (3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) \
	    										   else 0)""", DESC: "Trigger cluster upscaling by the number of nodes this expression evaluates to"},
		{KEY: KEY_TIME_BASED_SCALING, VAL: "{}", DESC: 'A JSON string that maps date regular expressions to minimum number of nodes. Dates to match against are formatted as "%a %Y-%m-%d %H:%M:%S". Example config: { "(Mon|Tue|Wed|Thu|Fri).01:.:.*": 1}'},
		{KEY: KEY_PREFERRED_UPSCALE_INSTANCE_MARKET, VAL: MARKET_SPOT, DESC: 'Whether to prefer increasing the pool of SPOT instances or ON_DEMAND instances (if both exist in the cluster)'}
	]
}

# load list of clusters
CLUSTER_LIST = common.load_json_file(CLUSTERS_FILE_LOCATION, [])

# set this to override config for testing
TEST_CONFIG = None

# logger
LOG = common.get_logger(__name__)

def init_clusters_file():
	cfg = []
	mutex = threading.Semaphore(1)
	run_parallel = True

	def init_cluster_config(c):
		if c['Status']['State'][0:10] != 'TERMINATED':
			out1 = run('aws emr describe-cluster --cluster-id=%s' % c['Id'], retries=1)
			out1 = json.loads(out1)
			cluster_details = out1['Cluster']
			cluster = {
				'id': c['Id'],
				'name': c['Name'],
				'ip': 'N/A',
				'ip_public': cluster_details['MasterPublicDnsName']
			}
			has_ganglia = False
			for app in out1['Cluster']['Applications']:
				if app['Name'] == 'Hive' and 'type' not in cluster:
					cluster['type'] = 'Hive'
				if app['Name'][0:6] == 'Presto':
					cluster['type'] = 'Presto'
				if app['Name'] == 'Ganglia':
					has_ganglia = True
			if has_ganglia:
				LOG.info('Getting details for cluster %s' % c['Id'])
				# get private IP address of cluster
				for g in cluster_details['InstanceGroups']:
					if g['InstanceGroupType'] == 'MASTER':
						cmd = 'aws emr list-instances --cluster-id=%s' % c['Id']
						out2 = run(cmd, retries=1)
						if not out2:
							LOG.warning("No output for command '%s'" % cmd)
						out2 = json.loads(out2)
						for inst in out2['Instances']:
							if inst['InstanceGroupId'] == g['Id']:
								cluster['ip'] = inst['PrivateDnsName']
				cfg.append(cluster)
			else:
				LOG.info('Ignoring cluster %s (Ganglia not installed)' % c['Id'])

	if not os.path.isfile(CLUSTERS_FILE_LOCATION):
		LOG.info("Initializing config file with list of clusters from AWS: %s" % CLUSTERS_FILE_LOCATION)
		out = run('aws emr list-clusters')
		out = json.loads(out)
		if run_parallel:
			common.parallelize(out['Clusters'], init_cluster_config)
		else:
			for c in out['Clusters']:
				init_cluster_config(c)
		common.save_json_file(CLUSTERS_FILE_LOCATION, cfg)
		LOG.info('Done initializing.')

def read(section=SECTION_GLOBAL):
	appConfig = common.load_json_file(CONFIG_FILE_LOCATION)
	if not appConfig:
		common.save_json_file(CONFIG_FILE_LOCATION, DEFAULT_APP_CONFIG)
		appConfig = DEFAULT_APP_CONFIG
	if section not in appConfig:
		if section != SECTION_GLOBAL:
			return DEFAULT_APP_CONFIG[SECTION_CLUSTER_TEMPLATE]
		return []
	return appConfig[section]

def write(config, section=SECTION_GLOBAL):
	appConfig = common.load_json_file(CONFIG_FILE_LOCATION)
	if not appConfig:
		appConfig = DEFAULT_APP_CONFIG
	appConfig[section] = config
	common.save_json_file(CONFIG_FILE_LOCATION, appConfig)
	return config

def get_value(key, config=None, default=None, section=SECTION_GLOBAL):
	if not config:
		config = read(section)
	for c in config:
		if c[KEY] == key:
			return c[VAL]
	return default
