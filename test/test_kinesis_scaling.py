import time
from datetime import datetime
import themis.config
from themis import config
from themis.util import common, aws_common
from themis.config import *
from themis.model.kinesis_model import *
from themis.scaling import kinesis_scaling
from themis.monitoring import kinesis_monitoring
from constants import *
import mock.aws_api

server = None

TEST_STREAM_ID = 'testStream'


def setup():
    mock.aws_api.init_mocks()


def mock_stream_state(config=None):
    task_nodes = []
    stream = kinesis_monitoring.retrieve_stream_details(TEST_STREAM_ID)
    stream.monitoring_data = kinesis_monitoring.collect_info(stream, config=config)
    return stream


def get_test_stream_config(upscale_expr=None, downscale_expr=None):
    config = SystemConfiguration()
    stream_config = KinesisStreamConfiguration()
    # per-cluster configs
    if upscale_expr is not None:
        stream_config.stream_upscale_expr = upscale_expr
    if downscale_expr is not None:
        stream_config.stream_downscale_expr = downscale_expr
    # global configs
    if now is not None:
        config.general.now = now
    config.kinesis.set(TEST_STREAM_ID, stream_config)
    themis.config.TEST_CONFIG = config
    return config


def test_upscale():

    common.QUERY_CACHE_TIMEOUT = 0
    config = get_test_stream_config(
        upscale_expr='1 if (shards.count < 5 and stream.IncomingBytes.average > 100000) else 0')

    # mock cloudwatch metrics
    mock.aws_api.server.config['cloudwatch.IncomingBytes.value'] = 1000

    stream = mock_stream_state(config=config)
    shards = kinesis_scaling.get_upscale_shards(stream, config)
    assert(len(shards) == 0)

    config = get_test_stream_config(
        upscale_expr='1 if (shards.count < 5 and stream.IncomingBytes.average > 100) else 0')

    # mock cloudwatch metrics
    mock.aws_api.server.config['cloudwatch.IncomingBytes.value'] = 1000000

    stream = mock_stream_state(config=config)
    shards = kinesis_scaling.get_upscale_shards(stream, config)
    assert(len(shards) == 1)


def test_perform_scaling():
    common.QUERY_CACHE_TIMEOUT = 0
    config = get_test_stream_config(
        upscale_expr='1 if (shards.count < 5 and stream.IncomingBytes.average > 100000) else 0')

    # mock cloudwatch metrics
    mock.aws_api.server.config['cloudwatch.IncomingBytes.value'] = 1000000
    stream = mock_stream_state(config=config)

    state = kinesis_scaling.perform_scaling(stream)
    assert(state.action == 'UPSCALE(+1)')
    state_obj = json.loads(state.state)
    assert(state_obj['stream']['IncomingBytes']['average'] == 1000000)
