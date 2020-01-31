
# import base spawner & authenticator classes
from csystemdspawner import CSystemdSpawner
from jupyterhub.auth import PAMAuthenticator

import hashlib # for `md5`
import os, sys, pwd

# ##############################################################################
# Jupyterhub Config File

c.JupyterHub.log_level = 10

# base application config
c.JupyterHub.hub_ip  = '192.168.2.6'
c.JupyterHub.hub_port = 9001

c.JupyterHub.cleanup_servers = False
c.JupyterHub.active_server_limit = 70
c.JupyterHub.concurrent_spawn_limit = 100

# named servers
c.JupyterHub.allow_named_servers = True
c.JupyterHub.named_server_limit_per_user = 1
c.JupyterHub.default_server_name = ""

# whether admins can access all notebook servers
c.JupyterHub.admin_access = True

# file locations
c.JupyterHub.cookie_secret_file = '/var/lib/jupyterhub/cookie_secret'
c.JupyterHub.db_url             = 'sqlite:////var/lib/jupyterhub/db.sqlite'
c.JupyterHub.data_files_path    = '/opt/shared/share/jupyterhub'

## XXX: external https now being handled by nginx
#c.JupyterHub.ssl_key = ...
#c.JupyterHub.ssl_cert = ...

# internal ssl
c.JupyterHub.internal_ssl = False
c.JupyterHub.generate_certs = False
c.JupyterHub.internal_certs_location = '/var/lib/jupyterhub/internal-ssl/'


## set spawner & authenticator classes
c.JupyterHub.spawner_class = CSystemdSpawner
c.JupyterHub.authenticator_class = PAMAuthenticator

## services
c.JupyterHub.services = [
    {
        'name': 'cull-idle',
        'admin': True,
        'command': [sys.executable,
                    '/opt/shared/bin/cull_idle_servers.py',
                    '--timeout=5400'],
    }
]

## HTTP Route Proxy ############################################################

# proxy config
#c.ConfigurableHTTPProxy.pid_file = "/var/lib/jupyterhub/jupyterhub-proxy.pid"
#c.ConfigurableHTTPProxy.debug = True

# XXX: routing proxy moved to it's own service 
c.ConfigurableHTTPProxy.should_start = False
c.ConfigurableHTTPProxy.auth_token = "testing" # passed to proxy as CONFIGPROXY_AUTH_TOKEN 
c.ConfigurableHTTPProxy.api_url = 'http://127.0.0.1:9000'

## Authentication ##############################################################

# basic PAM authentication setup
c.PAMAuthenticator.open_sessions = True # (actually log them in, not just auth.)
c.PAMAuthenticator.whitelist = set()
c.PAMAuthenticator.blacklist = {'admin', 'root'}
c.PAMAuthenticator.group_whitelist = {'hub-admin',
                                      'users'}
c.PAMAuthenticator.admin_groups = {'hub-admin'}
c.PAMAuthenticator.service = 'jupyter-hub'

## Server Spawning  ############################################################

c.CSystemdSpawner.controller = 'beta'
c.CSystemdSpawner.host = '192.168.2.7'

c.CSystemdSpawner.unit_name_template = 'notebook-{USERID}-{NAME_HASH}'


c.CSystemdSpawner.cmd = [ # command spawning server
    '/opt/shared/bin/platform-python', '-m', 'jupyterhub.singleuser' ]

# env config
c.CSystemdSpawner.default_shell = '/bin/bash'

c.CSystemdSpawner.environment = { 'PATH': '/opt/shared/bin:/bin:/bin:/usr/bin:/sbin:/usr/sbin',
                                  'PYTHONUNBUFFERED': '1' }

# user-service config
c.CSystemdSpawner.user_workingdir    = '/tmp/{USERNAME}/{NAME}'

# main resource container/slice
c.CSystemdSpawner.slice = 'jupyter'

# (NOTE: using a specific systemd-slice allows us to limit ram+swap usage
#   see github.com/jupyterhub/systemdspawner/issues/15#issuecomment-327947945
#   however, this only works for >= RHEL/Cent 8.0)


c.CSystemdSpawner.mem_limit = '1G'
c.CSystemdSpawner.cpu_limit = 0.5
c.CSystemdSpawner.isolate_devices   = False
c.CSystemdSpawner.isolate_tmp       = True
c.CSystemdSpawner.disable_user_sudo = True
c.CSystemdSpawner.unit_extra_properties = {
    'ExecStartPre'      : 'mkdir -p /tmp/{USERNAME_HASH}/{NAME_HASH}',
    'MemoryAccounting'  : 'true',
    'CPUAccounting'     : 'true',
    'MemoryMax'         : '1G',
    'MemorySwapMax'     : '1G',
    'CPUQuota'          : '50%'
#   'CPUQuotaPeriodSec' : '500'
}
