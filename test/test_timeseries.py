import os
import json
import datetime
from themis.util import timeseries, aws_common
from themis.util.common import *

THIS_FOLDER = os.path.realpath(os.path.dirname(__file__))


def test_cloudwatch_timeseries():
    cw = load_json_file(os.path.join(THIS_FOLDER, 'data', 'cloudwatch_kinesis_response.json'))
    series = timeseries.get_cloudwatch_timeseries(cw)
    # TODO add assertions
    # assert False


def test_fillup_with_zeros():
    datapoints = []
    times = ['04:32:00Z', '04:15:00Z', '04:33:00Z', '04:13:00Z', '04:47:00Z', '04:37:00Z', '04:45:00Z']
    for t in times:
        datapoints.append({
            'Timestamp': '2016-01-01T%s' % t,
            'Sum': 100,
            'Unit': 'Bytes'
        })
    start_time = aws_common.parse_cloudwatch_timestamp('2016-01-01T04:00:00Z')
    time_window = 60 * 60
    period = 60
    timeseries.fillup_with_zeros(datapoints, start_time, time_window, period)
    assert len(datapoints) == 60
    timestamps = [i['Timestamp'] for i in datapoints]
    for i in range(0, 60):
        assert ('2016-01-01T04:%s:00Z' % (('0' if i < 10 else '') + str(i))) in timestamps
