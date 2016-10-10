import subprocess
import re
import os
import json
import math
import time
import themis
import traceback
from datetime import timedelta, datetime
from scipy import integrate
from themis import constants, config
from themis.util import aws_common, common
from themis.util.common import *
from themis.config import SECTION_EMR
from themis.util.remote import run_ssh
from themis.model.resources_model import *
import themis.model.emr_model

# logger
LOG = get_logger(__name__)

# get data from the last 10 minutes
MONITORING_INTERVAL_SECS = 60 * 10

# default minimum task nodes
DEFAULT_MIN_TASK_NODES = 1


def remove_array_with_NaN(array):
    i = 0
    while i < len(array):
        for item in array[i]:
            if item == 'NaN' or math.isnan(item):
                del array[i]
                i -= 1
                break
        i += 1
    return array


def get_time_duration(datapoints):
    start = float('inf')
    end = 0
    for d in datapoints:
        if d[1] > end:
            end = d[1]
        if d[1] < start:
            start = d[1]
    return end - start


def get_ganglia_datapoints(cluster, host, type, monitoring_interval_secs):
    diff_secs = monitoring_interval_secs
    format = "%m/%d/%Y %H:%M"
    start_time, end_time = get_start_and_end(diff_secs, format)
    type_param = 'mem_report' if type == 'mem' else 'cpu_report' if type == 'cpu' else 'invalid'
    url_pattern = 'http://%s/ganglia/graph.php?h=%s&cs=%s&ce=%s&c=%s&g=%s&json=1'
    result = None
    error = None
    # In some cases Ganglia is only available via public IP address
    # (necessary if running the autoscaling webserver outside AWS)
    for ip in [cluster.ip, cluster.ip_public]:
        try:
            url = url_pattern % (ip, host, start_time, end_time, cluster.id, type_param)
            cmd = "curl --connect-timeout %s '%s' 2> /dev/null" % (CURL_CONNECT_TIMEOUT, url)
            result = run(cmd, GANGLIA_CACHE_TIMEOUT)
            result = json.loads(result)
            return result
        except Exception, e:
            error = e
            # try next IP
    raise error


