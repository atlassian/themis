import re
import json
import logging
import boto3
import os
import pytz
from datetime import datetime
from themis import config, constants
from themis.config import SECTION_EMR
from themis.util.common import run_func, remove_lines_from_string, get_logger, short_uid, is_ip_address
from themis.util.common import CURL_CONNECT_TIMEOUT, STATIC_INFO_CACHE_TIMEOUT, QUERY_CACHE_TIMEOUT
from themis.util.remote import run_ssh

# constants

PRESTO_STATE_SHUTTING_DOWN = 'SHUTTING_DOWN'
PRESTO_STATE_ACTIVE = 'ACTIVE'

INSTANCE_GROUP_TYPE_MASTER = 'MASTER'
INSTANCE_GROUP_TYPE_CORE = 'CORE'
INSTANCE_GROUP_TYPE_TASK = 'TASK'

INSTANCE_STATE_RUNNING = 'RUNNING'
INSTANCE_STATE_TERMINATED = 'TERMINATED'

INVALID_CONFIG_VALUE = '_invalid_value_to_avoid_restart_'

CW_TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# TODO move to model
CLUSTER_TYPE_PRESTO = 'Presto'
CLUSTER_TYPE_HIVE = 'Hive'

# Define local test endpoints
TEST_ENDPOINTS = {}

# Keep a reference to the initial boto3 session with default credentials
INITIAL_BOTO3_SESSION = None

# Map role ARNs to sessions with assumed roles
ASSUMED_ROLE_SESSIONS = {}

# Timespan before expiry to renew session
SESSION_EXPIRY_RENEW_PERIOD = 10 * 60

# logger
LOG = get_logger(__name__)


class StsSession(object):
    def __init__(self, role_arn):
        self.session = None
        self.role_arn = role_arn

    def get(self):
        if not self.role_arn:
            # work with default boto3 session
            return boto3
        if not self.session or self.expires_soon():
            # create a new boto3 session using assume-role
            self.session = do_assume_role(self.role_arn)
        return self.session

    def expires_soon(self):
        return session_expires_soon(self.session)


def session_expires_soon(session):
    exp = session.expiration
    now = datetime.now()
    # make dates substractable
    exp = exp.replace(tzinfo=None)
    now = now.replace(tzinfo=None)
    # get delta
    delta = (exp - now).total_seconds()
    return delta < SESSION_EXPIRY_RENEW_PERIOD


def init_aws_cli():
    endpoint_url = os.environ.AWS_ENDPOINT_URL
    if endpoint_url:
        TEST_ENDPOINTS['emr'] = endpoint_url
        TEST_ENDPOINTS['kinesis'] = endpoint_url
        TEST_ENDPOINTS['cloudwatch'] = endpoint_url
        TEST_ENDPOINTS['ec2'] = endpoint_url


def connect_emr(session=None, role=None):
    return connect_to_service('emr', session=session, role=role)


def connect_kinesis(session=None, role=None):
    return connect_to_service('kinesis', session=session, role=role)


def connect_cloudwatch(session=None, role=None):
    return connect_to_service('cloudwatch', session=session, role=role)


def connect_ec2(session=None, role=None):
    return connect_to_service('ec2', session=session, role=role)


def connect_to_service(service, session=None, role=None):
    session = session if session else assume_role(role) if role else None
    endpoint_url = TEST_ENDPOINTS.get(service)
    boto3_session = session.get() if session else boto3
    return boto3_session.client(service, endpoint_url=endpoint_url)


def assume_role(role_arn):
    return StsSession(role_arn)


def do_assume_role(role_arn):
    session = ASSUMED_ROLE_SESSIONS.get(role_arn)
    if not session or session_expires_soon(session):
        global INITIAL_BOTO3_SESSION
        # save initial session with micros credentials to use for assuming role
        if not INITIAL_BOTO3_SESSION:
            INITIAL_BOTO3_SESSION = boto3.session.Session()
        client = INITIAL_BOTO3_SESSION.client('sts')
        # generate a random role session name
        role_session_name = 's-' + str(short_uid())
        # make API call to assume role
        response = client.assume_role(RoleArn=role_arn, RoleSessionName=role_session_name)
        # save session with new credentials to use for all aws calls
        session = boto3.session.Session(
            aws_access_key_id=response['Credentials']['AccessKeyId'],
            aws_secret_access_key=response['Credentials']['SecretAccessKey'],
            aws_session_token=response['Credentials']['SessionToken'])
        session.expiration = response['Credentials']['Expiration']
        # store session for future reference
        ASSUMED_ROLE_SESSIONS[role_arn] = session
    return session


