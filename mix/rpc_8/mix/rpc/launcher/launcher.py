import os
import time
import multiprocessing
import logging
import queue

from mix.tools.util.logfactory import LogMasterMixin, log_entry
from mix.tools.util.excreport import get_exc_desc
from ..services.xavier import Xavier
from ..proxy.proxyfactory import ProxyFactory
from .interprocess import InterProcessEvents
from mix.tools.util.detach import daemonize
from mix.tools.util.misc import is_running_on_zynq
from mix.driver.core.zynq import Zynq, ZynqSim
from mix.tools.util.linuxhelper import LinuxHelper, LinuxHelperSim
from mix.rpc.util import constants
from ..services.fileservice import FileService
from ..services.logcollectionservice import LogCollectionService

SERVER_JOIN_TIMEOUT = 100  # seconds

FS_ALLOW = ['/tmp', '/tmp/logcollect', '/var/fw_update/upload', '/var/tmp/mix']

class LoggerHost(LogMasterMixin):

    def __init__(self, iden):
        super().__init__()
        self.setup_logger(iden)

    def __del__(self):
        if self._logger:
            self.stop_logger()


def run_man_server(profile_helper, events, queue, daemon=True):
    if daemon:
        daemonize()
    host = LoggerHost('launcher_manserver')
    logger = host.logger
    # so that the first line of the log always starts with a timestamp
    logger.info("launching the manager server")
    settings = profile_helper.get_manager_settings()
    try:
        from mix.rpc.server.mserver import ManagementServer
        m_server = ManagementServer(
            settings.url, settings.config)
        events['server'].set()
        logger.info("management server started")

        fs_config = profile_helper.get_file_system_settings()
        #We will always have a file system. We might not have allow_list inside it.
        if fs_config is not None:
            fs = FileService(FS_ALLOW + fs_config.get('allow_list', []) )
            m_server.register('file_system', fs)
            logger.info("the file system service started")

            # Let's configure Log Collection that uses FileService
        lc = LogCollectionService()
        m_server.register(constants.LOG_COLLECTOR_NAME, lc)

        zynq = ZynqSim()
        os_helper = LinuxHelperSim()
        simulated = not is_running_on_zynq()
        if not simulated:
            zynq = Zynq()
            os_helper = LinuxHelper()
        xavier = Xavier(zynq, os_helper)
        m_server.register('xavier', xavier)
        logger.info("the xavier service started")

        m_server.set_state(constants.MIX_SERVER_STATE_LOADED)

        ip_addr = profile_helper.get_xavier_ip()
        xavier.set_ip(ip_addr)
        events['xavier'].set()
        logger.info(f"the xavier ip is set to {ip_addr}")
        queue.put(os.getpid())

        m_server.start()
        m_server.set_state(constants.MIX_SERVER_STATE_READY)

        m_server.join(SERVER_JOIN_TIMEOUT)
    except Exception as e:
        logger.info(f'gotten exception {get_exc_desc(e)}')
        queue.put(RuntimeError(get_exc_desc(e)))

    host.stop_logger()


def run_app_server(server_name, profile_helper, events, queue, daemon=True):
    if daemon:
        daemonize()
    a_server = None
    host = LoggerHost(f'launcher_appserver_{server_name}')
    logger = host.logger
    # so that the first line of the log always starts with a timestamp
    logger.info(f"launching appserver {server_name}")
    '''
    this is the instrument factory returned by get_services_for_server
    this variable has to be in scope in the try and the except block
    because we need the proxyfactories held by the InstFactory to power
    down instruments
    '''
    factory = None

    try:
        # we create the server here but don't start the server
        # we just want to use the log file for the server
        from mix.rpc.server.appserver import RPCAppServer

        config = profile_helper.get_app_server_settings(server_name)
        a_server = RPCAppServer.DefaultServer(
            config.url, server_name, config.config)

        logger.info(f"in new process starting to run app server {server_name}")
        profile_helper.logger = logger

        services, factory = profile_helper.get_services_for_server(server_name)
        logger.info(f'get service objects {services}')

        for name, service_obj in services.items():
            a_server.register(name, service_obj.service, service_obj.two_step)

        events.set(constants.MIX_SERVER_STATE_LOADED)
        a_server.set_state(constants.MIX_SERVER_STATE_LOADED)

        a_server.start()
        logger.info("server_started")

        pf = ProxyFactory.DefaultFactory(config.url, f'{server_name}_power_on_proxy')
        events.set(constants.MIX_SERVER_STATE_POWER_ON)
        a_server.set_state(constants.MIX_SERVER_STATE_POWER_ON)
        for name in services.keys():
            ret = pf.power_on(name)
            logger.info(f'power on {name}, ret = {ret}')
        pf.shut_down()

        events.set(constants.MIX_SERVER_STATE_READY)
        a_server.set_state(constants.MIX_SERVER_STATE_READY)
        queue.put(os.getpid())
        a_server.join(timeout=SERVER_JOIN_TIMEOUT)
    except Exception as e_mainloop:
        logger.info(f'launcher handling exception {get_exc_desc(e_mainloop)} when running {server_name}')

        if a_server:
            try:
                a_server.shut_down()
                if a_server.is_alive():
                    a_server.join(timeout=SERVER_JOIN_TIMEOUT)
            except Exception as e:
                logger.error(f"error shutting down {server_name}:{e}")
        queue.put(RuntimeError(get_exc_desc(e_mainloop)))
        logger.info('finished error handling')

    host.stop_logger()


