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
from themis.util import aws_common, common, math_util
from themis.util.common import *
from themis.config import SECTION_EMR
from themis.util.remote import run_ssh
from themis.model.resources_model import *
import themis.model.emr_model

# logger
LOG = get_logger(__name__)

# get data from the last 10 minutes by default
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
    type_param = ('%s_report' % type) if type in ('mem', 'cpu', 'load') else 'invalid'
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

    elif type == 'mem':
        curve_bmem_total = curves_map['bmem_total']
        curve_bmem_free = curves_map['bmem_free']
        if len(curve_bmem_total) < 2:
            return float('NaN')
        mem_total = integrate.simps(curve_bmem_total[0], curve_bmem_total[1])
        mem_free = integrate.simps(curve_bmem_free[0], curve_bmem_free[1])
        if mem_total == 0:
            return float('NaN')
        return 1.0 - (mem_free / mem_total)

    elif type == 'load':
        curve_load = curves_map['a0']
        if len(curve_load) < 2:
            return float('NaN')
        avg_load = math_util.get_stats(curve_load[0])['avg']
        return avg_load

    return float('NaN')


def get_node_load_cpu(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    return get_node_load_part(cluster, host, 'cpu', monitoring_interval_secs)


def get_node_load_mem(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    return get_node_load_part(cluster, host, 'mem', monitoring_interval_secs)


def get_node_load_sysload(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    return get_node_load_part(cluster, host, 'load', monitoring_interval_secs)


def get_node_load(cluster, host, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    result = {}
    try:
        result['mem'] = get_node_load_mem(cluster, host, monitoring_interval_secs)
        result['cpu'] = get_node_load_cpu(cluster, host, monitoring_interval_secs)
        result['sysload'] = get_node_load_sysload(cluster, host, monitoring_interval_secs)
    except Exception, e:
        LOG.warn('Unable to get Ganglia monitoring data for cluster / host: %s / %s' % (cluster.ip, host))
        raise e
    return result


def get_cluster_load(cluster, nodes=None, monitoring_interval_secs=MONITORING_INTERVAL_SECS):
    result = {}
    role = get_iam_role_for_cluster(cluster)

    if not nodes:
        nodes = aws_common.get_cluster_nodes(cluster.id, role=role)

    def query(node):
        host = node['host']
        try:
            load = get_node_load(cluster, host, monitoring_interval_secs)
            result[host] = load
        except Exception, e:
            # LOG.warning(traceback.format_exc())
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

    load_aggregates = ('average', 'sum', 'min', 'max')
    all_aggregates = load_aggregates + ('count', )
    load_metrics = ('cpu', 'mem', 'sysload')
    all_metrics = load_metrics + ('queries', )

    # initialize maps
    map_min = {}
    map_max = {}
    map_sum = {}
    for m in all_metrics:
        map_min[m] = 100.0
        map_max[m] = 0.0
        map_sum[m] = 0.0
    for agg in all_aggregates:
        result_map[agg] = {}
    result_map['running'] = True
    result_map['active'] = True

    for item in nodelist:
        if 'load' in item:
            for metr in load_metrics:
                item_value = item['load'].get(metr)
                if is_float(item_value):
                    if item_value > map_max[metr]:
                        map_max[metr] = item_value
                    if item_value < map_min[metr]:
                        map_min[metr] = item_value
                    map_sum[metr] += item_value

        if 'queries' in item:
            map_sum['queries'] += item['queries']
        if 'state' not in item:
            item['state'] = 'N/A'
        if item['state'] != aws_common.INSTANCE_STATE_RUNNING:
            result_map['running'] = False
        if 'presto_state' not in item:
            item['presto_state'] = 'N/A'
        if item['presto_state'] != aws_common.PRESTO_STATE_ACTIVE:
            if result_map['active']:
                LOG.info('Status of node %s is %s, setting "<nodes>.active=False"' %
                    (item.get('host'), item['presto_state']))
            result_map['active'] = False

    # initialize result map with NaN values
    for metric in all_metrics:
        for aggr in load_aggregates:
            if aggr not in ('min', 'max') or metric not in ('queries'):
                result_map[aggr][metric] = 'NaN'
    # set actual node values
    if len(nodelist) > 0:
        for metr in all_metrics:
            result_map['average'][metr] = map_sum[metr] / len(nodelist)
        for metr in load_metrics:
            result_map['sum'][metr] = map_sum[metr]
            result_map['min'][metr] = map_min[metr]
            result_map['max'][metr] = map_max[metr]
    result_map['sum']['queries'] = map_sum['queries']
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
        # LOG.info('Collect monitoring info for cluster %s' % cluster.id)
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
            role = get_iam_role_for_cluster(cluster)
            nodes_list = aws_common.get_cluster_nodes(cluster.id, role=role)
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
                if host in result['nodes']:
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
        LOG.warning("Error getting monitoring info for cluster %s: %s" % (cluster.id, e))
        LOG.warning(traceback.format_exc())
        return {}


def get_time_based_scaling_config(cluster_id, config=None):
    result = themis.config.get_value(constants.KEY_TIME_BASED_SCALING,
        config=config, default='{}', section=SECTION_EMR, resource=cluster_id)
    try:
        return json.loads(result)
    except Exception, e:
        return {}


def reload_resource(resource):
    # TODO
    pass


def update_resources(resource_config, resource=None):
    return resource_config


def list_all_clusters(role=None):
    emr_client = aws_common.connect_emr(role=role)
    result = []
    marker = None
    for i in range(0, 10):
        kwargs = {}
        if marker:
            kwargs['Marker'] = marker
        out = emr_client.list_clusters(**kwargs)
        result.extend(out['Clusters'])
        marker = out.get('Marker')
        if not marker:
            break
    return result


def get_iam_role_for_cluster(cluster):
    if not isinstance(cluster, basestring):
        cluster = cluster.id
    return config.get_value('role_to_assume', section=SECTION_EMR, resource=cluster)


def init_emr_config(run_parallel=False, role=None):
    cfg = ResourcesConfiguration()

    emr_client = aws_common.connect_emr(role=role)

    def init_emr_cluster_config(c):
        if c['Status']['State'][0:10] != 'TERMINATED':
            out1 = emr_client.describe_cluster(ClusterId=c['Id'])
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
                group_details = emr_client.list_instance_groups(ClusterId=c['Id'])
                for g in group_details['InstanceGroups']:
                    if g['InstanceGroupType'] == 'MASTER':
                        out2 = emr_client.list_instances(ClusterId=c['Id'],
                            InstanceStates=['AWAITING_FULFILLMENT', 'PROVISIONING', 'BOOTSTRAPPING', 'RUNNING'])
                        for inst in out2['Instances']:
                            if inst['InstanceGroupId'] == g['Id']:
                                cluster.ip = inst['PrivateDnsName']
                cfg.emr.append(cluster)
            else:
                LOG.info('Ignoring cluster %s (Ganglia not installed)' % cluster.id)

    # load EMR resources
    try:
        clusters = list_all_clusters(role=role)
        if run_parallel:
            common.parallelize(clusters, init_emr_cluster_config)
        else:
            for c in clusters:
                init_emr_cluster_config(c)
    except Exception, e:
        LOG.info('Unable to list EMR clusters using IAM role "%s"' % role)
    return cfg