def ip_to_hostname(ip, domain_name):
    return 'ip-' + re.sub(r'\.', r'-', ip) + '.' + domain_name


def hostname_to_ip(host):
    return re.sub(r'ip-([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)\..+', r'\1.\2.\3.\4', host)


def parse_cloudwatch_timestamp(timestamp, tzinfo=pytz.UTC):
    time = datetime.strptime(timestamp, CW_TIMESTAMP_FORMAT)
    time = time.replace(tzinfo=tzinfo)
    return time


def format_cloudwatch_timestamp(timestamp):
    return timestamp.strftime(CW_TIMESTAMP_FORMAT)


def get_instance_by_ip(ip, role=None):
    ec2_client = connect_ec2(role=role)
    result = run_func(ec2_client.describe_instances,
        Filters=[{'Name': 'private-ip-address', 'Values': [ip]}],
        cache_duration_secs=STATIC_INFO_CACHE_TIMEOUT)
    result = json.loads(result)
    return result['Reservations'][0]['Instances'][0]


def get_instance_groups(cluster_id, role=None):
    emr_client = connect_emr(role=role)
    result = run_func(emr_client.list_instance_groups, ClusterId=cluster_id,
        cache_duration_secs=QUERY_CACHE_TIMEOUT)
    result = json.loads(result)
    result_map = {}
    for group in result['InstanceGroups']:
        group_type = group['InstanceGroupType']
        if group_type not in result_map:
            result_map[group_type] = []
        group['id'] = group['Id']
        group['type'] = group_type
        result_map[group_type].append(group)

    return result_map


def get_instance_groups_tasknodes(cluster_id, role=None):
    return get_instance_groups(cluster_id, role=role)[INSTANCE_GROUP_TYPE_TASK]


def get_instance_groups_ids(cluster_id, group_type, role=None):
    groups = get_instance_groups(cluster_id, role=role)
    return groups[group_type]


def get_instance_group_type(cluster_id, group_id, role=None):
    return get_instance_group_details(cluster_id, group_id, role=role)['type']


def get_instance_group_details(cluster_id, group_id, role=None):
    groups = get_instance_groups(cluster_id, role=role)
    for key, arr in groups.iteritems():
        for val in arr:
            if val['id'] == group_id:
                return val
    return None


def get_instance_group_for_node(cluster_id, node_host, role=None):
    nodes = get_cluster_nodes(cluster_id, role=role)
    for node in nodes:
        if node['host'] == node_host or node['ip'] == node_host:
            return node['gid']
    return None


def get_cluster_nodes(cluster_id, role=None):
    emr_client = connect_emr(role=role)
    result = run_func(emr_client.list_instances, ClusterId=cluster_id,
        InstanceStates=['AWAITING_FULFILLMENT', 'PROVISIONING', 'BOOTSTRAPPING', 'RUNNING'],
        cache_duration_secs=QUERY_CACHE_TIMEOUT)
    result = json.loads(result)
    result = result['Instances']

    # read domain name config
    custom_dn = config.get_value(constants.KEY_CUSTOM_DOMAIN_NAME, section=SECTION_EMR, resource=cluster_id)

    i = 0
    while i < len(result):
        inst = result[i]
        if inst['Status']['State'] == INSTANCE_STATE_TERMINATED:
            del result[i]
            i -= 1
        else:
            inst['cid'] = inst['Id'] if 'Id' in inst else 'n/a'
            inst['iid'] = inst['Ec2InstanceId'] if 'Ec2InstanceId' in inst else 'n/a'
            inst['gid'] = inst['InstanceGroupId'] if 'InstanceGroupId' in inst else 'n/a'
            inst['ip'] = inst['PrivateIpAddress'] if 'PrivateIpAddress' in inst else 'n/a'
            inst['host'] = inst['PrivateDnsName'] if 'PrivateDnsName' in inst else 'n/a'
            if custom_dn:
                inst['host'] = ip_to_hostname(hostname_to_ip(inst['host']), custom_dn)
            inst['type'] = get_instance_group_type(cluster_id, inst['InstanceGroupId'], role=role)
            inst['state'] = inst['Status']['State']
            inst['market'] = get_instance_group_details(cluster_id, inst['InstanceGroupId'], role=role)['Market']
        i += 1
    return result


