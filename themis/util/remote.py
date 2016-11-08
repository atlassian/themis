import subprocess
import re
import os
from themis.util import common
from themis.util.common import run, save_file, get_logger
from themis import config
from themis.constants import *

KEY_FILE_NAME_PATTERN = '/tmp/ssh.key.%s.pem'

# logger
LOG = get_logger(__name__)


def get_ssh_keys():
    keys = re.split(r'\s*,\s*', config.get_value(KEY_SSH_KEYS))
    for i in range(0, len(keys)):
        key = keys[i]
        if key[0] == '$':
            var_name = key[1:]
            key_file = KEY_FILE_NAME_PATTERN % var_name
            if not os.path.isfile(key_file):
                key_value = os.environ.get(var_name)
                if key_value:
                    marker_begin = '-----BEGIN RSA PRIVATE KEY-----'
                    marker_end = '-----END RSA PRIVATE KEY-----'
                    key_value = key_value.replace(marker_begin, '')
                    key_value = key_value.replace(marker_end, '')
                    key_value = key_value.replace(' ', '\n')
                    if marker_begin not in key_value:
                        key_value = ('%s\n' % marker_begin) + key_value
                    if marker_end not in key_value:
                        key_value += ('\n%s' % marker_end)
                    key_value = key_value.replace('\n\n', '\n')
                    save_file(key_file, key_value)
                    run('chmod 600 %s' % key_file)
                else:
                    LOG.warning('Unable to read SSH key from environment variable: %s' % var_name)
            keys[i] = key_file
    return keys


def run_ssh(cmd, host, user=None, keys=None, via_hosts=[], cache_duration_secs=0):
    if not keys:
        keys = get_ssh_keys()

    user = '%s@' % user if user else ''

    agent_forward = ''
    forward_addendum = ''
    ssh_configs = ('-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ' +
        '-o PasswordAuthentication=no -o BatchMode=yes -o ConnectTimeout=3')

    if len(via_hosts) > 0:
        agent_forward = '-o ForwardAgent=yes'
        for via_host in list(reversed(via_hosts)):
            forward_addendum = ('ssh %s %s%s ' % (ssh_configs, user, via_host)) + forward_addendum

    ssh_cmd_tmpl = 'ssh ' + ssh_configs + ' ' + agent_forward + ' -i %s %s%s "' + forward_addendum + '%s"'

    for key in keys:
        key = key.strip()
        ssh_cmd = ssh_cmd_tmpl % (key, user, host, cmd)

        if len(via_hosts) > 0:
            run('ssh-add %s 2>&1 > /dev/null' % key)

        try:
            out = run(ssh_cmd, cache_duration_secs)
            return out
        except subprocess.CalledProcessError, e:
            # TODO find a more elegant solution for this.
            if 'Permission denied (publickey)' not in e.output:
                raise e

    raise Exception('Cannot run SSH command with any of the provided ssh keys: %s%s %s %s' % (user, host, cmd, keys))
