from mix.tools.util.logfactory import LogMasterMixin
from ..transports import RPCTransportTimeout, ZMQClientTransport
from ..protocols import JSONRPCProtocol
from .proxy import RPCProxy
from .stub import RPCClient
from .eventserver import EventServer
from ..util import constants
# from ..util.constants import constants
import zmq
import time
import weakref

POWER_CTRL_SERVICE = constants.POWER_CTRL_NAME


class CachedInstance(type):
    # there is only one ProxyFacotry per URL
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # use weakref so that only instance that is acutally used are retained
        self. __cache = weakref.WeakValueDictionary()

    def __call__(self, transport, *args, **kwargs):
        url = transport.end_point
        obj = self.__cache.get(url)
        if obj is None:
            obj = super().__call__(transport, *args, **kwargs)
            self.__cache[url] = obj
            return obj
        else:
            return obj


class ProxyFactory(LogMasterMixin):

    '''
    Each ProxyFactory owns one socket, all proxies from this facotry will
    get the same socket. Access to this socket is exclusive by first acquiring a lock.
    So if you are concerned there are too many proxies and the line to use th socket
    gets too long, you shoudl create a different ProxyFactory.
    '''

    MAJOR_VERSION = constants.RPC_MAJOR_VERSION
    MINOR_VERSION = constants.RPC_MINOR_VERSION
    REVISION = constants.RPC_REVISION
    __version = f'{MAJOR_VERSION}.{MINOR_VERSION}.{REVISION}'

    def __init__(self, transport, protocol, identity=None, logger=None):
        self.event_server = None
        self.stub = None
        self.identity = identity or 'pf_' + transport.end_point
        super().__init__()
        if logger is None:
            self.setup_logger(self.identity)
        else:
            self.logger = logger

        self.proxy_cache = {}

        self.stub = RPCClient(transport, protocol)
        self.logger.info("client established")
        self.stub.logger = self.logger.getChild('stub')
        self.server_version = None
        old_timeout = self.stub.timeout
        try:
            self.stub.timeout = 300  # for testing the connection. unit is milisecond
            self.server_version = self.check_version()
            result = self.stub(constants.MIX_CLIENT_MANAGER, constants.MIX_CLIENT_HELLO, self.identity)
            self.server_session = result
        except RPCTransportTimeout:
            error_msg = "!!!!!!Not able to connect to server at {0}".format(
                transport.end_point)
            self.logger.error(error_msg)
            self.shut_down()  # __init__ needs to clean up after itself. dont' rely on __del__
            raise RPCTransportTimeout(error_msg)
        except RuntimeError as e:
            self.logger.critical('RuntimeError in __init__:{0}'.format(str(e)))
            self.shut_down()
            raise e

        self.stub.timeout = old_timeout

    def check_version(self):
        version = self.stub('__server__', 'version')
        self.logger.info(f'server version is {version}, proxy version is {self.__version}')
        try:
            major, minor, rev = [int(part) for part in version.split('.')]
            if major != self.MAJOR_VERSION:
                raise RuntimeError(
                    f"Version mismatched: server's major version is {major}, expects {self.MAJOR_VERSION}")
            if minor > self.MINOR_VERSION:
                self.logger.warning('server has new features. Please update your MIX client.')
            elif minor < self.MINOR_VERSION:
                self.logger.warning('server may not have some features you need')
            if rev > self.REVISION:
                self.logger.warning('server has bug fixes. Please update your MIX client')
            elif rev < self.REVISION:
                self.logger.warning('server may not have some bug fixes you need')
            return version
        except ValueError:
            raise RuntimeError(f'version string from server "{version}"" is not the expected format')

    def get_proxy(self, remote_obj_id):

        if remote_obj_id in self.proxy_cache:
            return self.proxy_cache[remote_obj_id]

        try:
            obj_info = self.stub('__server__', 'get_service_info', remote_obj_id)
            self.logger.info("for {0} got info: {1}".format(
                remote_obj_id, obj_info))
            logger = self.logger.getChild(remote_obj_id)
            # logger.propagate = True
            self.proxy_cache[remote_obj_id] = RPCProxy(remote_obj_id, obj_info, logger, self.stub, self)
            return self.proxy_cache[remote_obj_id]
        except Exception as e:
            # log to client logger and pass error up.
            self.logger.error(e)
            raise e

    def power_on(self, remote_obj_id):
        return self.stub(POWER_CTRL_SERVICE, 'power_on', remote_obj_id)

    def power_off(self, remote_obj_id):
        return self.stub(POWER_CTRL_SERVICE, 'power_off', remote_obj_id)

    def list_remote_services(self):
        service_names = self.stub('__server__', 'get_all_services')
        return service_names

    def get_server_version(self):
        return self.stub('__server__', 'version')

    def get_server_identity(self):
        return self.stub('__server__', 'identity')

    def get_server_pid(self):
        return self.stub('__server__', 'pid')

    def get_server_state(self):
        '''
        Get the Server's state.
 
        Server has the following possible states:
            INIT - Server is just instantiated programmatically.
            LOADED - All services designated for this server is registered.  (Hardware may not be useable yet!)
            SERVING - Server can now receive connection from Clients.  This is the first possible state you can retrieve.
            POWER_ON - Server is in the process of powering on hardware.
            READY - All services has been powered on.  Test Sequencer should wait for this state before testing.
            TERMINATING - Server has received command to shutdown and is in the process of power off hardware.
            TERMINATED - Server process is just about to exit.  You are not likely to intercept this state.
        '''
        return self.stub('__server__', 'get_state')

    def wait_server_state(self, state, timeout):
        '''
        Wait for server to enter a specific state, such as 'READY' before attempting instrument access.

        If the server's state has already progress pass the given state, this method returns immediately.

        Args:
            state: str, the state name.  See `get_server_state`.
            timeout: float, the time in seconds to wait.

        Return:
            str, the state it is currently.
        
        Example:
            try:
                pf = ProxyFactory.DefaultFactory('tcp://169.254.1.32:7801', timeout=30)
                assert pf
                if 'READY' == pf.wait_server_state('READY', 120):
                    # start testing
            except:
                # log error
        '''
           
        target_state_num = getattr(constants, f'MIX_SERVER_STATE_{state}_NUM', None)        
        if  target_state_num is None:
            raise ValueError(f'state "{state}" is not valid')

        def get_server_state_ex():
            '''
            get the current state as a tuple of (state_num, state_str)
            '''
            st = self.get_server_state()
            return (getattr(constants, f'MIX_SERVER_STATE_{st}_NUM', None), st)

        current_state_num, current_state = get_server_state_ex()

        if current_state_num >= target_state_num:
            return current_state

        start = time.time()
        while True:
            current_state_num, current_state = get_server_state_ex()
            if current_state_num >= target_state_num or time.time() > start + timeout:
                break
            time.sleep(0.1)

        return current_state

    def get_server_loggers(self):
        return self.stub('__server__', 'get_all_loggers')

    def get_config(self, name):
        return self.stub('__server__', 'get_config', name)

    def set_config(self, name, value):
        return self.stub('__server__', 'set_config', name, value)

    def set_rpc_timeout(self, timeout_ms):
        '''
        Convenient method to set RPC timeout.
        Same as: pf.stub.timeout = <timeout_ms>
        '''
        self.stub.timeout = timeout_ms

    def shut_down(self):
        try:
            if self.event_server and self.event_server.serving:
                self.event_server.shut_down()
            if self.stub:
                self.logger.info('shutting down proxyfactory ' + self.identity)
                self.stub.say_bye_to_server()
                self.stub.close()
                self.stop_logger()
                self.stub = None
        except ImportError:
            '''
            if we are shutting down the proxy factory due to garbage collecton,
            sometimes we get this error:
                Traceback (most recent call last):
              File "/Library/Frameworks/Python.framework/Versions/3.9/lib/python3.9/logging/handlers.py",
              line 1431, in emit
                self.enqueue(self.prepare(record))
              File "/Library/Frameworks/Python.framework/Versions/3.9/lib/python3.9/logging/handlers.py",
              line 1416, in prepare
                record = copy.copy(record)
              File "/Library/Frameworks/Python.framework/Versions/3.9/lib/python3.9/copy.py", line 92, in copy
                rv = reductor(4)
            ImportError: sys.meta_path is None, Python is likely shutting down
            '''
            pass

    def __del__(self):
        '''
        in normal use, the client code should alwasy call shut_down, instead of
        relying on the destructor. but if there is unknown excpetion on the client
        side, We need to make sure any service side resources the proxy has
        asked for is released.
        But at this time logger does not work, you get an ImportError becasue when
        the interpreter is shutting down, something the logging module depends on is
        already gone.
        '''
        if self.event_server and self.event_server.serving:
            self.event_server.shut_down()
        if self.stub:
            self.stub.close()

    def context(self, local_logging_level=None, server_logging_level=None, rpc_timeout=None, 
                worker_quit_timeout=None, heart_beat_interval=None):
        return ConfigContext(self, 
                            local_logging_level=local_logging_level,
                            server_logging_level=server_logging_level,
                            rpc_timeout=rpc_timeout,
                            worker_quit_timeout=worker_quit_timeout,
                            heart_beat_interval=heart_beat_interval)

    def get_event_server(self):
        if not self.event_server:
            id = f'{self.identity}_es'
            self.event_server = EventServer(id, self)
            self.event_server.logger = self.logger.getChild(id)
        return self.event_server

    def listen_for(self, event_name, listener):
        self.event_server.register(event_name, listener)
        if not self.event_server.serving:
            self.event_server.start()

    @classmethod
    def JsonZmqFactory(cls, server_url, identity=None, timeout=0):
        """
        Get a ProxyFactory with JsonZmq transport.

        Args:
            server_url: str, A fully qualifed URL to the server.  Ex: 'tcp://169.254.1.32:7801'
            identity: str, (optional) Client side identifier string.
            timeout: float, (optional) Connect attempt timeout.  If server connection is not 
                available, keep retrying until timeout.  If ommitted, and connection error occurs,
                this call will return immediately.
        """
        exc = None
        factory = None
        start = time.time()
        while True:
            try:
                ctx = zmq.Context().instance()
                ctx.linger = 0
                transport = ZMQClientTransport(server_url, ctx)
                protocol = JSONRPCProtocol()
                factory = cls(transport, protocol, identity)
                break                                           # Success
            except RPCTransportTimeout as e:
                del transport
                del protocol
                exc = e

            if time.time() > start + timeout:                   # timeout
                if exc is not None:
                    raise exc
                break

            time.sleep(0.3)                                     # delay before retry

        return factory

    DefaultFactory = JsonZmqFactory

