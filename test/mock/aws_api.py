from flask import Flask, request, make_response, jsonify
from flask_swagger import swagger
import json
import re
import time
import os
import threading
from themis.util import common
from constants import *

num_spot_nodes = 5
num_od_nodes = 2


def serve(port, daemon=True):
    class AwsApiApp(threading.Thread):
        def __init__(self):
            threading.Thread.__init__(self)
            self.config = {}
            self.app = Flask('testapp')

        def run(self):
            @self.app.route('/<path:path>', methods=['GET', 'PUT', 'POST', 'DELETE'])
            def handle(path):
                result = mock_aws_api(request.method, path, request, self.config)
                return result
            self.app.run(port=int(port), host=BIND_HOST)
    app = AwsApiApp()
    app.daemon = daemon
    app.start()
    time.sleep(1)
    return app


def init_aws_cli():
    home = os.path.expanduser("~")
    folder = '%s/.aws' % home
    if not os.path.exists(folder):
        os.makedirs(folder)
    file_config = '%s/.aws/config' % home
    if not os.path.isfile(file_config):
        common.save_file(file_config, "[default]\nregion = us-east-1")
    file_creds = '%s/.aws/credentials' % home
    if not os.path.isfile(file_creds):
        common.save_file(file_creds, "[default]\naws_access_key_id = testAccessKeyId\n" +
            "aws_secret_access_key = testSecretKey")


def mock_aws_api(method, path, req, config={}):
    result = {}
    target = req.headers['X-Amz-Target']
    print(target)
    if target == 'ElasticMapReduce.ListClusters':
        result = {
            "Clusters": [
                {
                    "Id": "testClusterID1",
                    "Name": "testCluster1",
                    "NormalizedInstanceHours": 1,
                    "Status": {
                        "State": "WAITING"
                    }
                }
            ]
        }
    elif target == 'ElasticMapReduce.ListInstances':
        result = {
            "Instances": []
        }
        for i in range(0, num_spot_nodes + num_od_nodes):
            gid = common.short_uid()
            if i < num_spot_nodes and 'group_id_task_spot' in config:
                gid = config['group_id_task_spot']
            if i >= num_spot_nodes and 'group_id_task_od' in config:
                gid = config['group_id_task_od']
            inst = {
                "Status": {
                    "State": "RUNNING",
                },
                "Id": common.short_uid(),
                "InstanceGroupId": gid,
                "Ec2InstanceId": common.short_uid(),
                "PublicDnsName": "",
                "PrivateDnsName": "testhost-%s" % common.short_uid(),
                "PublicIpAddress": LOCALHOST,
                "PrivateIpAddress": LOCALHOST
            }
            result['Instances'].append(inst)
    elif target == 'ElasticMapReduce.DescribeCluster':
        request = json.loads(req.data)
        cluster_id = request['ClusterId']
        result = {
            "Cluster": {
                "Name": "TestClusterName",
                "Id": cluster_id,
                "MasterPublicDnsName": "testhost-%s" % common.short_uid(),
                "ReleaseLabel": "emr-4.1.0",
                "Status": {
                    "State": "RUNNING"
                },
                "Ec2InstanceAttributes": {
                    "EmrManagedMasterSecurityGroup": "sg-%s" % common.short_uid(),
                    "EmrManagedSlaveSecurityGroup": "sg-%s" % common.short_uid(),
                    "Ec2SubnetId": "subnet-%s" % common.short_uid(),
                    "IamInstanceProfile": "EMR_EC2_DefaultRole",
                    "Ec2KeyName": "testKey",
                    "Ec2AvailabilityZone": "us-east-1b"
                }
            }
        }
    elif target == 'ElasticMapReduce.ListInstanceGroups':
        result = {
            "InstanceGroups": []
        }
        for t in ['master', 'core', 'task_od', 'task_spot']:
            key = 'group_id_%s' % t
            group_id = "%s" % (config[key] if key in config else 'group_%s' % t)
            g = {
                "RequestedInstanceCount": 1,
                "Status": {
                    "State": "RUNNING",
                },
                "Name": t,
                "InstanceGroupType": t.split('_')[0].upper(),
                "Id": group_id,
                "InstanceType": "c3.xlarge",
                "Market": ("SPOT" if t == 'task_spot' else "ON_DEMAND")
            }
            result['InstanceGroups'].append(g)

    elif target == 'ElasticMapReduce.ListBootstrapActions':
        result = {}
        # TODO!

    return jsonify(result)


if __name__ == "__main__":
    serve(AWS_API_PORT, daemon=False).join()
