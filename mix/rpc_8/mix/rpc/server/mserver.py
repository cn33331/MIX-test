from .server import RPCServer
from .dispatcher import Dispatcher
from ..proxy import ProxyFactory
from ..transports import ZMQClientTransport, ZMQServerTransport
from ..transports.pingtransport import ZMQPingServerTransport
from ..transports import RPCTransportTimeout
from ..protocols import JSONRPCProtocol
from ..rpc_error import RPCServiceError
from mix.tools.util.misc import wait_pid

import zmq
import time
import os
from threading import Thread, RLock
import json


class ServerInfo(object):
    __slots__ = ['url', 'pf', 'session_id', 'last_time', 'pid']

    def __init__(self, url, session_id, pf=None, pid=None):
        self.url = url
        self.pf = pf
        self.pid = pid
        self.session_id = session_id
        self.last_time = time.time()

    def __eq__(self, other):
        if not isinstance(other, ServerInfo):
            return False
        if self.url != other.url:
            return False
        if self.session_id != other.session_id:
            return False
        return True

    def __str__(self):
        return f"(url: {self.url}; session_id: {self.session_id}; pid: {self.pid}; last_time: {self.last_time})"

    def __repr__(self):
        return str(self)


class ServerManager(Dispatcher):

    # purge the server if we don't hear from it for 1 hour
    MAX_SERVER_DORMANT_TIME = 3600

    def __init__(self, logger):
        self.transport = ZMQPingServerTransport()
        self.transport.bind()
        self.logger = logger.getChild('SM')
        # we use the server info stored in the management service
        self.man_service = None

    @property
    def listening_socket(self):
        return self.transport.socket

    def dispatch(self):
        try:
            info = self.transport.recv()
            if info:
                self.logger.debug(f'ping server received {info}')
                iden, url, session_id = info
                s_info = ServerInfo(url, session_id)
                with self.man_service.server_lock:
                    server_info = self.man_service.servers.get(iden)
                    if server_info is None:
                        self.logger.debug(f'found new server {iden}:{s_info}')
                        self.man_service.found_new_server(iden, s_info)
                    else:
                        if s_info != server_info:
                            self.logger.debug(f'replacing server {iden}:{s_info}')
                            self.man_service.replace_server(iden, s_info)
                        else:
                            last_time = time.time()
                            self.logger.debug(f'touched server {iden}:{last_time}')
                            self.man_service.touch_server(iden, last_time)
        except RuntimeError as e:
            self.logger.exception(e)

        self.purge()

    def purge(self):
        purge_list = []
        t = time.time()
        with self.man_service.server_lock:
            for iden, info in self.man_service.servers.items():
                if t - info.last_time > self.MAX_SERVER_DORMANT_TIME:
                    self.logger.info(f'server {iden} dormant for too long. Purging...')
                    purge_list.append(iden)
            for iden in purge_list:
                self.man_service.remove_server(iden)

    def shut_down(self):
        self.transport.shut_down()


def connect_to_server(server_url, logger, client_id='temp', time_out=100):
    ctx = zmq.Context().instance()
    ctx.linger = 0
    transport = ZMQClientTransport(server_url, ctx)
    old_timeout = transport.timeout
    transport.timeout = time_out
    protocol = JSONRPCProtocol()
    pf = None
    name = 'None'
    pid = -1
    try:
        pf = ProxyFactory(transport, protocol,
                          identity=client_id + '._proxy', logger=logger)
        name = pf.get_server_identity()
        pf.logger = logger.getChild(name + '_proxy')
        pid = pf.get_server_pid()
    except RPCTransportTimeout:
        logger.warning('failed to reach {0}'.format(server_url))
        transport.shut_down()  # server is not running
    else:
        pf.stub.transport.timeout = old_timeout
    return pf, name, pid


