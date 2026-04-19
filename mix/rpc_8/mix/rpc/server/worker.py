from .requesthandler import RequestHandlerMixin
from .datastream import DataStreamService
from ..protocols import JSONRPCProtocol, JSONRPCResponse
from ..util import constants
from ..transports.transport_error import RPCTransportTimeout
from ..transports.workerservertransport import ZMQWorkerTransport
from mix.tools.util.excreport import get_exc_desc
from mix.tools.util.logfactory import create_null_logger
from mix.driver.modulebase.mixmoduledriver import MIXModuleDriver
from mix.tools.util.misc import short_id

from threading import Thread, Lock
import zmq
from enum import Enum


class PowerState(Enum):
    StandBy = 0
    Ready = 1


class ServiceWorker(RequestHandlerMixin, Thread):
    '''we want to serailize the exectuion of requests
    to any one service. So no only we need to keep track of the
    incoming request, but the requests in fly. Thd data structure
    seems to get too complicated if we use a thread pool
    '''
    # this is not an ascii code, so should never show up in a service id
    HEART_BEAT_CODE = b'\xa8'
    DATASTREAM_SHUTDOWN_TIMEOUT = 1  # unit is seconds

    def __init__(self, service_id, service, server_endpoint, configs = None):
        super().__init__()
        self.id = service_id
        self.service = service
        self.heart_beat_interval = constants.WORKER_HEART_BEAT_INTERVAL   # 5 second hearbeat
        self.logger = create_null_logger()
        if configs and 'worker_heart_beat_interval' in configs:
            self.heart_beat_interval = configs['worker_heart_beat_interval']
            self.logger.info(f"using {self.heart_beat_interval} as worker heart beat")

        self.poller = zmq.Poller()
        self._prepare_transport(server_endpoint)
        self._prepare_for_data_stream()
        self._prepare_control()
        if isinstance(self.service, MIXModuleDriver):
            self.power_state = PowerState.StandBy
        else:
            self.power_state = PowerState.Ready
        self.serving = False

    def _prepare_transport(self, server_endpoint):
        self.protocol = JSONRPCProtocol()
        self.transport = ZMQWorkerTransport(server_endpoint)
        self.poller.register(self.transport.socket, zmq.POLLIN)

        # announced self to the router
        self.transport.send(b'0', self.id.encode('utf8'))

    def _prepare_for_data_stream(self):
        self.data_stream_services = set()
        self.dss_lock = Lock()
        self.max_dss_count = constants.MAX_DATA_STREAM_PER_WORKER

    def _prepare_control(self):
        # control request can come from any thread.
        control_ep = f'inproc://worker_{self.id}_{short_id(8)}'
        ctx = zmq.Context().instance()
        self.control_sock = ctx.socket(zmq.PAIR)
        self.control_sock.bind(control_ep)
        self.control_pipe = ctx.socket(zmq.PAIR)
        self.control_pipe.connect(control_ep)
        self.poller.register(self.control_sock, zmq.POLLIN)

    def start_new_dss(self, request):
        self.logger.info('got a request to open data stream')
        dss_count = len(self.data_stream_services)
        if dss_count >= self.max_dss_count:
            error_msg = f'too may data streams in {self.id}: '\
                        f'{dss_count} >= {self.max_dss_count};'
            response = self.protocol.error_response(
                request.id, constants.INVALID_REQUEST_ERROR, error_msg)
        else:
            ds = self.call_method(request, self.service)
            identity = f'ds_{short_id(4)}'
            dss = DataStreamService(ds, self, id=identity)
            dss.logger = self.logger.getChild(identity)
            self.data_stream_services.add(dss)
            dss.start()
            result = {
                'port': dss.port,
                'meta_data': dss.data_stream.meta_data,
            }
            response = JSONRPCResponse(request.id, result)
        return response

    def remove_dss(self, dss):
        with self.dss_lock:
            # this lock is to protect if some dss tries to remove
            # itself when we are in the process of shutting everything down
            try:
                self.data_stream_services.remove(dss)
            except KeyError as e:
                self.logger.warning(f'remove_dss errored: {e}')

    def shut_all_dss(self):
        dss_finished = set()
        with self.dss_lock:
            # self.logger.debug('got dss_lock')
            for dss in self.data_stream_services:
                dss.quit()
            for dss in self.data_stream_services:
                if dss.is_alive():
                    dss.join(self.DATASTREAM_SHUTDOWN_TIMEOUT)
                if dss.is_alive():
                    self.logger.warning(f'datastream service {dss.identity} did not shutdown')
                else:
                    dss_finished.add(dss)
        for dss in dss_finished:
            self.remove_dss(dss)
        dss_finished.clear()
        self.logger.debug('finished shutting all dss')

    def shut_down(self):
        self.serving = False
        self.logger.info(f"shutting down worker {self.id}")
        self.shut_all_dss()
        if hasattr(self.service, 'reset'):
            try:
                self.service.reset()
            except Exception as exc:
                self.logger.exception(exc)
        self.transport.shut_down()
        if not self.control_sock.closed:
            self.control_sock.close(linger=0)
        if not self.control_pipe.closed:
            self.control_pipe.close(linger=0)

    def quit(self):
        if self.serving:
            self.control_pipe.send(b'quit')
        else:
            self.shut_down()

    def _handle_control_request(self):
        '''
        if this method returns True, we should break out
        of the main loop
        '''
        msg = self.control_sock.recv()
        self.logger.info(f'got control request {msg}')
        if msg == b'quit':
            return True

    def _handle_client_request(self):
        request = None
        try:
            client, request_bytes = self.transport.recv()
            request = self.protocol.parse_request(request_bytes)
            self.logger.info(f"from {client}, received {request}")
            if self.power_state is not PowerState.Ready:
                error_msg = f"try to use {self.id} when the power state is not ready"
                self.logger.error(error_msg)
                response = JSONRPCResponse(request.id, None, constants.INVALID_REQUEST_ERROR, error_msg)
                self.transport.send(client, response.serialize())
                return
            if request.method in self.service.rpc_public_api_async:
                self.logger.debug('gotten async call {0}'.format(request.method))
                response = JSONRPCResponse(request.id, True)
                # for async request, send a response first before
                # we execute the method
                self.transport.send(client, response.serialize())
                try:
                    self.call_method(request, self.service)
                except Exception as exc:
                    # we don't want to send back to the client becasue
                    # it has moved on
                    self.logger.exception(exc)
                return

            if request.method in self.service.rpc_data_path_open:
                response = self.start_new_dss(request)
            else:
                result = self.call_method(request, self.service)
                response = JSONRPCResponse(request.id, result)
            self.transport.send(client, response.serialize())
        except RPCTransportTimeout as exc:
            self.logger.exception(exc)
        except Exception as e:
            if request:
                extra_msg = "error calling {0}.{1}".format(
                    self.service.__class__, request.method)
                response = self.protocol.exp_error_response(
                    request.id, e, extra_msg)
                self.logger.exception(e)
                self.transport.send(client, response.serialize())
            else:   # if request can not be parsed correctly, we don't know what to do
                self.logger.exception(e)

    def run(self):
        self.logger.info(f'worker for {self.id} start serving... using {self.heart_beat_interval}')
        self.serving = True
        while self.serving:
            try:
                socks = dict(self.poller.poll(self.heart_beat_interval))
                if self.transport.socket in socks:
                    self._handle_client_request()
                elif self.control_sock in socks:
                    if self._handle_control_request():
                        break
                else:  # time to send a heart_beat
                    self.transport.send(b'0', self.HEART_BEAT_CODE)
            except Exception as e:
                self.logger.error('!!!!!!!!something went wrong in the main loop for service {0}: '.format(
                    self.service.__class__))
                self.logger.critical(get_exc_desc(e))
        self.shut_down()