def get_all_task_nodes(cluster_id, cluster_ip, role=None):
    all_nodes = get_cluster_nodes(cluster_id, role=role)
    task_nodes = [n for n in all_nodes if n['type'] == INSTANCE_GROUP_TYPE_TASK]
    return task_nodes


def terminate_task_node(instance_group_id, instance_id, role=None):
    # terminate instance
    emr_client = connect_emr(role=role)
    LOG.info('Terminate instance %s of instance group %s' % (instance_id, instance_group_id))
    result = emr_client.modify_instance_groups(InstanceGroups=[
        {'InstanceGroupId': instance_group_id, 'EC2InstanceIdsToTerminate': [instance_id]}
    ])
    return result


def spawn_task_node(instance_group_id, current_size, additional_nodes=1, role=None):
    # start new instance
    emr_client = connect_emr(role=role)
    new_size = current_size + additional_nodes
    LOG.info('Increase instances of instance group %s from %s to %s' %
        (instance_group_id, current_size, new_size))
    result = emr_client.modify_instance_groups(InstanceGroups=[
        {'InstanceGroupId': instance_group_id, 'InstanceCount': new_size}
    ])
    return result


def is_presto_cluster(cluster):
    return cluster.type == 'Presto'


def terminate_inactive_nodes(cluster, cluster_state, role=None):
    if not is_presto_cluster(cluster):
        return
    nodes = cluster_state['nodes']
    for key, node in nodes.iteritems():
        if (node['state'] == INSTANCE_STATE_RUNNING and node['presto_state'] not in
                [PRESTO_STATE_SHUTTING_DOWN, PRESTO_STATE_ACTIVE]):
            try:
                cmd = "cat /etc/presto/conf/config.properties | grep http-server.threads"
                out = run_ssh(cmd, cluster.ip, user='hadoop',
                    via_hosts=[node['host']], cache_duration_secs=QUERY_CACHE_TIMEOUT)
                if INVALID_CONFIG_VALUE in out:
                    LOG.info("Terminating instance of idle node %s in instance group %s" %
                        (node['iid'], node['gid']))
                    terminate_task_node(instance_group_id=node['gid'], instance_id=node['iid'], role=role)
            except Exception, e:
                LOG.info("Unable to read Presto config from node %s: %s" % (node, e))


def get_presto_node_state(cluster_ip, node_ip):
    cmd = ('curl -s --connect-timeout %s --max-time %s http://%s:8889/v1/info/state' %
        (CURL_CONNECT_TIMEOUT, CURL_CONNECT_TIMEOUT, node_ip))
    out = run_ssh(cmd, cluster_ip, user='hadoop', cache_duration_secs=QUERY_CACHE_TIMEOUT)
    out = remove_lines_from_string(out, r'.*Permanently added.*')
    out = re.sub(r'\s*"(.+)"\s*', r'\1', out)
    return out


def set_presto_node_state(cluster_ip, node_ip, state):
    cmd = ("sudo sed -i 's/http-server.threads.max=.*/http-server.threads.max=%s/g' " +
        "/etc/presto/conf/config.properties") % INVALID_CONFIG_VALUE
    if not is_ip_address(cluster_ip):
        cluster_ip = hostname_to_ip(cluster_ip)
    out = run_ssh(cmd, cluster_ip, user='hadoop', via_hosts=[node_ip], cache_duration_secs=QUERY_CACHE_TIMEOUT)

    cmd = ("curl -s --connect-timeout %s -X PUT -H 'Content-Type:application/json' " +
        "-d '\\\"%s\\\"' http://%s:8889/v1/info/state") % (CURL_CONNECT_TIMEOUT, state, node_ip)
    LOG.info(cmd)
    out = run_ssh(cmd, cluster_ip, user='hadoop', cache_duration_secs=QUERY_CACHE_TIMEOUT)
    out = re.sub(r'\s*"(.+)"\s*', r'\1', out)
    return out
