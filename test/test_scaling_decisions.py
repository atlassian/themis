from themis.scaling.server import *
from themis.util import common, aws_common
from themis import config
from constants import *
import mock.ganglia
import datetime

server = None


def mock_cluster_state(spot_nodes=0, od_nodes=0, config=None):
    task_nodes = []

    def add_node(gid):
        node = {}
        node['type'] = aws_common.INSTANCE_GROUP_TYPE_TASK
        node['gid'] = gid
        node['cid'] = 'testCID-%s' % common.short_uid()
        node['iid'] = 'testIID-%s' % common.short_uid()
        node['host'] = 'testhost-%s' % common.short_uid()
        node['state'] = aws_common.INSTANCE_STATE_RUNNING
        node['presto_state'] = aws_common.PRESTO_STATE_ACTIVE
        node['market'] = 'dummyvalue'
        task_nodes.append(node)

    for i in range(0, spot_nodes):
        add_node('group_task_spot')
    for i in range(0, od_nodes):
        add_node('group_task_od')

    cluster_info = {
        'id': 'testCluster',
        'ip': 'localhost:%s' % GANGLIA_PORT,
        'ip_public': 'localhost:%s' % GANGLIA_PORT,
        'type': aws_common.CLUSTER_TYPE_PRESTO
    }
    info = monitoring.collect_info(cluster_info, config=config, nodes=task_nodes)
    return info


def get_server():
    global server
    if not server:
        server = mock.ganglia.serve(GANGLIA_PORT)
    return server


def test_upscale():
    common.QUERY_CACHE_TIMEOUT = 0
    config = []
    config.append({KEY: KEY_UPSCALE_EXPR,
        VAL: """3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
                and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0"""})
    themis.config.TEST_CONFIG = config
    server = get_server()

    server.cpu = 90  # mock 90% CPU usage
    server.mem = 50  # mock 50% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_add(info, config)
    assert(len(nodes) == 3)

    server.cpu = 30  # mock 30% CPU usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_add(info, config)
    assert(len(nodes) == 0)


def test_upscale_time_based():
    common.QUERY_CACHE_TIMEOUT = 0
    MIN_NODES = """{
        "(Mon|Tue|Wed|Thu|Fri).*00:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*01:.*:.*": 14,
        "(Mon|Tue|Wed|Thu|Fri).*02:.*:.*": 12,
        "(Mon|Tue|Wed|Thu|Fri).*03:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*04:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*05:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*06:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*07:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*08:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*09:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*10:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*11:.*:.*": 5,
        "(Mon|Tue|Wed|Thu|Fri).*12:.*:.*": 5,
        "(Mon|Tue|Wed|Thu|Fri).*13:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*14:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*15:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*16:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*17:.*:.*": 7,
        "(Mon|Tue|Wed|Thu|Fri).*18:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*19:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*20:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*21:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*22:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*23:.*:.*": 10}
    """
    config = []
    # Tuesday
    test_date = datetime.datetime(2016, 05, 31, 1)
    config.append({KEY: KEY_NOW, VAL: test_date})
    config.append({KEY: KEY_TIME_BASED_SCALING, VAL: MIN_NODES})
    config.append({KEY: KEY_UPSCALE_EXPR,
        VAL: """(time_based.minimum.nodes(now) - tasknodes.count.nodes) if \
                (time_based.enabled and time_based.minimum.nodes(now) > tasknodes.count.nodes) \
                else (3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
                and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0)"""})

    themis.config.TEST_CONFIG = config
    server = get_server()
    server.cpu = 90  # mock 90% CPU usage
    server.mem = 50  # mock 50% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_add(info, config)
    assert (len(nodes) == 10)

    info = mock_cluster_state(spot_nodes=14, config=config)
    nodes = get_nodes_to_add(info, config)
    assert (len(nodes) == 3)


def test_downscale():
    common.QUERY_CACHE_TIMEOUT = 0
    config = []
    config.append({KEY: KEY_DOWNSCALE_EXPR,
        VAL: """1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > 2 and \
            tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0"""})
    themis.config.TEST_CONFIG = config

    server = get_server()

    server.cpu = 90  # mock 90% CPU usage
    server.mem = 50  # mock 50% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert(len(nodes) == 0)

    server.cpu = 40  # mock 40% CPU usage
    server.mem = 80  # mock 80% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert(len(nodes) == 1)


