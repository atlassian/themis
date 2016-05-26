from themis.scaling.server import *
from themis.util import common, aws_common
from constants import *
import mock.ganglia
import os

server = None

def mock_cluster_state(nodes=0, config=None):
	task_nodes = []
	for i in range(0,nodes):
		node = {}
		node['type'] = aws_common.INSTANCE_GROUP_TYPE_TASK
		node['gid'] = 'testGID'
		node['cid'] = 'testCID-%s' % common.short_uid()
		node['iid'] = 'testIID-%s' % common.short_uid()
		node['host'] = 'testhost-%s' % common.short_uid()
		node['state'] = aws_common.INSTANCE_STATE_RUNNING
		node['presto_state'] = aws_common.PRESTO_STATE_ACTIVE
		task_nodes.append(node)
	cluster_info = {
		'id': 'testCluster',
		'ip': 'localhost:%s' % GANGLIA_PORT,
		'ip_public': 'localhost:%s' % GANGLIA_PORT,
		'type': aws_common.CLUSTER_TYPE_PRESTO
	}
	info = monitoring.collect_info(cluster_info, task_nodes=task_nodes)
	print(info)
	return info

def get_server():
	global server
	if not server:
		server = mock.ganglia.serve(GANGLIA_PORT)
	return server

def test_upscale():
	common.QUERY_CACHE_TIMEOUT = 0
	config = []
	config.append({KEY: KEY_UPSCALE_EXPR, VAL: "3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 15 and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0"})
	server = get_server()

	server.cpu = 90 # mock 90% CPU usage
	server.mem = 50 # mock 50% memory usage
	info = mock_cluster_state(nodes=4, config=config)
	nodes = get_nodes_to_add(info, config)
	assert(len(nodes) == 3)

	server.cpu = 30 # mock 30% CPU usage
	info = mock_cluster_state(nodes=4, config=config)
	nodes = get_nodes_to_add(info, config)
	assert(len(nodes) == 0)

def test_downscale():
	common.QUERY_CACHE_TIMEOUT = 0
	config = []
	config.append({KEY: KEY_DOWNSCALE_EXPR, VAL: "1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes >= 2 and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0"})
	server = get_server()

	server.cpu = 90 # mock 90% CPU usage
	server.mem = 50 # mock 50% memory usage
	info = mock_cluster_state(nodes=4, config=config)
	nodes = get_nodes_to_terminate(info, config)
	assert(len(nodes) == 0)

	server.cpu = 40 # mock 40% CPU usage
	server.mem = 80 # mock 80% memory usage
	info = mock_cluster_state(nodes=4, config=config)
	nodes = get_nodes_to_terminate(info, config)
	assert(len(nodes) == 1)

