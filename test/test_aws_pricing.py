from themis.util import aws_pricing, common
from themis.util.exceptions import *


def mock_history(num_nodes=10):
    result = []
    num_points = 10
    t = common.now() * 1000
    for i in range(0, num_points):
        state = {
            'tasknodes': [],
            'allnodes': []
        }
        group1 = {
            'instances': []
        }
        group2 = {
            'instances': []
        }
        state['groups'] = {
            'testGID1': group1,
            'testGID2': group2
        }
        for j in range(0, num_nodes):
            node = {
                'iid': 'testIID%s' % j
            }
            group1['instances'].append(node)
            group2['instances'].append(node)
            state['tasknodes'].append(node)
            state['allnodes'].append(node)

        point = {
            'timestamp': t,
            'state': state
        }
        result.append(point)
        t += 5 * 60 * 1000
    return result


def test_pricing():
    try:
        baseline_nodes = 10
        info = mock_history(num_nodes=10)
        savings = aws_pricing.get_cluster_savings(info, baseline_nodes)
        assert abs(savings['saved']) < 0.00000001

        baseline_nodes = 15
        info = mock_history(num_nodes=10)
        savings = aws_pricing.get_cluster_savings(info, baseline_nodes)
        assert savings['saved'] > 1 and savings['saved'] < 10
    except ConnectivityException, e:
        print('Connectivity problems, skipping pricing test...')