class ConfigContext():

    def __init__(self, proxy: ProxyFactory, local_logging_level=None, server_logging_level=None,
                rpc_timeout=None, worker_quit_timeout=None, heart_beat_interval=None, ):
        self.proxy = proxy

        # Server properties are updated via pf.get_config()/pf.set_config()
        self.server_cache = {
            'logging_level': {
                'newval': server_logging_level,
            },
            'worker_quit_timeout': {
                'newval': worker_quit_timeout,
            },
            'heart_beat_interval': {
                'newval': heart_beat_interval,
            },
        }

        # Local properites are directly assigned
        self.local_cache = {
            'self.proxy.logger.level': {
                'newval': local_logging_level,
            },
            'self.proxy.stub.timeout': {
                'newval': rpc_timeout,
            },
        }

    def __enter__(self):

        # Save old values
        for k in self.server_cache:
            self.server_cache[k]['oldval'] = self.proxy.get_config(k)
        for k in self.local_cache:
            self.local_cache[k]['oldval'] = eval(k)

        # Update new value
        for k in self.server_cache:
            if self.server_cache[k]['newval'] is not None:
                self.proxy.set_config(k, self.server_cache[k]['newval'])
        for k in self.local_cache:
            if self.local_cache[k]['newval'] is not None:
                exec(f"{k} = {self.local_cache[k]['newval']}")

        self.proxy.logger.debug(f'ServerContext update values {self.local_cache} {self.server_cache}')

    def __exit__(self, type, value, traceback):

        # Restore local values
        for k in self.local_cache:
            if self.local_cache[k]['newval'] is not None:
                self.proxy.logger.debug(f"ServerContext restoring proxy local value {k} {self.local_cache[k]['oldval']}")
                exec(f"{k} = {self.local_cache[k]['oldval']}")

        # Restore server's values
        for k in self.server_cache:
            if self.server_cache[k]['newval'] is not None:
                self.proxy.logger.debug(f"ServerContext restoring server value {k} {self.server_cache[k]['oldval']}")
                self.proxy.set_config(k, self.server_cache[k]['oldval'])
