import zmq
from abc import ABCMeta
from threading import Thread
import logging
import time
import uuid
import os

from ..transports import ZMQServerTransport
from ..protocols import JSONRPCProtocol
from .clientmanager import ClientManager
from .workermanager import WorkerManager
from mix.tools.util.logfactory import LogMasterMixin
from .requesthandler import RequestHandlerMixin
from ..util import constants
# from ..util.constants import constants

def server_state_num(state_str):
    key = f'MIX_SERVER_STATE_{state_str}_NUM'
    return getattr(constants, key, None)

class RPCServer(RequestHandlerMixin, LogMasterMixin, Thread, metaclass=ABCMeta):

    MAJOR_VERSION = constants.RPC_MAJOR_VERSION
    MINOR_VERSION = constants.RPC_MINOR_VERSION
    REVISION = constants.RPC_REVISION

    __version = f'{MAJOR_VERSION}.{MINOR_VERSION}.{REVISION}'
    rpc_public_api = ['shut_down', 'version', 'identity', 'pid', 'get_service_info', 'get_state',
                      'get_all_services', 'get_all_loggers', 'get_config', 'set_config', 'up_since']
    DEFAULT_CONFIG = {
        'heart_beat_interval': 3000,  # unit is milliseconds
        'logging_level': logging.INFO,
        'worker_quit_timeout': 100,  # unit is seconds
        'worker_heart_beat_interval': constants.WORKER_HEART_BEAT_INTERVAL, # unit is milliseconds
    }

    '''
    each server can be further configured. In a production system, the configuration
    should be in software.json
    '''

    def __init__(self, protocol, transport, identity, config=None):
        super().__init__()
        self.state = constants.MIX_SERVER_STATE_INIT
        self._identity = identity or transport.identity
        self.config = self.DEFAULT_CONFIG.copy()
        self.setup_logger(f"mix.{self._identity}", self.config['logging_level'])

        self.transport = transport
        self.transport.logger = self.logger.getChild('transport')
        self.serving = False
        self.back_transport_ep = f'inproc://{self._identity}_bt_router'
        self.protocol = protocol
        self._up_since = 0
        self.session_id = str(uuid.uuid4())

        self.__configure(config)

        self.poller = zmq.Poller()
        self.dispatchers = []
        self.setup_service_dispatcher()
        self.setup_extra_dispatchers()

        for d in self.dispatchers:
            self.poller.register(d.listening_socket, zmq.POLLIN)

        self.setup_heart_beat()

    def setup_service_dispatcher(self):
        self.worker_man = WorkerManager(self, self.config)
        self.client_man = ClientManager(self, self.worker_man)
        self.dispatchers.append(self.worker_man)
        self.dispatchers.append(self.client_man)

    def __configure(self, config):
        if config:
            for key, value in config.items():
                if key in self.config:
                    self.set_config(key, value)
                else:  # this is a new key
                    self.config[key] = value

    def __shutdown(self):

        self.worker_man.shut_down(self.config['worker_quit_timeout'])

        self.clean_up()

        for d in self.dispatchers:
            if not d.listening_socket.closed:
                d.listening_socket.close(linger=0)

        # shut down the transport last, in case we
        # run into problem with worker quit
        self.transport.shut_down()

        self.logger.info("shutting down server {0}...".format(self._identity))

        self.stop_logger()

    def get_config(self, name=None):
        if name is None:
            return self.config
        else:
            return self.config[name]

    def set_config(self, name, value):
        old_val = self.config[name]
        val_type = type(old_val)
        new_val = val_type(value)
        # we can set the value now that we know it's a
        # compatible type
        self.config[name] = new_val

        # if there are too many property needs special treatment
        # I will turn config into a class with dunder methods.
        if name == 'logging_level':
            self.logger.setLevel(new_val)

    def get_state(self):
        '''
        Return the server's life-cycle state.
        '''
        return self.state

    def set_state(self, state):
        prev_state = self.state
        next_state = state

        if server_state_num(next_state) < server_state_num(prev_state):
            # When SERVING --> READY, sometimes the state change can reverse because
            # server thread start sets 'SERVING', but launcher is the one that set 'READY'.  
            #
            # The better implementation is to change lifecycle and server loading completely
            # done by RPCAppServer() or ManagementServer() class.
            self.logger.info(f'Server state {prev_state}--> {next_state} is not valid.  Skipping state change.')
            return

        self.logger.info(f'Server state {prev_state}--> {next_state}')
        self.state = next_state

    def run(self):
        self.serving = True
        self.logger.info("starting server {0} pid={1}...".format(self._identity, os.getpid()))
        self.heart_beat_action()    # heart beat once
        self.last_time = time.time()
        self._up_since = self.last_time

        self.set_state(constants.MIX_SERVER_STATE_SERVING)
        while self.serving:
            try:
                polling_timeout = self.config['heart_beat_interval']
                socks = dict(self.poller.poll(timeout=polling_timeout))
                if len(socks) > 0:
                    for d in self.dispatchers:
                        if d.listening_socket in socks:
                            d.dispatch()

                self.heart_beat()
            except zmq.ContextTerminated:
                # todo: this should really be ConnectionLost, so we can
                # decouple form ZMQ
                break
            except Exception as exc:
                error_msg = f'!!!!!Unexpected exception happened in server {self._identity} main loop: {exc}'
                self.logger.exception(error_msg)
        self.__shutdown()
        self.set_state(constants.MIX_SERVER_STATE_TERMINATED)

    def register(self, name, service, two_step=None):
        if not hasattr(service, 'rpc_public_api'):
            self.logger.error('{0} can not be registered becasue it has no '
                              'rpc_public_api'.format(type(service)))
            return None
        return self.worker_man.add_service(name, service)

    def get_service(self, name):
        '''
        this is a helper function to get the service object
        '''
        return self.worker_man.workers[name].worker.service

    def get_worker(self, name):
        '''
        this is helper function to get the ServiceWorker object
        '''
        return self.worker_man.workers[name].worker

    def heart_beat(self):
        t = time.time()
        if t - self.last_time > (self.config['heart_beat_interval'] / 1000):
            # make sure the client manager's purge is called periodically if
            # no new client requests are coming in. Otherwise purge() is only called
            # when a new client tries to connect
            self.client_man.purge()
            self.heart_beat_action()
            self.last_time = t

    # ================these are methods to be overwritten =============================

    def setup_heart_beat(self):
        '''
        This is called in the constructor. Derived calss shoudl prepare their
        heart beat action here
        '''
        pass

    def heart_beat_action(self):
        '''
        this is the method to override in derived class to customize heart_beat action.
        By default just write a log entry
        '''
        self.logger.info('.....{0} is alive...'.format(self._identity))

    def setup_extra_dispatchers(self):
        '''
        if a derived class wants extra dispatchers to be registered with the main loop
        poller, they should set them up here
        '''
        pass

    def clean_up(self):
        '''
        this is called by __shutdown after all workers have been shut down and before
        the transport is shut down. Derived class should implemente their specific clean up
        actons here.
        '''
        pass

    # ================public API starts =============================
    def get_all_loggers(self):
        logger_info = []
        for name, logger in logging.root.manager.loggerDict.items():
            # the environment could have added other loggers
            if name.startswith(f"mix.{self._identity}"):
                if isinstance(logger, logging.PlaceHolder):
                    continue
                self.logger.debug(name)
                msg = '{0} at level {1} with handlers {2}'.format(
                    name, logger.level, str(logger.handlers))
                logger_info.append(msg)
                self.logger.debug(msg)
        return logger_info

    def up_since(self):
        return self._up_since

    def shut_down(self):
        '''
        This method does not guarantee the server process/thread is terminated on return.
        If this server is running on the same thread, use server.join() to assure server thread dies.
        If this server is running on differnt proces, use util.misc.wait_pid(<server_pid>).
        '''
        self.set_state(constants.MIX_SERVER_STATE_TERMINATING)
        if not self.is_alive():
            self.__shutdown()
        else:
            self.serving = False

    def __del__(self):
        if hasattr(self, 'transport'):
            # it's possible an error happened in a derived class
            # before super().__init__() is called, self does not
            # have the transport member
            if self.transport:
                self.transport.shut_down()

    def version(self) -> str:
        return self.__version

    def identity(self) -> str:
        return self._identity

    def pid(self) -> int:
        return os.getpid()

    def get_service_info(self, service_name):
        return self.worker_man.get_service_info(service_name)

    def get_all_services(self) -> tuple:
        ss = [name for name in self.worker_man.workers.keys()
              if not name.startswith('__')]
        return tuple(ss)

    # classmeethod is the right way to create overloaded constructor in python
    @classmethod
    def JsonZmqServer(cls, end_point, identity=None, config=None):
        ctx = zmq.Context().instance()
        ctx.linger = 0
        protocol = JSONRPCProtocol()
        transport = ZMQServerTransport(end_point, ctx)
        iden = identity or end_point
        return cls(protocol, transport, iden, config)

    DefaultServer = JsonZmqServer
