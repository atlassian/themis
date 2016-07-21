from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_swagger import swagger
import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config
from themis.constants import *
from themis.util import common, monitoring, aws_common, aws_pricing
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK

root_path = os.path.dirname(os.path.realpath(__file__))
web_dir = root_path + '/../../../web/'

# flask web app
app = Flask('app', template_folder=web_dir)
app.root_path = root_path

# logger
LOG = common.get_logger(__name__)

# map of configured clusters
CLUSTERS = {}
for val in config.CLUSTER_LIST:
	CLUSTERS[val['id']] = val

@app.route('/swagger.json')
def spec():
	swag = swagger(app)
	swag['info']['version'] = "1.0"
	swag['info']['title'] = "Cluster Management API"
	return jsonify(swag)

@app.route('/state/<cluster_id>')
def get_state(cluster_id):
	""" Get cluster state
		---
		operationId: 'getState'
		parameters:
			- name: cluster_id
			  in: path
	"""
	monitoring_interval_secs = int(config.get_value(KEY_MONITORING_INTERVAL_SECS))
	info = monitoring.collect_info(CLUSTERS[cluster_id], monitoring_interval_secs=monitoring_interval_secs)
	return jsonify(info)

@app.route('/history/<cluster_id>')
def get_history(cluster_id):
	""" Get cluster state history
		---
		operationId: 'getHistory'
		parameters:
			- name: 'cluster_id'
			  in: path
	"""
	info = monitoring.history_get(cluster_id, 100)
	common.remove_NaN(info)
	return jsonify(results=info)

@app.route('/clusters')
def get_clusters():
	""" Get list of clusters
		---
		operationId: 'getClusters'
	"""
	return jsonify(results=config.CLUSTER_LIST)

@app.route('/config', methods=['GET'])
def get_config():
	""" Get configuration
		---
		operationId: 'getConfig'
	"""
	appConfig = config.read()
	return jsonify({'config': appConfig})

@app.route('/config', methods=['POST'])
def set_config():
	""" Set configuration
		---
		operationId: 'setConfig'
		parameters:
			- name: 'config'
			  in: body
	"""
	newConfig = json.loads(request.data)
	config.write(newConfig)
	appConfig = config.read()
	return jsonify({'config': appConfig})

@app.route('/restart', methods=['POST'])
def restart_node():
	""" Restart a cluster node
		---
		operationId: 'restartNode'
		parameters:
			- name: 'request'
			  in: body
	"""
	data = json.loads(request.data)
	cluster_id = data['cluster_id'];
	node_host = data['node_host'];
	for c_id, details in CLUSTERS.iteritems():
		if c_id == cluster_id:
			cluster_ip = details['ip']
			tasknodes_group = aws_common.get_instance_group_for_node(cluster_id, node_host)
			if tasknodes_group:
				terminate_node(cluster_ip, node_host, tasknodes_group)
				return jsonify({'result': 'SUCCESS'});
	return jsonify({'result': 'Invalid cluster ID provided'});

@app.route('/costs', methods=['POST'])
def get_costs():
	""" Get summary of cluster costs and cost savings
		---
		operationId: 'getCosts'
		parameters:
			- name: 'request'
			  in: body
	"""
	data = json.loads(request.data)
	cluster_id = data['cluster_id']
	num_datapoints = data['num_datapoints'] if 'num_datapoints' in data else 300
	baseline_nodes = data['baseline_nodes'] if 'baseline_nodes' in data else 15
	info = monitoring.history_get(cluster_id, num_datapoints)
	common.remove_NaN(info)
	result = aws_pricing.get_cluster_savings(info, baseline_nodes)
	return jsonify(results=result)

@app.route('/')
def hello():
	return render_template('index.html')

@app.route('/<path:path>')
def send_static(path):
	return send_from_directory(web_dir + '/', path)

def sort_nodes_by_load(nodes, weight_mem=1, weight_cpu=2, desc=False):
	return sorted(nodes, reverse=desc, key=lambda node: (\
			float((node['load']['mem'] if 'mem' in node['load'] else 0)*weight_mem) + \
			float((node['load']['cpu'] if 'cpu' in node['load'] else 0)*weight_cpu)))


#------------------#
# HELPER FUNCTIONS #
#------------------#

def get_autoscaling_clusters():
	return re.split(r'\s*,\s*', config.get_value(KEY_AUTOSCALING_CLUSTERS))

