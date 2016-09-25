import os
import re
import json
import time
import threading
import traceback
import themis
from themis import config
from themis.constants import *
from themis.util import common, aws_common, aws_pricing
from themis.model.emr_model import *
from themis.scaling import emr_scaling
from themis.monitoring import resources

# logger
LOG = common.get_logger(__name__)


def loop():
    while True:
        LOG.info("Running next loop iteration")
        try:
            resource_list = resources.get_resources()

            for resource in resource_list:
                resource.fetch_data()
                scaling_required = resource.needs_scaling()
                if scaling_required:
                    resource.perform_scaling(scaling_required)

        except Exception, e:
            LOG.warning("Exception in main loop: %s" % (traceback.format_exc(e)))
        time.sleep(int(config.get_value(KEY_LOOP_INTERVAL_SECS)))
