from themis.util import common
from themis.util.common import run
from themis import config
from themis.constants import *
import subprocess


def run_ssh(cmd, host, user=None, keys=None, via_hosts=[], cache_duration_secs=0):
    if not keys:
        keys = config.get_value(KEY_SSH_KEYS).split(',')

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