def get_termination_candidates(info, ignore_preferred=False, config=None):
	candidates = []
	for key, details in info['nodes'].iteritems():
		if details['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK:
			if 'queries' not in details:
				details['queries'] = 0
			# terminate only nodes with 0 queries running
			if details['queries'] == 0:
				preferred = themis.config.get_value(KEY_PREFERRED_UPSCALE_INSTANCE_MARKET, config)
				if ignore_preferred or not preferred:
					candidates.append(details)
				else:
					group_details = aws_common.get_instance_group_details(info['cluster_id'], details['gid'])
					if group_details['market'] == preferred:
						candidates.append(details)
	return candidates

def get_nodes_to_terminate(info, config=None):
	expr = themis.config.get_value(KEY_DOWNSCALE_EXPR, config)
	num_downsize = monitoring.execute_dsl_string(expr, info, config)
	LOG.info("num_downsize: %s" % num_downsize)
	if not isinstance(num_downsize, int) or num_downsize <= 0:
		return []

	candidates = get_termination_candidates(info, config=config)

	if len(candidates) <= 0:
		candidates = get_termination_candidates(info, ignore_preferred=True, config=config)

	candidates = sort_nodes_by_load(candidates, desc=False)

	result = []
	if candidates:
		for cand in candidates:
			ip = aws_common.hostname_to_ip(cand['host'])
			instance_info = {
				'iid': cand['iid'],
				'cid': cand['cid'],
				'gid': cand['gid'],
				'ip': ip
			}
			result.append(instance_info)
			if len(result) >= num_downsize:
				return result
	return result

def get_nodes_to_add(info, config=None):
	expr = themis.config.get_value(KEY_UPSCALE_EXPR, config)
	num_upsize = monitoring.execute_dsl_string(expr, info, config)
	num_upsize = int(float(num_upsize))
	LOG.info("num_upsize: %s" % num_upsize)
	if num_upsize > 0:
		return ['TODO' for i in range(0,num_upsize)]
	return []

def terminate_node(cluster_ip, node_ip, tasknodes_group):
	LOG.info("Sending shutdown signal to task node with IP '%s'" % node_ip)
	aws_common.set_presto_node_state(cluster_ip, node_ip, aws_common.PRESTO_STATE_SHUTTING_DOWN)

def spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, nodes_to_add=1):
	LOG.info("Adding new task node to cluster '%s'" % cluster_ip)
	aws_common.spawn_task_node(tasknodes_group, current_num_nodes, nodes_to_add)

def select_tasknode_group(tasknodes_groups):
	if len(tasknodes_groups) <= 0:
		raise Exception("Empty list of task node instance groups for scaling: %s" % tasknodes_groups)
	if len(tasknodes_groups) == 1:
		return tasknodes_groups[0]
	preferred = config.get_value(KEY_PREFERRED_UPSCALE_INSTANCE_MARKET)
	for group in tasknodes_groups:
		if group['market'] == preferred:
			return group
	raise Exception("Could not select task node instance group for preferred market '%s': %s" % (preferred, tasknodes_groups))


def tick():
	LOG.info("Running next loop iteration")
	monitoring_interval_secs = int(config.get_value(KEY_MONITORING_INTERVAL_SECS))
	for cluster_id, details in CLUSTERS.iteritems():
		cluster_ip = details['ip']
		info = None
		try:
			info = monitoring.collect_info(details, monitoring_interval_secs=monitoring_interval_secs)
		except Exception, e:
			LOG.warning("Error getting monitoring info for cluster %s: %s" % (cluster_id, e))
		if info:
			action = 'N/A'
			# Make sure we are only resizing Presto clusters atm
			if details['type'] == 'Presto':
				# Make sure we don't change clusters that are not configured
				if cluster_id in get_autoscaling_clusters():
					try:
						nodes_to_terminate = get_nodes_to_terminate(info)
						if len(nodes_to_terminate) > 0:
							for node in nodes_to_terminate:
								terminate_node(cluster_ip, node['ip'], node['gid'])
							action = 'DOWNSCALE(-%s)' % len(nodes_to_terminate)
						else:
							nodes_to_add = get_nodes_to_add(info)
							if len(nodes_to_add) > 0:
								tasknodes_groups = aws_common.get_instance_groups_tasknodes(cluster_id)
								tasknodes_group = select_tasknode_group(tasknodes_groups)['id']
								current_num_nodes = len([n for key,n in info['nodes'].iteritems() if n['gid'] == tasknodes_group])
								spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, len(nodes_to_add))
								action = 'UPSCALE(+%s)' % len(nodes_to_add)
							else:
								action = 'NOTHING'
					except Exception, e:
						LOG.warning("Error downscaling/upscaling cluster %s: %s" % (cluster_id, e))
					# clean up and terminate instances whose nodes are already in inactive state
					aws_common.terminate_inactive_nodes(cluster_ip, info['nodes'])
			# store the state for future reference
			monitoring.history_add(cluster_id, info, action)


def loop():
	while True:
		try:
			tick()
		except Exception, e:
			LOG.warning("Exception in main loop: %s" % (traceback.format_exc(e)))
		time.sleep(int(config.get_value(KEY_LOOP_INTERVAL_SECS)))

def serve(port):
	app.run(port=int(port), debug=True, threaded=True, host='0.0.0.0')
