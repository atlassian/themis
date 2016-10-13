import os
import json
from constants import *
from themis.util import common, aws_common
import mock.aws_api


def setup():
    mock.aws_api.init_mocks()


def test_list_instances():
    mock.aws_api.server.config['group_id_task_spot'] = 'group_task_spot'
    mock.aws_api.server.config['group_id_task_od'] = 'group_task_od'

    out = common.run("aws emr list-instances --cluster-id=testClusterID1", log_error=True)
    out = json.loads(out)
    assert len(out['Instances']) > 0

    nodes = aws_common.get_cluster_nodes('testClusterID1')
    assert len(nodes) > 1


def test_aws_cli():
    out = common.run("aws emr list-clusters", log_error=True)
    out = json.loads(out)
    assert out['Clusters'][0]['Id'] == 'testClusterID1'
