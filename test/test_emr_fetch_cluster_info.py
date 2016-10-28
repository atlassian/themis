import os
import json
from constants import *
from themis.util import common, aws_common
import mock.aws_api


def setup():
    mock.aws_api.init_mocks()


def test_list_instances():
    import constants

    mock.aws_api.server.config['group_id_task_spot'] = 'group_task_spot'
    mock.aws_api.server.config['group_id_task_od'] = 'group_task_od'

    emr_client = aws_common.connect_emr()

    out = emr_client.list_instances(ClusterId='testClusterID1')
    assert len(out['Instances']) > 0

    nodes = aws_common.get_cluster_nodes('testClusterID1')
    assert len(nodes) > 1


def test_aws_cli():
    emr_client = aws_common.connect_emr()

    out = emr_client.list_clusters()
    assert out['Clusters'][0]['Id'] == 'testClusterID1'
