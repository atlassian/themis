import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config
from themis.config import *
from themis.constants import *
from themis.util import common, aws_common, aws_pricing
from themis.monitoring import emr_monitoring, database
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK

# logger
LOG = common.get_logger(__name__)


def sort_nodes_by_load(nodes, weight_mem=1, weight_cpu=2, desc=False):
    return sorted(nodes, reverse=desc, key=lambda node: (
        float((node['load']['mem'] if 'mem' in node['load'] else 0) * weight_mem) +
        float((node['load']['cpu'] if 'cpu' in node['load'] else 0) * weight_cpu)))


def get_node_groups_or_preferred_markets(cluster_id, info=None, config=None):
    if not config:
        config = themis.config.get_config()
    cluster_config = config.get(SECTION_EMR, cluster_id)
    preferred = cluster_config.group_or_preferred_market
    if not preferred:
        return [MARKET_SPOT, MARKET_ON_DEMAND]
    # try to evaluate as an expression
    try:
        if info:
            result = emr_monitoring.execute_dsl_string(preferred, info, config)
            if not isinstance(result, (list, tuple)):
                result = [str(result)]
            return result
    except Exception, e:
        # unable to parse as expression, continue below...
        pass
    # return verbatim strings, split by comma
    result = [item for item in re.split("\s*,\s*", preferred) if item]
    return result


def get_termination_candidates(info, config=None):
    result = []
    cluster_id = info['cluster_id']
    preferred_list = get_node_groups_or_preferred_markets(cluster_id, info=info, config=config)
    for preferred in preferred_list:
        cand = get_termination_candidates_for_market_or_group(info, preferred=preferred)
        result.extend(cand)
    return result


def get_termination_candidates_for_market_or_group(info, preferred):
    candidates = []
    cluster_id = info['cluster_id']
    for key, details in info['nodes'].iteritems():
        if details['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK:
            if 'queries' not in details:
                details['queries'] = 0
            # terminate only nodes with 0 queries running
            if details['queries'] == 0:
                group_details = aws_common.get_instance_group_details(cluster_id, details['gid'])
                if preferred in [group_details['Market'], group_details['id']]:
                    candidates.append(details)
    return candidates


def get_nodes_to_terminate(info, config=None):
    cluster_id = info['cluster_id']
    if not config:
        config = themis.config.get_config()
    expr = config.get(SECTION_EMR, cluster_id, KEY_DOWNSCALE_EXPR)
    num_downsize = emr_monitoring.execute_dsl_string(expr, info, config)
    LOG.info("Cluster %s: num_downsize: %s" % (cluster_id, num_downsize))
    if not isinstance(num_downsize, int) or num_downsize <= 0:
        return []

    candidates = get_termination_candidates(info, config=config)
    candidates = sort_nodes_by_load(candidates, desc=False)

    if len(candidates) < num_downsize:
        LOG.warning('Not enough candidate nodes to perform downsize operation: %s < %s' %
            (len(candidates), num_downsize))

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
    if not config:
        config = themis.config.get_config()
    cluster_id = info['cluster_id']
    expr = config.get(SECTION_EMR, cluster_id, KEY_UPSCALE_EXPR)
    num_upsize = emr_monitoring.execute_dsl_string(expr, info, config)
    num_upsize = int(float(num_upsize))
    LOG.info("Cluster %s: num_upsize: %s" % (cluster_id, num_upsize))
    if num_upsize > 0:
        return ['TODO' for i in range(0, num_upsize)]
    return []


def terminate_node(cluster, node):
    node_ip = node['ip']
    instance_id = node['iid']
    tasknodes_group = node['gid']
    if aws_common.is_presto_cluster(cluster):
        LOG.info("Sending shutdown signal to Presto task node with IP '%s'" % node_ip)
        aws_common.set_presto_node_state(cluster.ip, node_ip, aws_common.PRESTO_STATE_SHUTTING_DOWN)
    else:
        LOG.info("Terminating task node with instance ID '%s' in group '%s'" % (instance_id, tasknodes_group))
        aws_common.terminate_task_node(instance_group_id=tasknodes_group, instance_id=instance_id)


def spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, nodes_to_add=1):
    LOG.info("Adding new task node to cluster '%s'" % cluster_ip)
    aws_common.spawn_task_node(tasknodes_group, current_num_nodes, nodes_to_add)


def select_tasknode_group(tasknodes_groups, cluster_id, info=None):
    if len(tasknodes_groups) <= 0:
        raise Exception("Empty list of task node instance groups for scaling: %s" % tasknodes_groups)
    if len(tasknodes_groups) == 1:
        return tasknodes_groups[0]
    preferred_list = get_node_groups_or_preferred_markets(cluster_id, info=info)
    for preferred in preferred_list:
        for group in tasknodes_groups:
            if preferred in [group['Market'], group['id']]:
                return group
    raise Exception("Could not select task node instance group for preferred market %s: %s" %
            (preferred_list, tasknodes_groups))


def perform_scaling(cluster):
    app_config = config.get_config()
    monitoring_interval_secs = int(app_config.general.monitoring_time_window)
    info = cluster.monitoring_data
    if info:
        action = 'N/A'
        # Make sure we don't change clusters that are not configured
        if cluster.id in app_config.general.get_autoscaling_clusters():
            try:
                nodes_to_terminate = get_nodes_to_terminate(info)
                if len(nodes_to_terminate) > 0:
                    for node in nodes_to_terminate:
                        terminate_node(cluster, node)
                    action = 'DOWNSCALE(-%s)' % len(nodes_to_terminate)
                else:
                    nodes_to_add = get_nodes_to_add(info)
                    if len(nodes_to_add) > 0:
                        tasknodes_groups = aws_common.get_instance_groups_tasknodes(cluster.id)
                        tasknodes_group = select_tasknode_group(tasknodes_groups, cluster.id, info=info)['id']
                        current_num_nodes = len([n for key, n in info['nodes'].iteritems()
                            if n['gid'] == tasknodes_group])
                        spawn_nodes(cluster.ip, tasknodes_group, current_num_nodes, len(nodes_to_add))
                        action = 'UPSCALE(+%s)' % len(nodes_to_add)
                    else:
                        action = 'NOTHING'
            except Exception, e:
                LOG.warning("WARNING: Error downscaling/upscaling cluster %s: %s" %
                    (cluster.id, traceback.format_exc(e)))
            # clean up and terminate instances whose nodes are already in inactive state
            aws_common.terminate_inactive_nodes(cluster, info)
        # store the state for future reference
        database.history_add(cluster.id, info, action)
