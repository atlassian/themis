from themis.monitoring import emr_monitoring
from themis.scaling import emr_scaling
from themis.util import aws_common
from themis.model.aws_model import *


class EmrCluster(Scalable, Monitorable):
    def __init__(self, id=None):
        super(EmrCluster, self).__init__(id)
        self.type = None
        self.ip = None
        self.ip_public = None
        self.monitoring_data = {}

    def fetch_data(self):
        self.monitoring_data = emr_monitoring.collect_info(self)
        return self.monitoring_data

    def needs_scaling(self, params=None):
        # TODO make decision here
        return True

    def perform_scaling(self, params=None):
        emr_scaling.perform_scaling(self)


class EmrClusterType(object):
    PRESTO = aws_common.CLUSTER_TYPE_PRESTO
    HIVE = aws_common.CLUSTER_TYPE_HIVE
