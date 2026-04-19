from .dispatcher import Dispatcher
from ..transports import ZMQClientTransport
from ..services.eventobjects import EventListener
from ..util import constants
from .requesthandler import RequestHandlerMixin
from ..protocols import JSONRPCProtocol

import time


class EventListenerProxy(EventListener):
    '''
    proxy for an event listener on the client side
    '''
    def __init__(self, event_server_ep):
        self.transport = ZMQClientTransport(event_server_ep)
        self.protocol = JSONRPCProtocol()

    def notify(self, event_name, event_data):
        request = self.protocol.create_request('event_server', 'notify', event_data, None)
        self.transport.send(request.serialize())


class ClientProxy(object):
    '''
    represent a client connection
    '''
    def __init__(self, route_id, identity):
        self.route_id = route_id
        self.identity = identity
        self.last_update = time.time()
        self.event_listener = None
        self.event_sources = []

    def idle_too_long(self):
        t = time.time()
        return (t - self.last_update) > constants.CLIENT_DORMANT_MAX

    def release(self):
        '''
        release all resources held by this client.
        '''
        # todo remove all event listeners
        pass

    def __str__(self):
        return f'{self.identity}'

    def __repr__(self):
        return str(self)


class ClientManager(Dispatcher, RequestHandlerMixin):

    def __init__(self, server, worker_manager):
        # the dispatcher needs to know the server because some requrests will be
        # dispatched back to the server
        self.server = server
        self.transport = server.transport
        self.worker_man = worker_manager
        self.clients = {}
        self.protocol = JSONRPCProtocol()
        self.logger = server.logger.getChild('cman')

    @property
    def listening_socket(self):
        return self.transport.socket

    def dispatch(self):
        client, target, msg = self.transport.recv()
        # todo: need to protect against invalid request msg
        # request = self.protocol.parse_request(msg)
        # self.logger.info('incoming: {0}.{1}'.format(
        #    request.remote_id, request.method))
        service_id = target.decode('utf8')
        response = None
        if service_id == constants.MIX_CLIENT_MANAGER:
            response = self.handle_client_request(client, msg)
        elif service_id == '__server__':
            request = self.protocol.parse_request(msg)
            response = self.handle_request(request, self.server)
        else:
            if c_proxy := self.clients.get(client):
                c_proxy.last_update = time.time()
                self.worker_man.handle_request(client, service_id, msg)
            else:
                error_msg = f'unregistered client {client}. This may be a spurious' \
                            'message from a prevous session'
                request = self.protocol.parse_request(msg)
                response = self.protocol.error_response(request.id,
                                                        constants.INVALID_REQUEST_ERROR,
                                                        error_msg)
        if response:
            self.transport.send(client, response.serialize())

    def handle_client_request(self, client_route, request_msg):
        '''
        for now there is less error checking because none of these
        requests come from application code
        '''
        response = None
        request = self.protocol.parse_request(request_msg)
        if request.method == constants.MIX_CLIENT_HELLO:
            identity = request.args[0]
            self.clients[client_route] = ClientProxy(client_route, identity)
            response = self.protocol.create_response(request.id, self.server.session_id)
            self.logger.info(f'new client {identity} appeared')
            self.purge()    # we purge old clients every time we get a new clients
        elif request.method == constants.MIX_CLIENT_BYE:
            client_proxy = self.clients[client_route]
            client_proxy.release()
            self.clients.pop(client_route)
            self.logger.info(f'client {client_proxy.identity} says bye')
            # the client is not expecting a response
        else:
            error_msg = f'invalid reqeust to client manager: {request.method}'
            response = self.protocol.error_response(request.id,
                                                    constants.INVALID_REQUEST_ERROR,
                                                    error_msg)
        return response

    def purge(self):
        purge_list = set()
        for client in self.clients.values():
            if client.idle_too_long():
                purge_list.add(client)
                self.logger.info(f"client {client.identity} is dormant too long")
        for c in purge_list:
            c.release()
            self.clients.pop(c.route_id)