class ManagementService(object):

    rpc_public_api = ['stop_server', 'list', 'connect', 'disconnect',
                      'stop_all_servers', 'get_server_url', 'system_reboot',
                      'system_shutdown', 'fw_version']

    def __init__(self, manager_url):
        self.servers = {}
        self.server_lock = RLock()
        self.manager_url = manager_url

    def reset(self):
        self.logger.info('resetting manager services')
        with self.server_lock:
            for name in list(self.servers.keys()):
                self.remove_server(name)

    def found_new_server(self, iden, server_info):
        with self.server_lock:
            self.servers[iden] = server_info

    def replace_server(self, iden, new_info):
        with self.server_lock:
            self.remove_server(iden)
            self.found_new_server(iden, new_info)

    def touch_server(self, iden, last_time):
        with self.server_lock:
            if s_info := self.servers.get(iden):
                s_info.last_time = last_time

    def remove_server(self, iden):
        with self.server_lock:
            if s_info := self.servers.pop(iden, None):
                if s_info.pf:
                    s_info.pf.shut_down()

    def stop_all_servers(self, wait=False):
        '''
        stop all servers in the reversed order they come up

        Args:
            wait: bool, If 'True', block until the server process terminate before returning.  
                        If 'False', this method returns after make the request to server to terminate.

        '''
        self.logger.info("stop_all_server enter")
        dead_servers = []
        with self.server_lock:
            server_names = list(self.servers.keys())
            server_start_times = dict.fromkeys(server_names, 0)
            for name in server_names:
                server_info = self.servers[name]
                pf = server_info.pf
                if pf is None:
                    self.logger.warning(
                        'trying to stop server {0} that we are not connected to'.format(name))
                    pf, name, _ = connect_to_server(
                        server_info.url, self.logger, client_id='stop_cmd')
                    if pf is None:
                        self.logger.warning('unable to connect to server at {0}'.format(server_info.url))
                        self.disconnect(name)
                    else:
                        try:
                            '''
                            note that in managerment service, we can not rely on the default behaviour
                            of the infrastructure to handle exceptions. Normally when the worker gets a
                            RPCTransportTimeout, there is no point trying to send an error message back
                            to the client. However here we are getting an RPCTransport timeout not because
                            we can not communicate to the client, but becasuse we can not communciate to the
                            app server. So we need to handle this in a way the MangementServer Client can
                            get the error message back
                            '''
                            t = pf.stub('__server__', 'up_since')
                            server_start_times[name] = t
                        except RPCTransportTimeout:
                            self.logger.warning(f'server @{server_info.url} no longer reachable')
                            dead_servers.append(name)

            # get rid of all the unreachable servers first
            for s in dead_servers:
                self.remove_server(s)

            # shut down servers in the reversed order they started
            for name, start_time in reversed(sorted(server_start_times.items(), key=lambda item: item[1])):
                pf = self.servers[name].pf

                try:
                    self.logger.info(f'requesting server {name} to shutdown')
                    pf.stub('__server__', 'shut_down')
                except RPCTransportTimeout:
                    self.logger.warning(f'server {name} no longer reachable')

                pid = self.servers[name].pid
                if wait and pid is not None:
                    self.logger.info(f'waiting for server {name} ({pid}) to terminate...')
                    terminated = wait_pid(pid)
                    if terminated:
                        self.logger.info(f'  server {name} ({pid}) terminated.')
                    else:
                        self.logger.error(f'  server {name} ({pid}) did NOT terminate!')


                self.disconnect(name)

        self.logger.info("stop_all_server exit")

    def stop_server(self, name, wait=False):
        '''
        stop a server
        ManagementService does not start a server, because that requires
        knowledge about drivers.

        Args:
            name: str, name of the server
            wait: bool, If 'True', block until the server process terminate before returning.  
                        If 'False', this method returns after make the request to server to terminate.

        Return:
            str, A message that describe the server has stopped (or was requested to stop).
        '''
        with self.server_lock:
            server_info = self.servers.get(name)
            if server_info is None:
                raise RPCServiceError(f'the management server does not know server {name} does not exist')
            pf = server_info.pf
            pid = server_info.pid
            if pf is None:
                self.logger.warning(
                    'trying to stop server {0} that we are not connected to'.format(name))
                pf, name, pid = connect_to_server(
                    server_info.url, self.logger, client_id='stop_cmd')
                if pf is None:
                    raise RPCServiceError(f'unalbe to connect to server at {server_info.url}')

            self.logger.info(f'requesting server {name} ({pid}) to shutdown')
            try:
                pf.stub('__server__', 'shut_down')
            except RPCTransportTimeout:
                raise RPCServiceError(f'server @{server_info.url} no longer reachable')
            self.disconnect(name)
            if wait and pid is not None:
                self.logger.info(f'  waiting for server process {name} ({pid}) to terminate')
                terminated = wait_pid(pid, 30)
                if not terminated:
                    self.logger.error(f'  server process {name} ({pid}) did not terminate!')
            return 'stopping server {0} at {1}'.format(name, server_info.url)

    def get_server_url(self, name):
        '''
        Get the fully qualified URL of the given server.

        Args:
            name: str, name of the server
        
        Example:
            >>> ms.get_server_url('dut0')
            'tcp://0.0.0.0:7801'
            >>> 
        '''
        if name in self.servers.keys():
            return self.servers[name].url
        else:
            return None

    def connect(self, url):
        '''
        Connect to an App Server.

        You should not need to manually call this method, unless you had explicitly
        call 'disconnect' before.

        Args:
            url: str, the fully qualified URL to the app server.

        Return:
            str, name of the server connected.

        Example:
            ms.connect('tcp://0.0.0.0:25001')
        '''
        pf, name, pid = connect_to_server(url, self.logger, client_id='manager')
        if pf is None:
            raise RuntimeError(
                'unable to connect to server at {0}'.format(url))
        else:
            iden = pf.get_server_identity()
            s_info = ServerInfo(url, pf.server_session, pf=pf, pid=pid)
            self.replace_server(iden, s_info)
        self.logger.info('connected to server {0}'.format(url))
        return name

    def disconnect(self, name):
        '''
        Manager Server to disconnect from a given server.

        Args:
            name: str, name of the server to be disconnected..
        '''
        self.logger.info(f'disconnected from server {name}')
        self.remove_server(name)

    def list(self, return_as_dict = False):
        '''
        list all the servers

        Args:
            return_as_dict: Default False
                            If True, Return dictionary of information, instead of string

        Returns:
            list of strings.  The strings are formatted to provide the url, status, and last ping'

        Example:
            ms.list()
            >>> ms.list()
            ['base_board@tcp://0.0.0.0:25001: connected, last_heard_from: 110.40 seconds ago', 
            'dut0@tcp://0.0.0.0:7801: connected, last_heard_from: 109.47 seconds ago']
        '''
        server_infos = []
        for name, info in self.servers.items():
            connect_status = 'connected'
            if info.pf is None:
                connect_status = 'not connected'
            t = time.time()
            if return_as_dict:
                server_infos.append({
                    'name' : name,
                    'url' : info.url,
                    'connect_status' : connect_status,
                    'last_heard_from_sec' : round(float(t-info.last_time), 2)
                    })
            else:
                server_infos.append(
                    f"{name}@{info.url}: {connect_status}, last_heard_from: {t - info.last_time:.2f} seconds ago")
        return server_infos

    def system_reboot(self):
        '''
        Shutdown all servers, then issue system REBOOT.
        This function returns immediately.

        Return:
            'done', indicate the reboot request has started.
        '''
        self.logger.info('stopping all application servers')
        self.stop_all_servers(True)
        self.logger.info('Xavier rebooting in 3s!')
        delay = 3
        Thread(target=lambda arg: os.system('sync && sleep {} && reboot'.format(arg)), args=[delay]).start()
        return 'done'

    def system_shutdown(self):
        '''
        Shutdown all servers, then issue system SHUTDOWN.
        This function returns immediately.

        Return:
            'done', indicate the shutdown request has started.
        '''
        self.logger.info('stopping all application servers')
        self.stop_all_servers(True)
        self.logger.info('Xavier shutdown in 3s!')
        delay = 3
        Thread(target=lambda arg: os.system('sync && sleep {} && shutdown -P now'.format(arg)), args=[delay]).start()
        return 'done'

    def fw_version(self):
        '''
        return dictionary of mix firmware;
        mix fw version is defined in a json file;
        Currently in /mix/version.json (MIX_FW_VERSION_FILE).
        Returns:
            dict, firmware version information.
        '''
        MIX_FW_VERSION_FILE = '/mix/version.json'
        if not MIX_FW_VERSION_FILE:
            raise Exception('MIX_FW_VERSION_FILE not defined.')
        with open(MIX_FW_VERSION_FILE, 'rb') as f:
            data = f.read()
        return json.loads(data)


class ManagementServer(RPCServer):
    HEART_BEAT_INTERVAL = 3

    def __init__(self, end_point, config, identity='m_server'):
        ctx = zmq.Context().instance()
        ctx.linger = 0
        protocol = JSONRPCProtocol()
        transport = ZMQServerTransport(end_point, ctx)
        iden = identity or end_point
        super().__init__(protocol, transport, iden, config)
        man_service = ManagementService(self.transport.end_point)
        self.register('manager', man_service)
        self.s_man.man_service = man_service

    def setup_extra_dispatchers(self):
        self.s_man = ServerManager(self.logger)
        self.dispatchers.append(self.s_man)

    def heart_beat_action(self):
        self.logger.info(f'....{self._identity} is running @{self.transport.end_point}...')
        # We need to make sure the server list is purged periodically
        # otherwise if no application server is sending ping, the server_manager's
        # purge method is never called
        self.s_man.purge()

    def clean_up(self):
        self.s_man.shut_down()
