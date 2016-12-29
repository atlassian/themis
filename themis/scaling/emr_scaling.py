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
from themis.util import common, aws_common, aws_pricing, expr
from themis.monitoring import emr_monitoring, database
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK

# logger
LOG = common.get_logger(__name__)


def sort_nodes_by_load(nodes, weight_mem=1, weight_cpu=2, desc=False):
    return sorted(nodes, reverse=desc, key=lambda node: (
        float((node['load'].get('mem', 0)) * weight_mem) +
        float((node['load'].get('cpu', 0)) * weight_cpu)))


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
            result = execute_dsl_string(preferred, info, config)
            if not isinstance(result, (list, tuple)):
                result = [str(result)]
            return result
    except Exception, e:
        # unable to parse as expression, continue below...
        pass
    # return verbatim strings, split by comma
    result = [item for item in re.split("\s*,\s*", preferred) if item]
    return result


def remove_duplicates(nodes):
    result = []
    for n in nodes:
        contained = False
        for n1 in result:
            if n1.get('iid') == n.get('iid') and n1.get('cid') == n.get('cid'):
                contained = True
        if not contained:
            result.append(n)
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
    role = emr_monitoring.get_iam_role_for_cluster(cluster_id)
    for key, details in info['nodes'].iteritems():
        if details['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK:
            if 'queries' not in details:
                details['queries'] = 0
            # terminate only nodes with 0 queries running
            if details['queries'] == 0:
                group_details = aws_common.get_instance_group_details(cluster_id, details['gid'], role=role)
                if preferred in [group_details['Market'], group_details['id']]:
                    candidates.append(details)
    return candidates


# TODO: merge with execute_dsl_string in util/expr.py !
def execute_dsl_string(dsl_str, context, config=None):
    expr_context = expr.ExprContext(context)
    allnodes = expr_context.allnodes
    tasknodes = expr_context.tasknodes
    time_based = expr_context.time_based
    cluster_id = context['cluster_id']

    def get_min_nodes_for_cluster(date):
        return get_minimum_nodes(date, cluster_id)
    time_based.minimum.nodes = get_min_nodes_for_cluster
    now = datetime.utcnow()
    now_override = themis.config.get_value(KEY_NOW, config=config, default=None)
    if now_override:
        now = now_override

    return eval(dsl_str)


# returns nodes if based on regex dict values
# assumes no overlapping entries as will grab the first item it matches.
def get_minimum_nodes(date, cluster_id):
    now_str = date.strftime("%a %Y-%m-%d %H:%M:%S")

    # This is only used for testing, to overwrite the config. If TEST_CONFIG is
    # None (which is the default), then the actual configuration will be used.
    config = themis.config.TEST_CONFIG

    pattern_to_nodes = emr_monitoring.get_time_based_scaling_config(cluster_id=cluster_id, config=config)
    nodes_to_return = None
    for pattern, num_nodes in pattern_to_nodes.iteritems():
        if re.match(pattern, now_str):
            if nodes_to_return is None:
                nodes_to_return = num_nodes
            else:
                LOG.warning(("'%s' Regex Pattern has matched more than once:\nnodes_to_return=%d " +
                    "is now changing to nodes_to_return=%d") % (pattern, nodes_to_return, num_nodes))
                nodes_to_return = num_nodes
    # no match revert to default
    if nodes_to_return is None:
        return emr_monitoring.DEFAULT_MIN_TASK_NODES
    return nodes_to_return


def get_nodes_to_terminate(info, config=None):
    cluster_id = info['cluster_id']
    if not config:
        config = themis.config.get_config()
    expr = config.get(SECTION_EMR, cluster_id, KEY_DOWNSCALE_EXPR)
    num_downsize = execute_dsl_string(expr, info, config)
    LOG.info("Cluster %s: num_downsize: %s" % (cluster_id, num_downsize))
    if not isinstance(num_downsize, int) or num_downsize <= 0:
        return []

    candidates_orig = get_termination_candidates(info, config=config)
    candidates = remove_duplicates(candidates_orig)
    candidates = sort_nodes_by_load(candidates, desc=False)

    if len(candidates) < num_downsize:
        LOG.warning('Not enough candidate nodes to perform downsize operation: %s < %s' %
            (len(candidates), num_downsize))
        cluster_id = info['cluster_id']
        preferred_list = get_node_groups_or_preferred_markets(cluster_id, info=info, config=config)
        LOG.warning('Initial candidates, preferred inst. groups: %s - %s' % (candidates_orig, preferred_list))

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
    num_upsize = execute_dsl_string(expr, info, config)
    num_upsize = int(float(num_upsize))
    LOG.info("Cluster %s: num_upsize: %s" % (cluster_id, num_upsize))
    if num_upsize > 0:
        return ['TODO' for i in range(0, num_upsize)]
    return []


def terminate_node(cluster, node, config=None):
    if not config:
        config = themis.config.get_config()
    node_ip = node['ip']
    instance_id = node['iid']
    tasknodes_group = node['gid']
    shutdown_signal = config.get(SECTION_EMR, cluster.id, KEY_SEND_SHUTDOWN_SIGNAL)
    if aws_common.is_presto_cluster(cluster) and shutdown_signal == 'true':
        LOG.info("Sending shutdown signal to Presto task node with IP '%s'" % node_ip)
        aws_common.set_presto_node_state(cluster.ip, node_ip, aws_common.PRESTO_STATE_SHUTTING_DOWN)
    else:
        LOG.info("Terminating task node with instance ID '%s' in group '%s'" % (instance_id, tasknodes_group))
        role = emr_monitoring.get_iam_role_for_cluster(cluster)
        aws_common.terminate_task_node(instance_group_id=tasknodes_group, instance_id=instance_id, role=role)


def spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, nodes_to_add=1, role=None):
    LOG.info("Adding new task node to cluster '%s'" % cluster_ip)
    aws_common.spawn_task_node(tasknodes_group, current_num_nodes, nodes_to_add, role=role)


