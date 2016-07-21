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
from themis.scaling import server
from themis.constants import *
from themis.util import common, monitoring, aws_common, aws_pricing
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK

root_path = os.path.dirname(os.path.realpath(__file__))
web_dir = root_path + '/../../../web/'

app = Flask('app', template_folder=web_dir)
app.root_path = root_path

CLUSTERS = server.CLUSTERS

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

@app.route('/config/<section>', methods=['GET'])
def get_config(section):
	""" Get configuration
		---
		operationId: 'getConfig'
		parameters:
			- name: 'section'
			  in: path
	"""
	appConfig = config.read(section=section)
	return jsonify({'config': appConfig})

@app.route('/config/<section>', methods=['POST'])
def set_config(section):
	""" Set configuration
		---
		operationId: 'setConfig'
		parameters:
			- name: 'config'
			  in: body
			- name: 'section'
			  in: path
	"""
	newConfig = json.loads(request.data)
	config.write(newConfig, section=section)
	appConfig = config.read(section=section)
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
				server.terminate_node(cluster_ip, node_host, tasknodes_group)
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


def serve(port):
	app.run(port=int(port), debug=True, threaded=True, host='0.0.0.0')
