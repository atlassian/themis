from themis.config import *
from themis.util.common import *
from themis.model.aws_model import *
from themis.model.emr_model import *
from themis.model.kinesis_model import *

# global pointer for list of resources
RESOURCES_CONFIG = None


class ResourcesConfiguration(ConfigObject):
    """Main configuration class representing the content of file themis.resources.json"""

    def __init__(self):
        self.emr = []
        self.kinesis = []

    @classmethod
    def from_json(cls, j):
        result = ResourcesConfiguration()
        result.emr = EmrCluster.from_json_list(j.get('emr'))
        result.kinesis = KinesisStream.from_json_list(j.get('kinesis'))
        return result

    def get_all(self):
        result = []
        result.extend(self.emr)
        result.extend(self.kinesis)
        return result


def get_resources(section=None):
    global RESOURCES_CONFIG
    if not os.path.isfile(RESOURCES_FILE_LOCATION):
        init_resources_file()
        RESOURCES_CONFIG = None
    if RESOURCES_CONFIG is None:
        content = load_json_file(RESOURCES_FILE_LOCATION)
        RESOURCES_CONFIG = ResourcesConfiguration.from_dict(content)
    if not section:
        return RESOURCES_CONFIG.get_all()
    return RESOURCES_CONFIG.get(section)


def get_resource(section, resource_id):
    section_resources = get_resources(section)
    for resource in section_resources:
        if resource.id == resource_id:
            return resource
    return None


def init_resources_file():
    cfg = ResourcesConfiguration()
    # Don't run this in parallel for now. There seems to be an issue with
    # the AWS CLI or API if we run multiple "aws ..." commands in parallel
    # (possible rate limiting)
    run_parallel = False

    def init_emr_cluster_config(c):
        if c['Status']['State'][0:10] != 'TERMINATED':
            out1 = run('aws emr describe-cluster --cluster-id=%s' % c['Id'], retries=1)
            out1 = json.loads(out1)
            cluster_details = out1['Cluster']
            cluster = EmrCluster()
            cluster.id = c['Id']
            cluster.name = c['Name']
            cluster.ip = 'N/A'
            cluster.ip_public = cluster_details['MasterPublicDnsName']
            has_ganglia = False
            for app in out1['Cluster']['Applications']:
                if app['Name'] == 'Hive' and not cluster.type:
                    cluster.type = 'Hive'
                if app['Name'][0:6] == 'Presto':
                    cluster.type = 'Presto'
                if app['Name'] == 'Ganglia':
                    has_ganglia = True
            if has_ganglia:
                LOG.info('Getting details for cluster %s' % cluster.id)
                # get private IP address of cluster
                for g in cluster_details['InstanceGroups']:
                    if g['InstanceGroupType'] == 'MASTER':
                        cmd = ('aws emr list-instances --cluster-id=%s --instance-states ' +
                            'AWAITING_FULFILLMENT PROVISIONING BOOTSTRAPPING RUNNING') % c['Id']
                        out2 = run(cmd, retries=6)
                        if not out2:
                            LOG.warning("No output for command '%s'" % cmd)
                        out2 = json.loads(out2)
                        for inst in out2['Instances']:
                            if inst['InstanceGroupId'] == g['Id']:
                                cluster.ip = inst['PrivateDnsName']
                cfg.emr.append(cluster)
            else:
                LOG.info('Ignoring cluster %s (Ganglia not installed)' % cluster.id)

    def init_kinesis_stream_config(c):
        pass
        # TODO

    if not os.path.isfile(RESOURCES_FILE_LOCATION):
        LOG.info("Initializing config file with list of resources from AWS: %s" % RESOURCES_FILE_LOCATION)

        # load EMR resources
        out = run('aws emr list-clusters')
        out = json.loads(out)
        if run_parallel:
            common.parallelize(out['Clusters'], init_emr_cluster_config)
        else:
            for c in out['Clusters']:
                init_emr_cluster_config(c)

        # load Kinesis resources
        # TODO

        common.save_file(RESOURCES_FILE_LOCATION, cfg.to_json())
        LOG.info('Done initializing.')
