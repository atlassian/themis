import os
import json
from themis.util import timeseries
from themis.util.common import *

THIS_FOLDER = os.path.realpath(os.path.dirname(__file__))


def test_cloudwatch_timeseries():
    cw = load_json_file(os.path.join(THIS_FOLDER, 'data', 'cloudwatch_kinesis_response.json'))
    series = timeseries.get_cloudwatch_timeseries(cw)
    print series
    # TODO add assertions
    # assert False
