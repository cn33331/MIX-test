from ..transports.zmqtransport import ZMQServerTransport
from ..protocols.jsonrpc import JSONRPCResponse

from threading import Thread
from collections import defaultdict
import time
import zmq
from queue import SimpleQueue


class EventServer(Thread):
    '''the event server for a proxy factory'''

    POLLER_INTERVAL = 2  # polling interval is 2 miliseconds

    def __init__(self, id, proxy_factory):
        self.id = id
        self.transport = ZMQServerTransport(
            'tcp://127.0.0.1:*', poll_interval=self.POLLER_INTERVAL)
        super().__init__()
        self.pf = proxy_factory
        self.protocol = proxy_factory.stub.protocol
        self.listeners_map = defaultdict(set)
        self.serving = False
        self.response_queue = SimpleQueue()

    def register(self, event_name, proxy):
        self.logger.info(f'listening for {event_name} of {proxy.remote_obj_id}')
        self.listeners_map[(proxy.remote_obj_id, event_name)].add(proxy)

    def unregister(self, event_name, proxy):
        key = (proxy.remote_obj_id, event_name)
        if key in self.listeners_map:
            listeners = self.listeners_map[key]
            listeners.discard(proxy)
            if len(listeners) == 0:
                self.listeners_map.pop(key)

    def run(self):
        self.serving = True
        self.logger.info(f"starting event server {self.id}")
        self.last_time = time.time()
        while self.serving:
            try:
                client, msg = self.transport.recv()
                if msg:
                    dispatch_thread = Thread(
                        target=self.dispatch, args=(client, msg,))
                    dispatch_thread.setDaemon(True)
                    self.logger.debug('before starting dispatching thread')
                    dispatch_thread.start()
                if self.response_queue.qsize() > 0:
                    client, response = self.response_queue.get()
                    self.logger.info(
                        'responding: {0}'.format(response.summary()))
                    self.transport.send(client, response.serialize())
                    self.last_time = time.time()
                self.heart_beat()
            except zmq.ContextTerminated:
                # todo: this should really be ConnectionLost, so we can
                # decouple form ZMQ
                break
            except Exception as exc:
                self.logger.exception(exc)

    def dispatch(self, client, msg):
        request = self.protocol.parse_request(msg)
        remote_obj_id, event_name, event_data = request.args
        self.logger.info(f'got event {event_name} from {remote_obj_id}')
        listeners = self.listeners_map[(remote_obj_id, event_name)]
        results = []
        response = None
        for listener in listeners:
            try:
                result = listener.notify(event_name, event_data)
                results.extend(result)
            except Exception as e:
                extra_msg = f"error handling {event_name}"
                self.logger.exception(e)
                response = self.protocol.exp_error_response(
                    request.id, e, extra_msg)

        if response is None:
            '''
            response is still none, meaning no excpetion happened.
            '''
            response = JSONRPCResponse(request.id, results)

        self.response_queue.put([client, response])
        self.logger.debug(f'end dispatch, resposne size is {self.response_queue.qsize()}')

    def heart_beat(self):
        pass

    def shut_down(self):
        self.deregister_all()
        self.serving = False

    def deregister_all(self):
        for proxies in list(self.listeners_map.values()):
            for proxy in list(proxies):
                proxy.deregister_all()
