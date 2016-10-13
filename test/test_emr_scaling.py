from datetime import datetime
from themis import config
from themis.scaling.emr_scaling import *
from themis.monitoring.emr_monitoring import *
from themis.util import common, aws_common
from themis.config import *
from themis.model.emr_model import *
from constants import *
import mock.aws_api
import mock.ganglia

server = None

TEST_CLUSTER_ID = 'testCluster'


def setup():
    mock.aws_api.init_mocks()


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

    cluster = EmrCluster(id=TEST_CLUSTER_ID)
    cluster.ip = 'localhost:%s' % GANGLIA_PORT
    cluster.ip_public = 'localhost:%s' % GANGLIA_PORT
    cluster.type = aws_common.CLUSTER_TYPE_PRESTO
    info = emr_monitoring.collect_info(cluster, config=config, nodes=task_nodes)
    return info


def get_server():
    global server
    if not server:
        server = mock.ganglia.serve(GANGLIA_PORT)
    return server


def get_test_cluster_config(upscale_expr=None, downscale_expr=None, now=None,
        time_based_scaling=None, preferred_market=None):
    config = SystemConfiguration()
    cluster_config = EmrClusterConfiguration()
    # per-cluster configs
    if upscale_expr is not None:
        cluster_config.upscale_expr = upscale_expr
    if downscale_expr is not None:
        cluster_config.downscale_expr = downscale_expr
    if time_based_scaling is not None:
        cluster_config.time_based_scaling = time_based_scaling
    if preferred_market is not None:
        cluster_config.group_or_preferred_market = preferred_market
    # global configs
    if now is not None:
        config.general.now = now
    config.emr.set(TEST_CLUSTER_ID, cluster_config)
    themis.config.TEST_CONFIG = config
    return config


def test_upscale():
    common.QUERY_CACHE_TIMEOUT = 0
    config = get_test_cluster_config(
        upscale_expr="""3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
            and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0""")
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

    config = get_test_cluster_config(
        upscale_expr="""3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
            and (tasknodes.min.cpu > 0.8 or tasknodes.min.mem > 0.8)) else 0""")

    server.cpu = 90  # mock 90% CPU usage
    server.mem = 50  # mock 50% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_add(info, config)
    assert (len(nodes) == 3)

    server.cpu = 70  # mock 70% CPU usage
    server.mem = 50  # mock 50% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_add(info, config)
    assert (len(nodes) == 0)


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
    test_date = datetime(2016, 05, 31, 1)
    config = get_test_cluster_config(now=test_date, time_based_scaling=MIN_NODES,
        upscale_expr="""(time_based.minimum.nodes(now) - tasknodes.count.nodes) if \
            (time_based.enabled and time_based.minimum.nodes(now) > tasknodes.count.nodes) \
            else (3 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes < 25 \
            and (tasknodes.average.cpu > 0.7 or tasknodes.average.mem > 0.95)) else 0)""")

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
    config = get_test_cluster_config(preferred_market=MARKET_SPOT,
        downscale_expr="""1 if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > 2 and \
            tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0""")

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

    config = get_test_cluster_config(preferred_market=MARKET_SPOT,
        downscale_expr="""1 if (tasknodes.running and tasknodes.active and
            tasknodes.count.nodes > 2 and tasknodes.max.cpu < 0.2 and tasknodes.max.mem < 0.2) else 0""")

    server.cpu = 10  # mock 10% CPU usage
    server.mem = 90  # mock 90% memory free

    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert(len(nodes) == 1)

    server.cpu = 30  # mock 30% CPU usage
    server.mem = 90  # mock 10% memory usage
    info = mock_cluster_state(spot_nodes=4, config=config)
    nodes = get_nodes_to_terminate(info, config)
    assert (len(nodes) == 0)


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
    # Tuesday
    test_date = datetime(2016, 05, 31, 1)
    config = get_test_cluster_config(now=test_date, time_based_scaling=MIN_NODES,
        downscale_expr="""1 if (tasknodes.running and tasknodes.active and \
            tasknodes.count.nodes > time_based.minimum.nodes(now) \
            and tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0""")

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
    config = get_test_cluster_config(preferred_market=config_market,
        downscale_expr="""%s if (tasknodes.running and tasknodes.active and tasknodes.count.nodes > 2 and \
            tasknodes.average.cpu < 0.5 and tasknodes.average.mem < 0.9) else 0""" % num_downscale)

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
