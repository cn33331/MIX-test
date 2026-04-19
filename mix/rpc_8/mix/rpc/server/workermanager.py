from ..transports.workerservertransport import ZMQServerWorkerTransport
from .worker import ServiceWorker
from .dispatcher import Dispatcher
from ..rpc_error import RPCError
from ..services.eventobjects import EventSource
from ..protocols import datarpc

import zmq
import inspect
import time
from ..protocols.jsonrpc import json_extend_encode


def ensure_list(service, val_name):
    '''helper function to ensure service.val_name is a list'''
    if not hasattr(service, val_name):
        setattr(service, val_name, [])
    else:
        val_val = getattr(service, val_name)
        if not isinstance(val_val, list):
            setattr(service, val_name, [val_val])


def ensure_rpc_service(service):
    '''
    make sure the service has all the rpc related fields in place
    for future processing
    '''
    ensure_list(service, 'rpc_public_api')
    ensure_list(service, 'rpc_public_api_async')
    ensure_list(service, 'rpc_data_path_open')
    ensure_list(service, 'rpc_events')

    service.rpc_public_api.extend(service.rpc_data_path_open)
    service.rpc_public_api.extend(service.rpc_public_api_async)


class WMWorker(object):
    '''data structure to represent a worker in the
    WorkerManager
    '''
    def __init__(self, worker, route_id=None):
        self.worker = worker
        self.route_id = route_id


class WorkerManager(Dispatcher):
    '''Manage all the workers on behalf of the server'''

    def __init__(self, server, config = None):
        self.server = server
        self.config = config
        self.protocol = server.protocol
        self.transport = ZMQServerWorkerTransport(server.back_transport_ep)
        self.client_transport = server.transport
        self.logger = server.logger.getChild('wm')
        self.workers = {}

    @property
    def listening_socket(self):
        return self.transport.socket

    def add_service(self, service_id, service):
        self.logger.info(f'adding service {service_id}')
        if service_id in self.workers.keys():
            error_msg = f'service name {service_id} has been used'
            self.logger.error(error_msg)
            raise RPCError(error_msg)
        ensure_rpc_service(service)
        worker = ServiceWorker(service_id, service, self.server.back_transport_ep, self.config)
        worker.logger = self.logger.getChild(f'w_{service_id}')
        service.logger = worker.logger.getChild(f'{service_id}')
        self.workers[service_id] = WMWorker(worker)
        return worker

    def set_worker_route(self, service_id, route_id):
        try:
            wmw = self.workers[service_id]
            wmw.route_id = route_id
        except KeyError:
            raise RPCError(f'unknown service: {service_id}')

    def get_worker_route(self, service_id):
        try:
            wmw = self.workers[service_id]
            if wmw.route_id is None:
                raise RPCError(f'No route information for ServiceWorker {service_id}')
            return wmw.route_id
        except KeyError:
            raise RPCError(f'unknown service: {service_id}')

    def dispatch(self):
        w_route, client, msg = self.transport.recv()
        self.logger.debug(f'in worker man, w_route:{w_route}, client:{client}')
        if client == b'0':
            if msg == ServiceWorker.HEART_BEAT_CODE:
                self.logger.debug(f'received heart beat from {w_route}')
            else:
                service_id = msg.decode('utf8')
                self.set_worker_route(service_id, w_route)
        else:
            self.client_transport.send(client, msg)

    def handle_request(self, client, service_id, msg: bytes):
        try:
            wmw = self.workers[service_id]
            if wmw.route_id is None:
                raise RPCError(f'No route information for ServiceWorker {service_id}')
            if not wmw.worker.serving:
                wmw.worker.start()
            self.transport.send(wmw.route_id, client, msg)
        except RPCError as exc:
            self.logger.exception(exc)
            response = self.protocol.exp_error_response(-1, exc)
            self.server.transport.send(client, response.serialize())

    def _make_method_dict(self, service, m_name):
        met = getattr(service, m_name)
        method_dict = {'__doc__': inspect.getdoc(met)}
        method_dict['params'] = []
        sig = inspect.signature(met)
        for name, param in sig.parameters.items():
            if name == 'self':
                continue
            method_dict['params'].append(param)
        method_dict = json_extend_encode(method_dict)
        return method_dict

    def _make_property_dict(self, service, p_name):
        prop = getattr(service.__class__, p_name)
        prop_dict = {}
        for k in ['fget', 'fset', 'fdel', '__doc__']:
            v = getattr(prop, k)
            if v is not None:
                prop_dict[k] = v if k == '__doc__' else True
        return prop_dict

    def get_service_info(self, service_name):
        if service_name not in self.workers:
            raise KeyError(f"Service not found {service_name}")
        service = self.workers[service_name].worker.service
        info_dict = {'__doc__': inspect.getdoc(service)}
        info_dict['methods'] = {}

        for m in service.rpc_public_api:
            info_dict['methods'][m] = self._make_method_dict(service, m)

        if hasattr(service, 'rpc_public_property'):
            info_dict['__rpc_properties__'] = {}
            for p in service.rpc_public_property:
                info_dict['__rpc_properties__'][p] = self._make_property_dict(service, p)

        if hasattr(service, 'rpc_data_path_open'):
            for m in service.rpc_data_path_open:
                method_dict = info_dict['methods'][m]
                method_dict[datarpc.DATA_PATH] = True

        if isinstance(service, EventSource):
            info_dict['events'] = service.rpc_events
        return info_dict

    def shut_down(self, timeout=0):
        for name, worker in self.workers.items():
            worker.worker.quit()

        if timeout > 0:
            start_time = time.time()
            self.logger.info('====checking if all workers stopped')
            workers_alive = list(self.workers.keys())
            while len(workers_alive) > 0:
                for service_id in workers_alive:
                    self.logger.debug(f'trying to shut_down {service_id}')
                    worker = self.workers[service_id].worker
                    if worker.is_alive():
                        worker.join(0.5)
                    else:
                        workers_alive.remove(service_id)
                        break   # restart the loop afer we changed the loop condition
                if (time.time() - start_time) > timeout:
                    self.logger.info('timed out shutting down workers')
                    break

            for name in workers_alive:
                self.logger.error(f'unable to stop worker {name} during server shut_down')
                '''
                ww: I dont' think it's a good idea to kill the thread here. No way for
                the server to know the consequences of killing a thread in an arbitrary
                service. Better to let the author of the service know something's wrong
                and have them fix it.
                '''

        if not self.transport.socket.closed:
            while True:
                try:
                    w_route, client, msg = self.transport.recv(zmq.NOBLOCK)
                    if client != b'0':
                        self.client_transport.send(client, msg)
                except zmq.error.Again:
                    self.logger.info('all results forwarded by worker manager')
                    break
            self.transport.shut_down()
