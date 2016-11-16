import re
from themis import config
from themis.config import *
from themis.util import aws_common
from themis.util.common import *
from themis.model.aws_model import *
from themis.model.emr_model import *
from themis.model.kinesis_model import *
import themis.model.resources_model
import themis.monitoring.kinesis_monitoring
import themis.monitoring.emr_monitoring


def update_config(old_config, new_config, section, resource=None):
    if section != SECTION_GLOBAL:
        return
    old_value = old_config.roles_to_assume
    new_value = new_config.roles_to_assume
    if new_value != old_value:
        get_resources(reload=True)


config.CONFIG_LISTENERS.add(update_config)


def update_resources(section=None):
    cfg = load_resources_config()
    if not section or section == SECTION_KINESIS:
        cfg.kinesis = themis.monitoring.kinesis_monitoring.update_resources(cfg.kinesis)
    if not section or section == SECTION_EMR:
        cfg.emr = themis.monitoring.emr_monitoring.update_resources(cfg.emr)
    save_resources_file(cfg)
    return cfg


def get_resources(section=None, reload=False):
    if reload and os.path.isfile(RESOURCES_FILE_LOCATION):
        os.remove(RESOURCES_FILE_LOCATION)
    reloaded = False
    if not os.path.isfile(RESOURCES_FILE_LOCATION):
        init_resources_file()
        reloaded = True
    config = load_resources_config()
    if reloaded:
        config = update_resources(section)
    if not section:
        return config.get_all()
    return config.get(section)


def get_resource(section, resource_id, reload=False):
    if reload:
        if section == SECTION_KINESIS:
            themis.monitoring.kinesis_monitoring.reload_resource(resource_id)
        if section == SECTION_EMR:
            themis.monitoring.emr_monitoring.reload_resource(resource_id)
    section_resources = get_resources(section)
    for resource in section_resources:
        if resource.id == resource_id:
            return resource
    return None


def load_resources_config():
    content = load_json_file(RESOURCES_FILE_LOCATION)
    cfg = themis.model.resources_model.ResourcesConfiguration.from_dict(content)
    return cfg


def save_resources_file(config):
    common.save_file(RESOURCES_FILE_LOCATION, config.to_json())


def save_resource(section, resource):
    config = load_resources_config()
    resources = config.get(section)
    for i in range(0, len(resources)):
        if resources[i].id == resource.id:
            resources[i] = resource
    save_resources_file(config)


def init_resources_file(run_parallel=False):
    if os.path.isfile(RESOURCES_FILE_LOCATION):
        return

    sys_config = get_config()
    roles = re.split(r'\s*,\s*', sys_config.general.roles_to_assume)

    cfg = themis.model.resources_model.ResourcesConfiguration()
    LOG.info("Initializing config file with list of resources from AWS: %s" % RESOURCES_FILE_LOCATION)

    for role in roles:
        # load resources
        kinesis_streams = themis.monitoring.kinesis_monitoring.init_kinesis_config(
            run_parallel=run_parallel, role=role).kinesis
        emr_clusters = themis.monitoring.emr_monitoring.init_emr_config(
            run_parallel=run_parallel, role=role).emr
        for stream in kinesis_streams:
            cfg.kinesis.append(stream)
            config.set_value('role_to_assume', role, section=SECTION_KINESIS, resource=stream.id)
        for cluster in emr_clusters:
            cfg.emr.append(cluster)
            config.set_value('role_to_assume', role, section=SECTION_EMR, resource=cluster.id)

    # save config file
    save_resources_file(cfg)
    LOG.info('Done initializing.')
