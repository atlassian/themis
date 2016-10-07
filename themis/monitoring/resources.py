from themis.config import *
from themis.util.common import *
from themis.model.aws_model import *
from themis.model.emr_model import *
from themis.model.kinesis_model import *
from themis.model.resources_model import *
from themis.monitoring import kinesis_monitoring, emr_monitoring

# global pointer for list of resources
RESOURCES_CONFIG = None


def get_resources(section=None):
    global RESOURCES_CONFIG
    if not os.path.isfile(RESOURCES_FILE_LOCATION):
        init_resources_file()
        RESOURCES_CONFIG = None
    if RESOURCES_CONFIG is None:
        content = load_json_file(RESOURCES_FILE_LOCATION)
        RESOURCES_CONFIG = ResourcesConfiguration.from_dict(content)
    if not section:
        return RESOURCES_CONFIG.get_all()
    return RESOURCES_CONFIG.get(section)


def get_resource(section, resource_id):
    section_resources = get_resources(section)
    for resource in section_resources:
        if resource.id == resource_id:
            return resource
    return None


def init_resources_file(run_parallel=False):
    if os.path.isfile(RESOURCES_FILE_LOCATION):
        return

    cfg = ResourcesConfiguration()
    LOG.info("Initializing config file with list of resources from AWS: %s" % RESOURCES_FILE_LOCATION)
    # load resources
    cfg.kinesis = kinesis_monitoring.init_kinesis_config(run_parallel=run_parallel).kinesis
    cfg.emr = emr_monitoring.init_emr_config(run_parallel=run_parallel).emr
    # save config file
    common.save_file(RESOURCES_FILE_LOCATION, cfg.to_json())
    LOG.info('Done initializing.')
