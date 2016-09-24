from themis.model.aws_model import *


class EmrCluster(AwsObject):
    def __init__(self, id):
        super(EmrCluster, self).__init__(id)