def get_node_load_part(cluster, host, type, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    ganglia_data = get_ganglia_datapoints(cluster, host, type, monitoring_interval_secs)
    if not ganglia_data:
        return float('NaN')
    curves_map = {}
    datapoints_map = {}

    for curve in ganglia_data:
        datapoints = curve['datapoints']
        remove_array_with_NaN(datapoints)
        rev_curve = array_reverse(datapoints)
        curve_ds_name = curve['ds_name']
        curves_map[curve_ds_name] = rev_curve
        datapoints_map[curve_ds_name] = datapoints

    if type == 'cpu':
        curve_cpu_idle = curves_map['cpu_idle']
        if len(curve_cpu_idle) < 2:
            return float('NaN')
        integrated = integrate.simps(curve_cpu_idle[0], curve_cpu_idle[1])
        time_duration = get_time_duration(datapoints_map['cpu_idle'])
        total = time_duration * 100.0
        percent = 1.0 - (integrated / total)
        return percent

    if type == 'mem':
        curve_bmem_total = curves_map['bmem_total']
        curve_bmem_free = curves_map['bmem_free']
        if len(curve_bmem_total) < 2:
            return float('NaN')
        mem_total = integrate.simps(curve_bmem_total[0], curve_bmem_total[1])
        mem_free = integrate.simps(curve_bmem_free[0], curve_bmem_free[1])
        if mem_total == 0:
            return float('NaN')
        return 1.0 - (mem_free / mem_total)

    return float('NaN')


def get_node_load_cpu(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    return get_node_load_part(cluster, host, 'cpu', monitoring_interval_secs)


def get_node_load_mem(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    return get_node_load_part(cluster, host, 'mem', monitoring_interval_secs)


def get_node_load(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    result = {}
    result['mem'] = get_node_load_mem(cluster, host, monitoring_interval_secs)
    result['cpu'] = get_node_load_cpu(cluster, host, monitoring_interval_secs)
    return result


def get_cluster_load(cluster, nodes=None, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    result = {}
    if not nodes:
        nodes = aws_common.get_cluster_nodes(cluster.id)

    def query(node):
        host = node['host']
        try:
            load = get_node_load(cluster, host, monitoring_interval_secs)
            result[host] = load
        except Exception, e:
            print(traceback.format_exc())
            LOG.warning("Unable to get load for node %s: %s" % (host, e))
            result[host] = {}

    parallelize(nodes, query)
    return result


def get_presto_node_states(nodes, cluster_ip):
    def query(host, node_info):
        node_info['presto_state'] = 'N/A'
        try:
            if node_info['state'] == aws_common.INSTANCE_STATE_RUNNING:
                state = aws_common.get_presto_node_state(cluster_ip, host)
                node_info['presto_state'] = state
        except Exception, e:
            if host[0:9] == 'testhost-':
                # for testing purposes
                node_info['presto_state'] = aws_common.PRESTO_STATE_ACTIVE
            # swallow this exception. It occurs if the node has been shutdown (i.e., JVM
            # process on node is terminated) but the instance has not been terminated yet
            pass

    parallelize(nodes, query)


def get_node_queries(cluster):
    cmd = ('presto-cli --execute \\"SELECT n.http_uri,count(q.node_id) from system.runtime.nodes n ' +
        'left join (select * from system.runtime.queries where state = \'RUNNING\' ) as q ' +
        'on q.node_id = n.node_id group by n.http_uri\\"')

    result = {}
    if cluster.ip == 'localhost':
        # for testing purposes
        return result

    # run ssh command
    out = run_ssh(cmd, cluster.ip, user='hadoop', cache_duration_secs=QUERY_CACHE_TIMEOUT)

    # remove SSH log output line
    out = remove_lines_from_string(out, r'.*Permanently added.*')

    # read config for domain
    custom_dn = config.get_value(constants.KEY_CUSTOM_DOMAIN_NAME, section=SECTION_EMR, resource=cluster.id)
    # assume input is actually domain name (not ip)
    dn = custom_dn if custom_dn else re.match(r'ip-[^\.]+\.(.+)', cluster.ip).group(1)

    for line in out.splitlines():
        ip = re.sub(r'.*http://([0-9\.]+):.*', r'\1', line)
        if ip:
            queries = re.sub(r'.*"([0-9\.]+)"$', r'\1', line)
            host = aws_common.ip_to_hostname(ip, dn)
            try:
                result[host] = int(queries)
            except Exception, e:
                result[host] = 0
    return result


def get_idle_task_nodes(queries):
    result = []
    for host in queries:
        if queries[host] == "0":
            result.append(host)
    return result


def do_add_stats(nodelist, result_map):
    result_map['average'] = {}
    result_map['sum'] = {}
    result_map['count'] = {}
    result_map['max'] = {}
    result_map['min'] = {}
    result_map['running'] = True
    result_map['active'] = True
    max_cpu = 0.0
    min_cpu = 100
    max_mem = 0.0
    min_mem = 100
    sum_cpu = 0.0
    sum_mem = 0.0
    sum_queries = 0.0
    for item in nodelist:
        if 'load' in item:
            if 'mem' in item['load'] and is_float(item['load']['mem']):
                if item['load']['mem'] > max_mem:
                    max_mem = item['load']['mem']
                if item['load']['mem'] < min_mem:
                    min_mem = item['load']['mem']
                sum_mem += item['load']['mem']

            if 'cpu' in item['load'] and is_float(item['load']['cpu']):
                if item['load']['cpu'] > max_cpu:
                    max_cpu = item['load']['cpu']
                if item['load']['cpu'] < min_cpu:
                    min_cpu = item['load']['cpu']
                sum_cpu += item['load']['cpu']

        if 'queries' in item:
            sum_queries += item['queries']
        if 'state' not in item:
            item['state'] = 'N/A'
        if item['state'] != aws_common.INSTANCE_STATE_RUNNING:
            result_map['running'] = False
        if 'presto_state' not in item:
            item['presto_state'] = 'N/A'
        if item['presto_state'] != aws_common.PRESTO_STATE_ACTIVE:
            result_map['active'] = False
    result_map['average']['cpu'] = 'NaN'
    result_map['average']['mem'] = 'NaN'
    result_map['average']['queries'] = 'NaN'
    result_map['sum']['cpu'] = 'NaN'
    result_map['sum']['mem'] = 'NaN'
    result_map['max']['cpu'] = 'NaN'
    result_map['min']['cpu'] = 'NaN'
    result_map['max']['mem'] = 'NaN'
    result_map['min']['mem'] = 'NaN'
    if len(nodelist) > 0:
        result_map['average']['cpu'] = sum_cpu / len(nodelist)
        result_map['average']['mem'] = sum_mem / len(nodelist)
        result_map['average']['queries'] = sum_queries / len(nodelist)
        result_map['sum']['cpu'] = sum_cpu
        result_map['sum']['mem'] = sum_mem
        result_map['max']['cpu'] = max_cpu
        result_map['min']['cpu'] = min_cpu
        result_map['max']['mem'] = max_mem
        result_map['min']['mem'] = min_mem
    result_map['sum']['queries'] = sum_queries
    result_map['count']['nodes'] = len(nodelist)


def add_stats(data):
    if 'nodes_list' in data:
        data['allnodes'] = {}
        do_add_stats(data['nodes_list'], data['allnodes'])

        data['tasknodes'] = {}
        data['corenodes'] = {}
        data['masternodes'] = {}
        task_nodes = [n for n in data['nodes_list'] if n['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK]
        do_add_stats(task_nodes, data['tasknodes'])
        master_nodes = [n for n in data['nodes_list'] if n['type'] == aws_common.INSTANCE_GROUP_TYPE_MASTER]
        do_add_stats(master_nodes, data['masternodes'])
        core_nodes = [n for n in data['nodes_list'] if n['type'] == aws_common.INSTANCE_GROUP_TYPE_CORE]
        do_add_stats(core_nodes, data['corenodes'])


def collect_info(cluster, nodes=None, config=None,
        monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    try:
        result = {}
        result['time_based'] = {}
        time_based_config = get_time_based_scaling_config(cluster.id, config=config)
        result['time_based']['enabled'] = len(time_based_config) > 0
        result['time_based']['minimum'] = {}
        result['nodes'] = {}
        result['cluster_id'] = cluster.id
        result['is_presto'] = cluster.type == aws_common.CLUSTER_TYPE_PRESTO
        nodes_list = nodes
        if not nodes_list:
            nodes_list = aws_common.get_cluster_nodes(cluster.id)
        for node in nodes_list:
            host = node['host']
            result['nodes'][host] = {}
            result['nodes'][host]['queries'] = 0
            result['nodes'][host]['market'] = node['market']
            for attr in ['type', 'state', 'cid', 'iid', 'gid']:
                result['nodes'][host][attr] = node[attr]
        try:
            queries = get_node_queries(cluster)
            for host in queries:
                if host not in result['nodes']:
                    result['nodes'][host] = {}
                result['nodes'][host]['queries'] = queries[host]
            result['idle_nodes'] = get_idle_task_nodes(queries)
        except subprocess.CalledProcessError, e:
            # happens for non-presto clusters (where presto-cli is not available)
            pass
        result['nodes_list'] = []
        for host in result['nodes']:
            entry = result['nodes'][host]
            entry['host'] = host
            result['nodes_list'].append(entry)
        node_infos = get_cluster_load(cluster, nodes=nodes,
            monitoring_interval_secs=monitoring_interval_secs)
        for host in node_infos:
            result['nodes'][host]['load'] = node_infos[host]
            if 'presto_state' in result['nodes'][host]:
                result['nodes'][host]['presto_state'] = node_infos[host]
        if result['is_presto']:
            get_presto_node_states(result['nodes'], cluster.ip)

        add_stats(result)
        remove_NaN(result)
        return result

    except Exception, e:
        # print(traceback.format_exc())
        LOG.warning("Error getting monitoring info for cluster %s: %s" % (cluster.id, e))
        return {}


def get_time_based_scaling_config(cluster_id, config=None):
    result = themis.config.get_value(constants.KEY_TIME_BASED_SCALING,
        config=config, default='{}', section=SECTION_EMR, resource=cluster_id)
    try:
        return json.loads(result)
    except Exception, e:
        return {}


def update_resources(resource_config):
    return resource_config


def init_emr_config(run_parallel=False):
    cfg = ResourcesConfiguration()

    def init_emr_cluster_config(c):
        if c['Status']['State'][0:10] != 'TERMINATED':
            out1 = run('aws emr describe-cluster --cluster-id=%s' % c['Id'], retries=1)
            out1 = json.loads(out1)
            cluster_details = out1['Cluster']
            cluster = themis.model.emr_model.EmrCluster()
            cluster.id = c['Id']
            cluster.name = c['Name']
            cluster.ip = 'N/A'
            cluster.ip_public = cluster_details['MasterPublicDnsName']
            has_ganglia = False
            for app in out1['Cluster']['Applications']:
                if app['Name'] == 'Hive' and not cluster.type:
                    cluster.type = 'Hive'
                if app['Name'][0:6] == 'Presto':
                    cluster.type = 'Presto'
                if app['Name'] == 'Ganglia':
                    has_ganglia = True
            if has_ganglia:
                LOG.info('Getting details for EMR cluster %s' % cluster.id)
                # get private IP address of cluster
                for g in cluster_details['InstanceGroups']:
                    if g['InstanceGroupType'] == 'MASTER':
                        cmd = ('aws emr list-instances --cluster-id=%s --instance-states ' +
                            'AWAITING_FULFILLMENT PROVISIONING BOOTSTRAPPING RUNNING') % c['Id']
                        out2 = run(cmd, retries=6)
                        if not out2:
                            LOG.warning("No output for command '%s'" % cmd)
                        out2 = json.loads(out2)
                        for inst in out2['Instances']:
                            if inst['InstanceGroupId'] == g['Id']:
                                cluster.ip = inst['PrivateDnsName']
                cfg.emr.append(cluster)
            else:
                LOG.info('Ignoring cluster %s (Ganglia not installed)' % cluster.id)

    # load EMR resources
    out = run('aws emr list-clusters')
    out = json.loads(out)
    if run_parallel:
        common.parallelize(out['Clusters'], init_emr_cluster_config)
    else:
        for c in out['Clusters']:
            init_emr_cluster_config(c)
    return cfg