def test_downscale_time_based():
    common.QUERY_CACHE_TIMEOUT = 0
    MIN_NODES = """{
        "(Mon|Tue|Wed|Thu|Fri).*00:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*01:.*:.*": 14,
        "(Mon|Tue|Wed|Thu|Fri).*02:.*:.*": 12,
        "(Mon|Tue|Wed|Thu|Fri).*03:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*04:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*05:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*06:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*07:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*08:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*09:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*10:.*:.*": 4,
        "(Mon|Tue|Wed|Thu|Fri).*11:.*:.*": 5,
        "(Mon|Tue|Wed|Thu|Fri).*12:.*:.*": 5,
        "(Mon|Tue|Wed|Thu|Fri).*13:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*14:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*15:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*16:.*:.*": 6,
        "(Mon|Tue|Wed|Thu|Fri).*17:.*:.*": 7,
        "(Mon|Tue|Wed|Thu|Fri).*18:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*19:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*20:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*21:.*:.*": 8,
        "(Mon|Tue|Wed|Thu|Fri).*22:.*:.*": 10,
        "(Mon|Tue|Wed|Thu|Fri).*23:.*:.*": 10
    }"""
    config = []
    # Tuesday
    test_date = datetime.datetime(2016, 05, 31, 1)
    config.append({KEY: KEY_NOW, VAL: test_date})
    config.append({KEY: KEY_TIME_BASED_SCALING, VAL: MIN_NODES})
    config.append({KEY: KEY_DOWNSCALE_EXPR,
        VAL: """1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > time_based.minimum.nodes(now) \
            and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0"""})

    themis.config.TEST_CONFIG = config

    server.cpu = 40  # mock 40% CPU usage
    server.mem = 80  # mock 80% memory usage
    info = mock_cluster_state(spot_nodes=17, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert(len(nodes) == 1)

    server.cpu = 40  # mock 40% CPU usage
    server.mem = 30  # mock 30% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert (len(nodes) == 0)


def assert_downscale_preferred_market(config_market, od_nodes=0, spot_nodes=0, expected_od_downscale=0,
                                      expected_spot_downscale=0, num_downscale=1):

    common.QUERY_CACHE_TIMEOUT = 0
    config = []
    config.append({KEY: KEY_DOWNSCALE_EXPR,
        VAL: """%s if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > 2 and \
            tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0""" % num_downscale})
    config.append({KEY: KEY_PREFERRED_INSTANCE_MARKET, VAL: config_market})
    themis.config.TEST_CONFIG = config

    server = get_server()

    server.cpu = 40  # mock 40% CPU usage
    server.mem = 80  # mock 80% memory usage
    info = mock_cluster_state(od_nodes=od_nodes, spot_nodes=spot_nodes, config=config)
    nodes = get_nodes_to_terminate(info, config)
    c_spot_nodes = 0
    c_od_nodes = 0
    for n in nodes:
        if n['gid'] == 'group_task_spot':
            c_spot_nodes += 1
        if n['gid'] == 'group_task_od':
            c_od_nodes += 1
    assert(c_spot_nodes == expected_spot_downscale)
    assert(c_od_nodes == expected_od_downscale)


def test_downscale_preferred_market():
    assert_downscale_preferred_market('', 0, 4, 0, 1)
    assert_downscale_preferred_market('', 4, 0, 1, 0)
    assert_downscale_preferred_market('', 4, 4, 0, 1)
    assert_downscale_preferred_market('', 4, 1, 0, 1)
    assert_downscale_preferred_market('', 1, 4, 0, 1)
    assert_downscale_preferred_market('SPOT', 0, 4, 0, 1)
    assert_downscale_preferred_market('ON_DEMAND', 4, 0, 1, 0)
    assert_downscale_preferred_market('SPOT,ON_DEMAND', 4, 4, 0, 1)
    assert_downscale_preferred_market('ON_DEMAND,SPOT', 4, 4, 1, 0)
    assert_downscale_preferred_market('SPOT,ON_DEMAND', 4, 4, 0, 2, 2)
    assert_downscale_preferred_market('ON_DEMAND,SPOT', 4, 4, 2, 0, 2)
    assert_downscale_preferred_market('SPOT,ON_DEMAND', 4, 1, 1, 1, 2)
    assert_downscale_preferred_market('ON_DEMAND,SPOT', 1, 4, 1, 1, 2)