def select_tasknode_group(tasknodes_groups, cluster_id, info=None):
    if len(tasknodes_groups) <= 0:
        raise Exception("Empty list of task node instance groups for scaling: %s" % tasknodes_groups)
    if len(tasknodes_groups) == 1:
        return tasknodes_groups[0]
    preferred_list = get_node_groups_or_preferred_markets(cluster_id, info=info)
    LOG.info('List of preferred TASK node groups: %s' % preferred_list)
    for preferred in preferred_list:
        for group in tasknodes_groups:
            if preferred in [group['Market'], group['id']]:
                return group
    raise Exception("Could not select task node instance group for preferred market %s: %s" %
            (preferred_list, tasknodes_groups))


def add_history_entry(cluster, state, action):
    nodes = state['nodes']
    state['nodes'] = {}
    del state['nodes_list']
    state['groups'] = {}
    for key, val in nodes.iteritems():
        group_id = val['gid']
        if group_id not in state['groups']:
            state['groups'][group_id] = {'instances': []}
        state['groups'][group_id]['instances'].append({
            'iid': val['iid']
            # TODO add more relevant data to persist
        })
    database.history_add(section=SECTION_EMR, resource=cluster.id, state=state, action=action)


def perform_scaling(cluster):
    app_config = config.get_config()
    monitoring_interval_secs = int(app_config.general.monitoring_time_window)
    info = cluster.monitoring_data
    if info:
        action = 'N/A'
        # Make sure we don't change clusters that are not configured
        autoscaling_clusters = app_config.general.get_autoscaling_clusters()
        if cluster.id in autoscaling_clusters:
            role = emr_monitoring.get_iam_role_for_cluster(cluster)
            try:
                nodes_to_terminate = get_nodes_to_terminate(info)
                if len(nodes_to_terminate) > 0:
                    for node in nodes_to_terminate:
                        terminate_node(cluster, node, config=app_config)
                    action = 'DOWNSCALE(-%s)' % len(nodes_to_terminate)
                else:
                    nodes_to_add = get_nodes_to_add(info)
                    if len(nodes_to_add) > 0:
                        tasknodes_groups = aws_common.get_instance_groups_tasknodes(cluster.id, role=role)
                        tasknodes_group = select_tasknode_group(tasknodes_groups, cluster.id, info=info)['id']
                        current_num_nodes = len([n for key, n in info['nodes'].iteritems()
                            if n['gid'] == tasknodes_group])
                        spawn_nodes(cluster.ip, tasknodes_group, current_num_nodes, len(nodes_to_add), role=role)
                        action = 'UPSCALE(+%s)' % len(nodes_to_add)
                    else:
                        action = 'NOTHING'
            except Exception, e:
                LOG.warning("WARNING: Error downscaling/upscaling cluster %s: %s" %
                    (cluster.id, traceback.format_exc(e)))
            # clean up and terminate instances whose nodes are already in inactive state
            aws_common.terminate_inactive_nodes(cluster, info, role=role)
        # store the state for future reference
        add_history_entry(cluster, info, action)
