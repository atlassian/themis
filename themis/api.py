from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_swagger import swagger
import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config, server
from themis.config import *
from themis.constants import *
from themis.util import common, aws_common, aws_pricing
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK
from themis.scaling import emr_scaling
from themis.monitoring import resources, emr_monitoring, kinesis_monitoring, database

root_path = os.path.dirname(os.path.realpath(__file__))
web_dir = root_path + '/web/'

app = Flask('app', template_folder=web_dir)
app.root_path = root_path


# -----------------------
# Generic top-level APIs
# -----------------------


@app.route('/swagger.json')
def spec():
    swag = swagger(app)
    swag['info']['version'] = "1.1"
    swag['info']['title'] = "Themis Autoscaling API"
    return jsonify(swag)


@app.route('/config/<section>', methods=['GET'])
def get_global_config(section):
    """ Get global configuration
        ---
        operationId: 'getGlobalConfig'
        parameters:
            - name: 'section'
              in: path
    """
    return do_get_config(section)


@app.route('/config/<section>/<resource>', methods=['GET'])
def get_config(section, resource):
    """ Get configuration
        ---
        operationId: 'getConfig'
        parameters:
            - name: 'section'
              in: path
            - name: 'resource'
              in: path
    """
    return do_get_config(section, resource)


@app.route('/config/<section>/', methods=['POST'])
def set_global_config(section):
    """ Set global configuration
        ---
        operationId: 'setGlobalConfig'
        parameters:
            - name: 'config'
              in: body
            - name: 'section'
              in: path
    """
    new_config = json.loads(request.data)
    return do_set_config(section, new_config)


@app.route('/config/<section>/<resource>', methods=['POST'])
def set_config(section, resource=None):
    """ Set configuration
        ---
        operationId: 'setConfig'
        parameters:
            - name: 'config'
              in: body
            - name: 'section'
              in: path
            - name: 'resource'
              in: path
    """
    new_config = json.loads(request.data)
    return do_set_config(section, new_config, resource=resource)


def do_get_config(section, resource=None):
    cfg = config.get_config()
    cfg = cfg.get(section)
    if resource:
        cfg = cfg.get(resource)
    cfg = cfg.to_dict() if cfg else {}
    cfg = config.convert_to_list(cfg)
    return jsonify({'config': cfg})


def do_set_config(section, new_config, resource=None):
    if isinstance(new_config, list):
        new_config = config.convert_from_list(new_config)
    config.write(new_config, section=section, resource=resource)
    cfg = config.get_config(force_load=True)
    cfg = cfg.get(section)
    if resource:
        cfg = cfg.get(resource)
    cfg = cfg.to_dict() if cfg else {}
    cfg = config.convert_to_list(cfg)
    return jsonify({'config': cfg})


# ----------------------------------------
# EMR specific APIs, prefixed with /emr/
# ----------------------------------------


@app.route('/emr/state/<cluster_id>')
def get_emr_state(cluster_id):
    """ Get EMR cluster state
        ---
        operationId: 'getEmrState'
        parameters:
            - name: cluster_id
              in: path
    """
    app_config = config.get_config()
    cluster = resources.get_resource(SECTION_EMR, cluster_id)
    monitoring_interval_secs = int(app_config.general.monitoring_time_window)
    info = emr_monitoring.collect_info(cluster, monitoring_interval_secs=monitoring_interval_secs)
    return jsonify(info)


@app.route('/emr/history/<cluster_id>')
def get_emr_history(cluster_id):
    """ Get EMR cluster state history
        ---
        operationId: 'getEmrHistory'
        parameters:
            - name: 'cluster_id'
              in: path
    """
    info = database.history_get(section=SECTION_EMR, resource=cluster_id, limit=100)
    common.remove_NaN(info)
    return jsonify(results=info)


@app.route('/emr/clusters')
def get_emr_clusters():
    """ Get list of EMR clusters
        ---
        operationId: 'getEmrClusters'
    """
    resource_list = resources.get_resources('emr')
    result = [r.to_dict() for r in resource_list]
    return jsonify(results=result)


@app.route('/emr/restart', methods=['POST'])
def restart_emr_node():
    """ Restart a cluster node
        ---
        operationId: 'restartEmrNode'
        parameters:
            - name: 'request'
              in: body
    """
    data = json.loads(request.data)
    cluster_id = data['cluster_id']
    node_host = data['node_host']
    for c_id, details in CLUSTERS.iteritems():
        if c_id == cluster_id:
            cluster_ip = details['ip']
            tasknodes_group = aws_common.get_instance_group_for_node(cluster_id, node_host)
            if tasknodes_group:
                server.terminate_node(cluster_ip, node_host, tasknodes_group)
                return jsonify({'result': 'SUCCESS'})
    return jsonify({'result': 'Invalid cluster ID provided'})


@app.route('/emr/costs', methods=['POST'])
def get_emr_costs():
    """ Get summary of cluster costs and cost savings
        ---
        operationId: 'getEmrCosts'
        parameters:
            - name: 'request'
              in: body
    """
    data = json.loads(request.data)
    cluster_id = data['cluster_id']
    num_datapoints = data['num_datapoints'] if 'num_datapoints' in data else 300
    baseline_nodes = (data['baseline_nodes'] if 'baseline_nodes' in data else
        config.get_value(KEY_BASELINE_COMPARISON_NODES, section=SECTION_EMR, resource=cluster_id, default=20))
    baseline_nodes = int(baseline_nodes)
    info = database.history_get(section=SECTION_EMR, resource=cluster_id, limit=num_datapoints)
    common.remove_NaN(info)
    result = aws_pricing.get_cluster_savings(info, baseline_nodes)
    common.remove_NaN(result, delete_values=False, replacement=0)
    return jsonify(results=result, baseline_nodes=baseline_nodes)


# -----------------------------------------------
# Kinesis specific APIs, prefixed with /kinesis/
# -----------------------------------------------

@app.route('/kinesis/streams')
def get_kinesis_streams():
    """ Get list of Kinesis streams
        ---
        operationId: 'getKinesisStreams'
    """
    resource_list = resources.get_resources('kinesis')
    result = [r.to_dict() for r in resource_list]
    return jsonify(results=result)


@app.route('/kinesis/state/<stream_id>')
def get_kinesis_state(stream_id):
    """ Get Kinesis stream state
        ---
        operationId: 'getKinesisState'
        parameters:
            - name: stream_id
              in: path
    """
    app_config = config.get_config()
    stream = resources.get_resource(SECTION_KINESIS, stream_id)
    monitoring_interval_secs = int(app_config.general.monitoring_time_window)
    info = kinesis_monitoring.collect_info(stream, monitoring_interval_secs=monitoring_interval_secs)
    return jsonify(info)


@app.route('/kinesis/history/<stream_id>')
def get_kinesis_history(stream_id):
    """ Get Kinesis stream state history
        ---
        operationId: 'getKinesisHistory'
        parameters:
            - name: 'stream_id'
              in: path
    """
    info = database.history_get(section=SECTION_KINESIS, resource=stream_id, limit=100)
    common.remove_NaN(info)
    return jsonify(results=info)


# ------------------------
# Addition default routes
# ------------------------


@app.route('/')
def hello():
    return render_template('index.html')


@app.route('/<path:path>')
def send_static(path):
    return send_from_directory(web_dir + '/', path)


def serve(port):
    app.run(port=int(port), debug=True, threaded=True, host='0.0.0.0')
