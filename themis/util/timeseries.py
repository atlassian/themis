import pandas
import time
import pytz
from datetime import datetime, timedelta
from themis.util import aws_common
from themis.util.common import get_logger

# logger
LOG = get_logger(__name__)


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


def fillup_with_zeros(datapoints, start_time, time_window, period, statistic='Sum'):
    # first, make sure datapoints are sorted
    datapoints.sort(key=lambda item: item['Timestamp'])

    dates_as_string = False
    if len(datapoints) > 0:
        dates_as_string = isinstance(datapoints[0]['Timestamp'], basestring)

    expected_length = int(time_window / period)
    for i in range(0, expected_length):
        unit = 'n/a'
        time = start_time + timedelta(seconds=i * period)

        add_zero = False
        if len(datapoints) <= i:
            add_zero = True
        else:
            unit = datapoints[i]['Unit']
            next_time = datapoints[i]['Timestamp']
            if dates_as_string:
                next_time = aws_common.parse_cloudwatch_timestamp(datapoints[i]['Timestamp'])
            # make sure all timestamps are in UTC timezone, to avoid uncomparable datetimes
            next_time = next_time.replace(tzinfo=pytz.UTC)
            time = time.replace(tzinfo=pytz.UTC)
            if (time + timedelta(seconds=period)) <= next_time:
                add_zero = True

        if add_zero:
            if dates_as_string:
                time = aws_common.format_cloudwatch_timestamp(time)
            datapoints.insert(i, {
                'Timestamp': time,
                statistic: 0,
                'Unit': unit
            })
