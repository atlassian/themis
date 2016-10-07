import themis.monitoring.emr_monitoring
import themis.scaling.emr_scaling
from themis.util import aws_common
from themis import config
from themis.model.aws_model import *


class EmrCluster(Scalable, Monitorable):
    def __init__(self, id=None):
        super(EmrCluster, self).__init__(id)
        self.type = None
        self.ip = None
        self.ip_public = None
        self.monitoring_data = {}

    def fetch_data(self):
        if self.needs_scaling():
            self.monitoring_data = themis.monitoring.emr_monitoring.collect_info(self)
        return self.monitoring_data

    def needs_scaling(self, params=None):
        app_config = config.get_config()
        cluster_ids = app_config.general.get_autoscaling_clusters()
        return self.id in cluster_ids

    def perform_scaling(self, params=None):
        themis.scaling.emr_scaling.perform_scaling(self)


class EmrClusterType(object):
    PRESTO = aws_common.CLUSTER_TYPE_PRESTO
    HIVE = aws_common.CLUSTER_TYPE_HIVE
