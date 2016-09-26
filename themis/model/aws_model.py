import json
import decimal
from datetime import datetime


class JsonObject(object):

    def to_json(self, indent=None):
        return json.dumps(self,
            default=lambda o: ((float(o) if o % 1 > 0 else int(o))
                if isinstance(o, decimal.Decimal) else str(o)
                if isinstance(o, datetime) else
                (o.__dict__)),
            sort_keys=True, indent=indent)

    def apply_json(self, j):
        if isinstance(j, str):
            j = JsonObject.parse_json(j)
        self.__dict__.update(j)

    def to_dict(self):
        return JsonObject.parse_json(self.to_json())

    @classmethod
    def parse_json(cls, s):
        return json.loads(s)

    @classmethod
    def from_json(cls, j):
        j = JsonObject.as_dict(j)
        result = cls()
        result.apply_json(j)
        return result

    @classmethod
    def from_dict(cls, j):
        return cls.from_json(j)

    @classmethod
    def from_json_list(cls, l):
        return [cls.from_json(j) for j in l]

    @classmethod
    def as_dict(cls, obj):
        if isinstance(obj, dict):
            return obj
        return obj.to_dict()

    def __str__(self):
        return self.to_json()

    def __repr__(self):
        return self.__str__()


class AwsObject(JsonObject):
    def __init__(self, id):
        self.id = id


class Monitorable(AwsObject):
    def __init__(self, id):
        super(Monitorable, self).__init__(id)

    def fetch_data(self, params=None):
        raise Exception('Not implemented')


class Scalable(AwsObject):
    def __init__(self, id):
        super(Monitorable, self).__init__(id)

    def needs_scaling(self, params=None):
        raise Exception('Not implemented')

    def perform_scaling(self, params=None):
        raise Exception('Not implemented')
