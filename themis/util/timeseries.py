import pandas
import time
from datetime import datetime


class DefaultExtractor(object):
    def get_x(self, value, index=None, values=None):
        return index

    def get_y(self, value, index=None, values=None):
        return value


class CloudwatchExtractor(object):
    def get_x(self, value, index=None, values=None):
        return value['Timestamp']

    def get_y(self, value, index=None, values=None):
        for k, v in value.iteritems():
            if k not in ['Timestamp', 'Unit']:
                return v
        return None


class SpotPriceHistoryExtractor(object):
    def get_x(self, value, index=None, values=None):
        prev_t = SpotPriceHistoryExtractor.get_time(values, index - 1)
        t = SpotPriceHistoryExtractor.get_time(values, index)
        delta = abs(t - prev_t)
        if delta > 0:
            return t
        return None

    def get_y(self, value, index=None, values=None):
        return float(value['SpotPrice'])

    @staticmethod
    def get_time(values, index):
        if index < 0:
            return 0
        format = "%Y-%m-%dT%H:%M:%S.%fZ"
        value = values[index]
        return time.mktime(datetime.strptime(value['Timestamp'], format).timetuple())


# TODO use this method in aws_pricing.py
def get_spot_history_curve(spot_history):
    extractor = SpotPriceHistoryExtractor()
    result = get_timeseries(spot_history, extractor)
    # print(result)
    return result


def get_timeseries(values, extractor):
    x_arr = []
    y_arr = []
    i = 0
    for value in values:
        x = extractor.get_x(value, i)
        y = extractor.get_y(value, i)
        i += 1
        x_arr.append(x)
        y_arr.append(y)
    return pandas.Series(y_arr, index=x_arr)


def get_cloudwatch_timeseries(datapoints):
    if 'Datapoints' in datapoints:
        datapoints = datapoints['Datapoints']
    extractor = CloudwatchExtractor()
    return get_timeseries(datapoints, extractor)
