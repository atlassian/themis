from themis.model.aws_model import *
import themis.monitoring.kinesis_monitoring
import themis.scaling.kinesis_scaling
from themis import config


class KinesisStream(Scalable, Monitorable):
    def __init__(self, id=None):
        super(KinesisStream, self).__init__(id)
        self.monitoring_data = {}
        self.shards = []
        self.enhanced_monitoring = []

    def fetch_data(self):
        if self.needs_scaling():
            self.monitoring_data = themis.monitoring.kinesis_monitoring.collect_info(self)
        return self.monitoring_data

    def needs_scaling(self, params=None):
        app_config = config.get_config()
        stream_ids = app_config.general.get_autoscaling_kinesis_streams()
        return self.id in stream_ids

    def perform_scaling(self, params=None):
        themis.scaling.kinesis_scaling.perform_scaling(self)

    @classmethod
    def from_json(cls, j):
        result = KinesisStream(j.get('id'))
        result.monitoring_data = j.get('monitoring_data') or {}
        result.shards = KinesisShard.from_json_list(j.get('shards'))
        return result


class KinesisShard(Monitorable):
    MAX_KEY = "340282366920938463463374607431768211455"

    def __init__(self, id=None):
        super(KinesisShard, self).__init__(id)
        self.stream = None
        self.start_key = "0"
        self.end_key = KinesisShard.MAX_KEY  # 128 times '1' binary as decimal
        self.child_shards = []

    def print_tree(self, indent=''):
        print '%s%s' % (indent, self)
        for c in self.child_shards:
            c.print_tree(indent=indent + '   ')

    def length(self):
        return long(self.end_key) - long(self.start_key)

    def center_key(self):
        length = self.length()
        center = long(self.start_key) + length / 2
        return str(long(center))

    def percent(self):
        return 100.0 * self.length() / float(KinesisShard.MAX_KEY)

    def __str__(self):
        return ('Shard(%s, length=%s, percent=%s, start=%s, end=%s)' %
                (self.id, self.length(), self.percent(), self.start_key,
                    self.end_key))

    @staticmethod
    def sort(shards):
        def compare(x, y):
            s1 = long(x.start_key)
            s2 = long(y.start_key)
            if s1 < s2:
                return -1
            elif s1 > s2:
                return 1
            else:
                return 0
        return sorted(shards, cmp=compare)

    @staticmethod
    def max(shards):
        max_shard = None
        max_length = long(0)
        for s in shards:
            if s.length() > max_length:
                max_shard = s
                max_length = s.length()
        return max_shard
