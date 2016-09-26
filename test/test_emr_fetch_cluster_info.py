import os
import json
from constants import *
from themis.util import common, aws_common
import mock.aws_api

server = None


def init_mocks():
    global server
    try:
        tmp = os.environ.AWS_ENDPOINT_URL
    except AttributeError, e:
        os.environ.AWS_ENDPOINT_URL = 'http://%s:%s/aws' % (LOCALHOST, AWS_API_PORT)
        server = mock.aws_api.serve(AWS_API_PORT)
        mock.aws_api.init_aws_cli()


def test_list_instances():
    init_mocks()
    server.config['group_id_task_spot'] = 'group_task_spot'
    server.config['group_id_task_od'] = 'group_task_od'

    out = common.run("aws emr list-instances --cluster-id=testClusterID1", log_error=True)
    out = json.loads(out)
    assert len(out['Instances']) > 0

    nodes = aws_common.get_cluster_nodes('testClusterID1')
    assert len(nodes) > 1


def test_aws_cli():
    init_mocks()

    out = common.run("aws emr list-clusters", log_error=True)
    out = json.loads(out)
    assert out['Clusters'][0]['Id'] == 'testClusterID1'
