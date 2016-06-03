import os
import json
from themis.util import common
from themis.util.common import run,log
from themis.constants import *

# config file location
ROOT_PATH = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..'))
CONFIG_FILE_LOCATION = os.path.join(ROOT_PATH, 'autoscaling.config.json')
CLUSTERS_FILE_LOCATION = os.path.join(ROOT_PATH, 'autoscaling.clusters.json')

DEFAULT_APP_CONFIG = [
	{KEY: KEY_SSH_KEYS, VAL: '~/.ssh/atl-ai-etl-prod.pem,~/.ssh/atl-ai-etl-dev.pem,~/.ssh/ai-etl.pem', DESC: 'Comma-separated list of SSH public key files to use for connecting to the clusters.'},
	{KEY: KEY_AUTOSCALING_CLUSTERS, VAL: '', DESC: 'Comma-separated list of cluster IDs to auto-scale'},
	{KEY: KEY_DOWNSCALE_EXPR, VAL: "1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes >= 2 and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0", DESC: 'Trigger cluster downscaling by the number of nodes this expression evaluates to'},
	{KEY: KEY_UPSCALE_EXPR, VAL: "3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 15 and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0", DESC: "Trigger cluster upscaling by the number of nodes this expression evaluates to"},
	{KEY: KEY_UPSCALE_ITERATIONS, VAL: "1", DESC: "Number of consecutive times %s needs to evaluate to true before upscaling"},
	{KEY: KEY_LOOP_INTERVAL_SECS, VAL: LOOP_SLEEP_TIMEOUT_SECS, DESC: 'Loop interval seconds'},
	{KEY: KEY_PREFERRED_UPSCALE_INSTANCE_MARKET, VAL: MARKET_SPOT, DESC: 'Whether to prefer increasing the pool of SPOT instances or ON_DEMAND instances (if both exist in the cluster)'},
	{KEY: KEY_MONITORING_INTERVAL_SECS, VAL: 60 * 10, DESC: 'Time period (seconds) of historical monitoring data to consider for scaling decisions'},
	{KEY: KEY_TIME_BASED_SCALING, VAL: "{}", DESC: 'A JSON string that maps date regular expressions to minimum number of nodes. Dates to match against are formatted as "%a %Y-%m-%d %H:%M:%S". Example config: { "(Mon|Tue|Wed|Thu|Fri).01:.:.*": 1}'}
]

# load list of clusters
CLUSTER_LIST = common.load_json_file(CLUSTERS_FILE_LOCATION, [])

# set this to override config for testing
TEST_CONFIG = None

def init_clusters_file():
	if not os.path.isfile(CLUSTERS_FILE_LOCATION):
		log("Initializing config file with list of clusters from AWS: %s" % CLUSTERS_FILE_LOCATION)
		cfg = []

		out = run('aws emr list-clusters')
		out = json.loads(out)
		for c in out['Clusters']:
			if c['Status']['State'][0:10] != 'TERMINATED':
				out1 = run('aws emr describe-cluster --cluster-id=%s' % c['Id'])
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
					log('Getting details for cluster %s' % c['Id'])
					# get private IP address of cluster
					for g in cluster_details['InstanceGroups']:
						if g['InstanceGroupType'] == 'MASTER':
							out2 = run('aws emr list-instances --cluster-id=%s' % c['Id'])
							out2 = json.loads(out2)
							for inst in out2['Instances']:
								if inst['InstanceGroupId'] == g['Id']:
									cluster['ip'] = inst['PrivateDnsName']
					cfg.append(cluster)
				else:
					log('Ignoring cluster %s (Ganglia not installed)' % c['Id'])
		common.save_json_file(CLUSTERS_FILE_LOCATION, cfg)
		log('Done.')

def read():
	appConfig = common.load_json_file(CONFIG_FILE_LOCATION)
	if appConfig:
		return appConfig['config']
	write(DEFAULT_APP_CONFIG)
	return DEFAULT_APP_CONFIG

def write(config):
	configToStore = {'config': config}
	common.save_json_file(CONFIG_FILE_LOCATION, configToStore)
	return config

def get_value(key, config=None, default=None):
	if not config:
		config = read()
	for c in config:
		if c[KEY] == key:
			return c[VAL]
	return default
