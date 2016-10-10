import logging
import themis.config
from themis.util import expr
from themis.constants import *
from themis.config import *

LOG = logging.getLogger(__name__)


def get_downscale_shards(stream, config=None):
    if not config:
        config = themis.config.get_config()
    expr = config.get(SECTION_KINESIS, stream.id, KEY_DOWNSCALE_EXPR)
    num_downsize = execute_dsl_string(expr, stream.monitoring_data, config=config)
    LOG.info("Kinesis Stream %s: num_downsize: %s" % (stream.id, num_downsize))
    if not isinstance(num_downsize, int) or num_downsize <= 0:
        return []


def get_upscale_shards(stream, config=None):
    return 'TODO'


def perform_scaling(kinesis_stream):
    downscale = get_downscale_shards(kinesis_stream)
    upscale = get_upscale_shards(kinesis_stream)


def execute_dsl_string(dsl_str, context, config=None):
    return expr.execute_dsl_string(dsl_str, context=context, config=config)
