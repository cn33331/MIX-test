from ..services.eventobjects import EventListener
from ..transports import ZMQClientTransport
from ..protocols import JSONRPCProtocol
from ..rpc_error import RPCError


class EventProxy(EventListener):
    '''
    The event proxy on the server side to receive service events notifications
    on behalf of remote clients
    one event proxy for each (event_server, event_name) combination
    '''

    def __init__(self, service_worker, event_server_url, protocol=None):
        self.server_url = event_server_url
        self.service_worker = service_worker
        self.transport = ZMQClientTransport(event_server_url)
        self.protocol = protocol or JSONRPCProtocol()
        self.ref_count = 1

    def notify(self, event_name, event_data):
        request = self.protocol.create_request(
            '__server__', 'notify', [self.service_worker.id, event_name, event_data], None)
        with self.transport.lock:
            self.logger.info(f'sending notification of {event_name} for {self.service_worker.id}')
            try:
                response_str = self.transport.send_and_recv(request.serialize())
            except RPCError as exc:
                self.logger.info("not able to get a response from the remote listener in proxy for "
                                 f"{self.service_worker.id}")
                self.logger.exception(exc)
            else:
                response = self.protocol.parse_response(response_str)
                self.logger.info(f'done sending notification of {event_name} for {self.service_worker.id}')
                return response.result

    def inc_ref(self):
        self.ref_count += 1

    def dec_ref(self):
        self.ref_count -= 1
        if self.ref_count == 0:
            self.shut_down()

    def shut_down(self):
        '''
        getting a lock so we don't shut down the transport in the middle of
        sending notficiation
        '''
        with self.transport.lock:
            self.transport.shut_down()
