import os
import pwd
import subprocess
from traitlets import Bool, Unicode, List, Dict
import asyncio

from socket import gethostbyname
from hashlib import md5
from csystemdspawner import systemd

from jupyterhub.spawner import Spawner
from jupyterhub.utils import random_port


class CSystemdSpawner(Spawner):
    controller = Unicode(
        None,
        all_none=True,
        help="""
        string identifying the jupyterhub controller which 
        initialed the spawn and can control the unit."""
    ).tag(config=True)

    host = Unicode(
        None,
        allow_none=True,
        help="""
        Hostname or ip address of machine tasked with launching the 
        guest notebook server unit; 
           NOTE: if the value is not None, then requires that ssh and
        preconfigured authorized_keys are in place on the target machine.
        """
    ).tag(config=True)
    
    user_workingdir = Unicode(
        None,
        allow_none=True,
        help="""
        Path to start each notebook user on.

        {USERNAME}, {USERID}, and ... are expanded.

        Defaults to the home directory of the user.

        Not respected if dynamic_users is set to True.
        """
    ).tag(config=True)

    username_template = Unicode(
        '{USERNAME}',
        help="""
        Template for unix username each user should be spawned as.

        {USERNAME}, {USERID}, {HUB} and {*_HASH} are expanded.

        This user should already exist in the system.

        Not respected if dynamic_users is set to True
        """
    ).tag(config=True)

    default_shell = Unicode(
        os.environ.get('SHELL', '/bin/bash'),
        help='Default shell for users on the notebook terminal'
    ).tag(config=True)

    extra_paths = List(
        [],
        help="""
        Extra paths to prepend to the $PATH environment variable.

        {USERNAME}, {USERID}, and {NAME_HASH} are expanded
        """,
    ).tag(config=True)

    unit_name_template = Unicode(
        'notebook-{USERID}-{NAME_HASH}',
        help="""
        Template to use to make the systemd service names.

        {USERNAME}, {USERID} and {NAME_HASH} are expanded}
        """
    ).tag(config=True)

    # FIXME: Do not allow enabling this for systemd versions < 227,
    # since that is when it was introduced.
    isolate_tmp = Bool(
        False,
        help="""
        Give each notebook user their own /tmp, isolated from the system & each other
        """
    ).tag(config=True)

    isolate_devices = Bool(
        False,
        help="""
        Give each notebook user their own /dev, with a very limited set of devices mounted
        """
    ).tag(config=True)

    disable_user_sudo = Bool(
        False,
        help="""
        Set to true to disallow becoming root (or any other user) via sudo or other means from inside the notebook
        """,
    ).tag(config=True)

    readonly_paths = List(
        None,
        allow_none=True,
        help="""
        List of paths that should be marked readonly from the user notebook.

        Subpaths maybe be made writeable by setting readwrite_paths
        """,
    ).tag(config=True)

    readwrite_paths = List(
        None,
        allow_none=True,
        help="""
        List of paths that should be marked read-write from the user notebook.

        Used to make a subpath of a readonly path writeable
        """,
    ).tag(config=True)

    unit_extra_properties = Dict(
        {},
        help="""
        Dict of extra properties for systemd-run --property=[...].

        Keys are property names, and values are either strings or
        list of strings (for multiple entries). When values are
        lists, ordering is guaranteed. Ordering across keys of the
        dictionary are *not* guaranteed.

        Used to add arbitrary properties for spawned Jupyter units.
        Read `man systemd-run` for details on per-unit properties
        available in transient units.
        """
    ).tag(config=True)

    dynamic_users = Bool(
        False,
        help="""
        Allocate system users dynamically for each user.

        Uses the DynamicUser= feature of Systemd to make a new system user
        for each hub user dynamically. Their home directories are set up
        under /var/lib/{USERNAME}, and persist over time. The system user
        is deallocated whenever the user's server is not running.

        See http://0pointer.net/blog/dynamic-users-with-systemd.html for more
        information.

        Requires systemd 235.
        """
    ).tag(config=True)

    slice = Unicode(
        None,
        allow_none=True,
        help="""
        Ensure that all users that are created are run within a given slice.
        This allow global configuration of the maximum resources that all users
        collectively can use by creating a a slice beforehand.
        """
    ).tag(config=True)

    # ##########################################################################
    
    def _expand_user_vars(self, obj):
        """
        Expand user related variables in a given string

        Currently expands:
          {NAME}          -> server name (when present)
          {NAME_HASH}     -> hash of server name (when present)
          {USERNAME}      -> name of user
          {USERNAME_HASH} -> hashed name of user

          {HUB}           -> string identifiying the hub controller  
                               which initiated the spawn & controls the unit
          {HUB_HASH}      -> hash of ...

          {USERID}        -> UserID

        """
        fmtenv = dict(
            USERNAME=self.user.name,
            USERID=self.user.id,
            HUB=self.controller
        )
        
        if self.name:
            fmtenv['NAME'] = self.name
            if not hasattr(self, 'name_hash'):
                self.name_hash = md5(
                    self.name.encode('utf-8')
                ).hexdigest()
            fmtenv['NAME_HASH'] = self.name_hash

        if self.controller:
            fmtenv['HUB'] = self.controller
            if not hasattr(self, 'controller_hash'):
                self.controller_hash = md5(
                    self.controller.encode('utf-8')
                ).hexdigest()
            fmtenv['HUB_HASH']=self.controller_hash
            
        if type(obj) is str:
            return obj.format(**fmtenv)
        elif type(obj) is list:
            return [self._expand_user_vars(v) for v in obj]
        else:
            raise Exception('something is misconfigured')
        
    # ##########################################################################
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # All traitlets configurables are configured by now
        self.unit_name = self._expand_user_vars(self.unit_name_template)
        if self.host:
            self.ip = gethostbyname(self.remote_host)
        self.log.debug('user:%s Initialized spawner with unit %s', self.user.name, self.unit_name)
        self.log.debug('host:%s controller:%s', repr(self.host), repr(self.controller))
        
    def get_state(self):
        """
        Save state required to reconstruct spawner from scratch

        We save the unit name, just in case the unit template was changed
        between a restart. We do not want to lost the previously launched
        events.

        JupyterHub before 0.7 also assumed your notebook was dead if it
        saved no state, so this helps with that too!
        """
        state = super().get_state()

        state['unit_name'] = self.unit_name
        
        if self.host:
            state['host'] = self.host
            state['ip'] = self.ip
            
        if self.controller:
            state['controller'] = self.controller
        
        return state

    def load_state(self, state):
        """
        Load state from storage required to reinstate this user's server

        This runs after __init__, so we can override it with saved unit name
        if needed. This is useful primarily when you change the unit name template
        between restarts.

        JupyterHub before 0.7 also assumed your notebook was dead if it
        saved no state, so this helps with that too!
        """
        if 'unit_name' in state:
            self.unit_name = state['unit_name']

        if 'host' in state:
            self.host = state['host']
            self.ip = state['ip'] # raises an exception if not found;
                                  #   this is intentional        
        if 'controller' in state:
            self.controller = state['controller']
        pass
    
    async def start(self):
        self.port = random_port()
        self.log.debug('user:%s using port %s to start spawning user server', self.user.name, self.port)
        self.log.debug('host:%s controller:%s', repr(self.host), repr(self.controller))
        
        # If there's a unit with this name running already. This means a bug in
        # JupyterHub, a remnant from a previous install or a failed service start
        # from earlier. Regardless, we kill it and start ours in its place.
        # FIXME: Carefully look at this when doing a security sweep.
        if await systemd.service_running(self.unit_name, self.host):
            self.log.info('user:%s Unit %s already exists but not known to JupyterHub. Killing', self.user.name, self.unit_name)
            await systemd.stop_service(self.unit_name, self.host)
            if await systemd.service_running(self.unit_name, self.host):
                self.log.error('user:%s Could not stop already existing unit %s', self.user.name, self.unit_name)
                raise Exception('Could not stop already existing unit {}'.format(self.unit_name))

        # If there's a unit with this name already but sitting in a failed state.
        if await systemd.service_failed(self.unit_name, self.host):
            # then do a reset of the state before trying to start it up again.
            self.log.info('user:%s Unit %s in a failed state. Resetting state.', self.user.name, self.unit_name)
            await systemd.reset_service(self.unit_name, self.host)

        # collect environment for unit
        env = self.get_env()

        # begin translating Spawner interface into unit properties
        properties = {}

        if self.dynamic_users:
            #
            # TODO: Figure out how to combine state with server-name
            #
            properties['DynamicUser'] = 'yes'
            properties['StateDirectory'] = self._expand_user_vars('{USERNAME_HASH}')

            # HOME is not set by default otherwise
            env['HOME'] = self._expand_user_vars('/var/lib/{USERNAME_HASH}')
            # Set working directory to $HOME too
            working_dir = env['HOME']
            
            # Set uid, gid = None so we don't set them
            uid = gid = None
        else:
            try:
                unix_username = self._expand_user_vars(self.username_template)
                pwnam = pwd.getpwnam(unix_username)
            except KeyError:
                self.log.exception('No user named {} found in the system'.format(unix_username))
                raise
            uid = pwnam.pw_uid
            gid = pwnam.pw_gid
            
            if self.user_workingdir is None:
                working_dir = pwnam.pw_dir
            else:
                working_dir = self._expand_user_vars(self.user_workingdir)
            pass
        
        # XXX: having removed the temporary hack from `systemd.py`
        #   this is now needed.
        properties['WorkingDirectory'] = working_dir

        
        if self.isolate_tmp:
            properties['PrivateTmp'] = 'yes'

        if self.isolate_devices:
            properties['PrivateDevices'] = 'yes'

        if self.extra_paths:
            env['PATH'] = '{extrapath}:{curpath}'.format(
                curpath=env['PATH'],
                extrapath=':'.join(
                    [self._expand_user_vars(p) for p in self.extra_paths]
                )
            )

        env['SHELL'] = self.default_shell

        if self.mem_limit is not None:
            # FIXME: Detect & use proper properties for v1 vs v2 cgroups
            properties['MemoryAccounting'] = 'yes'
            properties['MemoryLimit'] = self.mem_limit

        if self.cpu_limit is not None:
            # FIXME: Detect & use proper properties for v1 vs v2 cgroups
            # FIXME: Make sure that the kernel supports CONFIG_CFS_BANDWIDTH
            #        otherwise this doesn't have any effect.
            properties['CPUAccounting'] = 'yes'
            properties['CPUQuota'] = '{}%'.format(int(self.cpu_limit * 100))

        if self.disable_user_sudo:
            properties['NoNewPrivileges'] = 'yes'

        if self.readonly_paths is not None:
            properties['ReadOnlyDirectories'] = [
                self._expand_user_vars(path)
                for path in self.readonly_paths
            ]

        if self.readwrite_paths is not None:
            properties['ReadWriteDirectories'] = [
                self._expand_user_vars(path)
                for path in self.readwrite_paths
            ]

        # XXX: added variable expansion to values associated with
        #  the `unit_extra_properties` parameter
        properties.update({ prop:  self._expand_user_vars(val) \
                            for prop, val in self.unit_extra_properties })


        # assemble and record the paramters passed to systemd 
        unit_spec=dict(
            name=self.unit_name,
            cmd=[self._expand_user_vars(c) for c in self.cmd],
            args=[self._expand_user_vars(a) for a in self.get_args()],
            environment_variables=env,
            properties=properties,
            uid=uid,
            gid=gid,
            host=self.host,
            slice=self.slice)

        await systemd.start_transient_service(unit_spec.pop('name'), **unit_spec)

        for i in range(self.start_timeout):
            is_up = await self.poll()
            if is_up is None:
                return (self.ip or '127.0.0.1', self.port)
            await asyncio.sleep(1)

        return None

    async def stop(self, now=False):
        await systemd.stop_service(self.unit_name, self.host)

    async def poll(self):
        if await systemd.service_running(self.unit_name, self.host):
            return None
        return 1

