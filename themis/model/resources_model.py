from themis.config import *
import themis.model.emr_model
import themis.model.kinesis_model


class ResourcesConfiguration(ConfigObject):
    """Main configuration class representing the content of file themis.resources.json"""

    def __init__(self):
        self.emr = []
        self.kinesis = []

    @classmethod
    def from_json(cls, j):
        result = ResourcesConfiguration()
        result.emr = themis.model.emr_model.EmrCluster.from_json_list(j.get('emr'))
        result.kinesis = themis.model.kinesis_model.KinesisStream.from_json_list(j.get('kinesis'))
        return result

    def get_all(self):
        result = []
        result.extend(self.emr)
        result.extend(self.kinesis)
        return result