class Launcher(LogMasterMixin, object):

    EVENT_TIMEOUT = 120  # 120 seconds
    SW_EVENT_TIMEOUT = 10  # 10 seconds
    HW_EVENT_TIMEOUT = 10

    def __init__(self, iden='launcher'):
        super().__init__()
        self.setup_logger(iden)
        self.logger.info('launcher created')
        self.started_servers = {}

    def __del__(self):
        self.stop_logger()

    @log_entry(logging.INFO)
    def launch_man_server(self, profile_helper):
        q = multiprocessing.Queue()
        events = InterProcessEvents(q)
        events.create('server')
        events.create('xavier')
        p = multiprocessing.Process(
            target=run_man_server, args=(profile_helper, events, q))
        p.start()

        for name in events.event_names():
            try:
                self.logger.info(f'waiting for event {name}')
                events.wait_on(name, self.EVENT_TIMEOUT)
                self.logger.info(
                    'management server event {0} happened'.format(name))
            except RuntimeError as e:
                self.logger.exception(e)
                raise RuntimeError('problem launching the manager server')

        time.sleep(0.1)  # because interprocess queue need some time
        try:
            m = q.get_nowait()
            # this should be the process id
            self.logger.info("pid for manager server is {0}".format(m))
            return m
        except queue.Empty:
            raise RuntimeError('could not get the man server process id')

    @log_entry(logging.INFO)
    def launch_app_server(self, server_name, profile_helper):
        q = multiprocessing.Queue()
        events = InterProcessEvents(q)
        events.create(constants.MIX_SERVER_STATE_LOADED)
        events.create(constants.MIX_SERVER_STATE_POWER_ON)
        events.create(constants.MIX_SERVER_STATE_READY)
        p = multiprocessing.Process(
            target=run_app_server, args=(server_name, profile_helper, events, q))
        p.start()
        for name in events.event_names():
            try:
                self.logger.info(f'app server {server_name}, waiting for {name}')
                events.wait_on(name, self.EVENT_TIMEOUT)
                self.logger.info(
                    'app server {0}; event {1} happened'.format(server_name, name))
            except RuntimeError as e:
                self.logger.info(f"while waiting for {name} for {server_name}, got exception {e}")
                self.logger.exception(e)
                raise RuntimeError(f'problem launching appserver {server_name}')

        time.sleep(0.1)
        try:
            m = q.get_nowait()
            # this should be the process id
            self.logger.info(
                "pid for app server {0} is {1}".format(server_name, m))
            return m
        except queue.Empty:
            raise RuntimeError('could not get the appserver process id')

    def log_error(self, msg, e):
        self.logger.error('!!!!!!! {0}: {1}'.format(msg, get_exc_desc(e)))

    @log_entry(logging.INFO)
    def go(self, profile_helper):
        self.started_servers = {}
        man_url = profile_helper.get_manager_settings().url
        try:
            pid = self.launch_man_server(profile_helper)
            self.started_servers['management'] = (pid, man_url)
        except Exception as e:
            self.log_error('error launching manager server', e)
            raise e

        pf_man = ProxyFactory.DefaultFactory(man_url, 'launcher.man_pf')
        manager = pf_man.get_proxy('manager')

        for server_name in profile_helper.app_server_list:
            try:
                server_cfg = profile_helper.get_app_server_settings(
                    server_name)
                pid = self.launch_app_server(server_name, profile_helper)
                self.started_servers[server_name] = (pid, server_cfg.url)
                manager.connect(server_cfg.url)
            except Exception as e:
                self.log_error(
                    'error launching app server for {0}'.format(server_name), e)

        pf_man.shut_down()
        return self.started_servers
