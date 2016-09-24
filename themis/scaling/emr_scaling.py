import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config
from themis.constants import *
from themis.util import common, aws_common, aws_pricing
from themis.monitoring import emr_monitoring
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK

# map of configured clusters
CLUSTERS = {}
for val in config.CLUSTER_LIST:
    CLUSTERS[val['id']] = val

# logger
LOG = common.get_logger(__name__)


def sort_nodes_by_load(nodes, weight_mem=1, weight_cpu=2, desc=False):
    return sorted(nodes, reverse=desc, key=lambda node: (
        float((node['load']['mem'] if 'mem' in node['load'] else 0) * weight_mem) +
        float((node['load']['cpu'] if 'cpu' in node['load'] else 0) * weight_cpu)))


def get_autoscaling_clusters():
    return re.split(r'\s*,\s*', config.get_value(KEY_AUTOSCALING_CLUSTERS))


def get_termination_candidates(info, config=None):
    result = []
    cluster_id = info['cluster_id']
    preferred = themis.config.get_value(KEY_PREFERRED_INSTANCE_MARKET, config, section=cluster_id, default='')
    if not preferred:
        preferred = [MARKET_SPOT, MARKET_ON_DEMAND]
    else:
        preferred = re.split("\s*,\s*", preferred)
    for market in preferred:
        if market:
            cand = get_termination_candidates_for_market(info, market=market)
            result.extend(cand)
    return result


def get_termination_candidates_for_market(info, market):
    candidates = []
    cluster_id = info['cluster_id']
    for key, details in info['nodes'].iteritems():
        if details['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK:
            if 'queries' not in details:
                details['queries'] = 0
            # terminate only nodes with 0 queries running
            if details['queries'] == 0:
                group_details = aws_common.get_instance_group_details(cluster_id, details['gid'])
                if group_details['Market'] == market:
                    candidates.append(details)
    return candidates


def get_nodes_to_terminate(info, config=None):
    cluster_id = info['cluster_id']
    expr = themis.config.get_value(KEY_DOWNSCALE_EXPR, config=config, section=cluster_id)
    num_downsize = emr_monitoring.execute_dsl_string(expr, info, config)
    LOG.info("Cluster %s: num_downsize: %s" % (cluster_id, num_downsize))
    if not isinstance(num_downsize, int) or num_downsize <= 0:
        return []

    candidates = get_termination_candidates(info, config=config)
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
    cluster_id = info['cluster_id']
    expr = themis.config.get_value(KEY_UPSCALE_EXPR, config, section=cluster_id)
    num_upsize = emr_monitoring.execute_dsl_string(expr, info, config)
    num_upsize = int(float(num_upsize))
    LOG.info("Cluster %s: num_upsize: %s" % (cluster_id, num_upsize))
    if num_upsize > 0:
        return ['TODO' for i in range(0, num_upsize)]
    return []


def terminate_node(cluster, node):
    cluster_ip = cluster['ip']
    node_ip = node['ip']
    instance_id = node['iid']
    tasknodes_group = node['gid']
    if aws_common.is_presto_cluster(cluster):
        LOG.info("Sending shutdown signal to Presto task node with IP '%s'" % node_ip)
        aws_common.set_presto_node_state(cluster_ip, node_ip, aws_common.PRESTO_STATE_SHUTTING_DOWN)
    else:
        LOG.info("Terminating task node with instance ID '%s' in group '%s'" % (instance_id, tasknodes_group))
        aws_common.terminate_task_node(instance_group_id=tasknodes_group, instance_id=instance_id)


def spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, nodes_to_add=1):
    LOG.info("Adding new task node to cluster '%s'" % cluster_ip)
    aws_common.spawn_task_node(tasknodes_group, current_num_nodes, nodes_to_add)


def select_tasknode_group(tasknodes_groups, cluster_id):
    if len(tasknodes_groups) <= 0:
        raise Exception("Empty list of task node instance groups for scaling: %s" % tasknodes_groups)
    if len(tasknodes_groups) == 1:
        return tasknodes_groups[0]
    preferred = config.get_value(KEY_PREFERRED_INSTANCE_MARKET, section=cluster_id)
    for group in tasknodes_groups:
        if group['Market'] == preferred:
            return group
    raise Exception("Could not select task node instance group for preferred market '%s': %s" %
            (preferred, tasknodes_groups))


def tick():
    LOG.info("Running next loop iteration")
    monitoring_interval_secs = int(config.get_value(KEY_MONITORING_INTERVAL_SECS))
    for cluster_id, cluster_details in CLUSTERS.iteritems():
        cluster_ip = cluster_details['ip']
        info = None
        try:
            info = emr_monitoring.collect_info(cluster_details, monitoring_interval_secs=monitoring_interval_secs)
        except Exception, e:
            LOG.warning("Error getting monitoring info for cluster %s: %s" % (cluster_id, e))
        if info:
            action = 'N/A'
            # Make sure we don't change clusters that are not configured
            if cluster_id in get_autoscaling_clusters():
                try:
                    nodes_to_terminate = get_nodes_to_terminate(info)
                    if len(nodes_to_terminate) > 0:
                        for node in nodes_to_terminate:
                            terminate_node(cluster_details, node)
                        action = 'DOWNSCALE(-%s)' % len(nodes_to_terminate)
                    else:
                        nodes_to_add = get_nodes_to_add(info)
                        if len(nodes_to_add) > 0:
                            tasknodes_groups = aws_common.get_instance_groups_tasknodes(cluster_id)
                            tasknodes_group = select_tasknode_group(tasknodes_groups, cluster_id)['id']
                            current_num_nodes = len([n for key, n in info['nodes'].iteritems()
                                if n['gid'] == tasknodes_group])
                            spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, len(nodes_to_add))
                            action = 'UPSCALE(+%s)' % len(nodes_to_add)
                        else:
                            action = 'NOTHING'
                except Exception, e:
                    LOG.warning("WARNING: Error downscaling/upscaling cluster %s: %s" %
                        (cluster_id, traceback.format_exc(e)))
                # clean up and terminate instances whose nodes are already in inactive state
                aws_common.terminate_inactive_nodes(cluster_details, info)
            # store the state for future reference
            emr_monitoring.history_add(cluster_id, info, action)
