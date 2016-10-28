from flask import Flask, request, make_response, jsonify
from flask_swagger import swagger
import json
import re
import datetime
import os
import threading
from themis.util import common
from constants import *
import time

num_spot_nodes = 5
num_od_nodes = 2

server = None

TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
TIMESTAMP_FORMAT_MS = '%Y-%m-%dT%H:%M:%S.%fZ'


def init_mocks():
    global server
    if not server:
        server = serve(AWS_API_PORT)


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


def parse_time(time, format=TIMESTAMP_FORMAT):
    return datetime.datetime.strptime(time, format)


def mock_aws_api(method, path, req, config={}):
    result = {}
    target = req.headers.get('X-Amz-Target')
    # print(target)
    # print(path)
    metric_name = req.form.get('MetricName') if req.form else None
    namespace = req.form.get('Namespace') if req.form else None
    if path == 'aws/cloudwatch/get-metric-statistics' or (metric_name and namespace):
        action = req.form.get('Action')
        if action == 'GetMetricStatistics':
            stats = []
            dimensions = {}
            start_time = parse_time(req.form.get('StartTime'), format=TIMESTAMP_FORMAT_MS)
            end_time = parse_time(req.form.get('EndTime'), format=TIMESTAMP_FORMAT_MS)
            period = int(req.form.get('Period'))
            datapoints = ''

            for i in range(1, 10):
                stat = req.form.get('Statistics.member.%s' % i)
                if not stat:
                    break
                stats.append(stat)

            for i in range(1, 10):
                key = req.form.get('Dimensions.member.%s.Name' % i)
                if not key:
                    break
                dimensions[key] = req.form.get('Dimensions.member.%s.Value' % i)

            timestamp = start_time
            key = 'cloudwatch.%s.value' % metric_name
            value = config.get(key) or 0
            while timestamp < end_time:
                datapoints += """<member><Timestamp>%s</Timestamp><Unit>%s</Unit><Average>%s</Average></member>
                    """ % (timestamp.strftime(TIMESTAMP_FORMAT), "TODO", value)
                timestamp += datetime.timedelta(seconds=period)

            result_str = """<GetMetricStatisticsResponse xmlns="http://monitoring.amazonaws.com/doc/2010-08-01/">
                  <GetMetricStatisticsResult>
                    <Datapoints>%s</Datapoints>
                    <Label>IncomingBytes</Label>
                  </GetMetricStatisticsResult>
                </GetMetricStatisticsResponse>""" % datapoints
            result_str

            return make_response(result_str)
    elif target == 'ElasticMapReduce.ListClusters':
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
                "Market": ('SPOT' if t == 'task_spot' else 'ON_DEMAND')
            }
            result['InstanceGroups'].append(g)

    elif target == 'Kinesis_20131202.DescribeStream':
        shards = []
        num_shards = config.get('kinesis.num_shards') or 1
        keys_per_shard = long('340282366920938463463374607431768211455') / long(num_shards)
        start_key = long(0)
        for i in range(0, num_shards):
            shards.append({
                "ShardId": "shardId-00000000000%s" % i,
                "HashKeyRange": {
                    "EndingHashKey": str(long(start_key + keys_per_shard)),
                    "StartingHashKey": str(start_key)
                },
                "SequenceNumberRange": {
                    "StartingSequenceNumber": "49566574182713195037261772394799414734632859404425232418"
                }
            })
            start_key = long(start_key + keys_per_shard)
        result = {
            "StreamDescription": {"Shards": shards}
        }

    elif target == 'ElasticMapReduce.ListBootstrapActions':
        result = {}
        # TODO!

    return jsonify(result)


if __name__ == "__main__":
    serve(AWS_API_PORT, daemon=False).join()
