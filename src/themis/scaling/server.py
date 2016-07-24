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

# logger
LOG = common.get_logger(__name__)

# map of configured clusters
CLUSTERS = {}
for val in config.CLUSTER_LIST:
    CLUSTERS[val['id']] = val


def sort_nodes_by_load(nodes, weight_mem=1, weight_cpu=2, desc=False):
    return sorted(nodes, reverse=desc, key=lambda node: (
        float((node['load']['mem'] if 'mem' in node['load'] else 0) * weight_mem) +
        float((node['load']['cpu'] if 'cpu' in node['load'] else 0) * weight_cpu)))


def get_autoscaling_clusters():
    return re.split(r'\s*,\s*', config.get_value(KEY_AUTOSCALING_CLUSTERS))


def get_termination_candidates(info, ignore_preferred=False, config=None):
    candidates = []
    cluster_id = info['cluster_id']
    for key, details in info['nodes'].iteritems():
        if details['type'] == aws_common.INSTANCE_GROUP_TYPE_TASK:
            if 'queries' not in details:
                details['queries'] = 0
            # terminate only nodes with 0 queries running
            if details['queries'] == 0:
                preferred = themis.config.get_value(KEY_PREFERRED_UPSCALE_INSTANCE_MARKET, config, section=cluster_id)
                if ignore_preferred or not preferred:
                    candidates.append(details)
                else:
                    group_details = aws_common.get_instance_group_details(cluster_id, details['gid'])
                    if group_details['market'] == preferred:
                        candidates.append(details)
    return candidates


def get_nodes_to_terminate(info, config=None):
    cluster_id = info['cluster_id']
    expr = themis.config.get_value(KEY_DOWNSCALE_EXPR, config=config, section=cluster_id)
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
    cluster_id = info['cluster_id']
    expr = themis.config.get_value(KEY_UPSCALE_EXPR, config, section=cluster_id)
    num_upsize = monitoring.execute_dsl_string(expr, info, config)
    num_upsize = int(float(num_upsize))
    LOG.info("num_upsize: %s" % num_upsize)
    if num_upsize > 0:
        return ['TODO' for i in range(0, num_upsize)]
    return []


def terminate_node(cluster_ip, node_ip, tasknodes_group):
    LOG.info("Sending shutdown signal to task node with IP '%s'" % node_ip)
    aws_common.set_presto_node_state(cluster_ip, node_ip, aws_common.PRESTO_STATE_SHUTTING_DOWN)


def spawn_nodes(cluster_ip, tasknodes_group, current_num_nodes, nodes_to_add=1):
    LOG.info("Adding new task node to cluster '%s'" % cluster_ip)
    aws_common.spawn_task_node(tasknodes_group, current_num_nodes, nodes_to_add)


def select_tasknode_group(tasknodes_groups, cluster_id):
    if len(tasknodes_groups) <= 0:
        raise Exception("Empty list of task node instance groups for scaling: %s" % tasknodes_groups)
    if len(tasknodes_groups) == 1:
        return tasknodes_groups[0]
    preferred = config.get_value(KEY_PREFERRED_UPSCALE_INSTANCE_MARKET, cluster_id)
    for group in tasknodes_groups:
        if group['market'] == preferred:
            return group
    raise Exception("Could not select task node instance group for preferred market '%s': %s" %
            (preferred, tasknodes_groups))


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
