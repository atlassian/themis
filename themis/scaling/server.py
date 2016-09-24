import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config
from themis.constants import *
from themis.util import common, monitoring, aws_common, aws_pricing
from themis.util.aws_common import INSTANCE_GROUP_TYPE_TASK
from themis.scaling import emr_scaling

# logger
LOG = common.get_logger(__name__)


def loop():
    while True:
        try:
            emr_scaling.tick()
        except Exception, e:
            LOG.warning("Exception in main loop: %s" % (traceback.format_exc(e)))
        time.sleep(int(config.get_value(KEY_LOOP_INTERVAL_SECS)))
