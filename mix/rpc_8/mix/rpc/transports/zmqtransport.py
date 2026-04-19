from ..util import constants
# from ..util.constants import constants
from ..rpc_error import RPCError
from .transport_error import RPCTransportTimeout, RPCTransportError
from mix.tools.util.logfactory import create_null_logger

import zmq
from zmq.error import ZMQError
from abc import ABCMeta
import threading
import logging


class ZMQTransport(metaclass=ABCMeta):

    def __init__(self, ctx):
        '''
        zmq socket is not thread safe. Transport does not guarantee
        thread safety but it carries a lock. The client can acquire the
        lock if they choose to
        '''
        self.ctx = ctx or zmq.Context().instance()
        self.lock = threading.Lock()
        self.socket = None
        self.logger = create_null_logger()

    def __del__(self):
        self.shut_down()
        if self.lock.locked():
            self.lock.release()

    @staticmethod
    def parse_protocol(end_point):
        protocol, addr = end_point.split("://")
        return protocol, addr

    @staticmethod
    def parse_ip_port(ip_addr):
        return int(ip_addr.split(":")[-1])

    @property
    def end_point(self):
        ep = ''
        if self.socket is None:
            raise RPCTransportError('Socket is None')
        if self.socket.closed:
            raise RPCTransportError('socket is closed')

        try:
            ep = self.socket.LAST_ENDPOINT
        except ZMQError as e:
            raise self.wrap_zmq_error(e, 'error')
        else:
            return ep.decode('utf8')

    def drain(self):
        # disgard all the messages buffered by zmq
        while True:
            try:
                self.socket.recv(zmq.NOBLOCK)
            except zmq.ZMQError:
                break

    def wrap_zmq_error(self, exc: zmq.error.ZMQError, end_point, extra='') -> RPCError:
        msg = 'ZMQ error happend, end_point is {0}; {1}\n'.format(
            end_point, extra)
        raise RPCError(msg) from exc

    def shut_down(self, linger=0):  # unit of linger is miliseconds
        if not self.socket.closed:
            self.socket.close(linger=linger)


class ZMQClientTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None,
                 timeout_ms=constants.ZMQ_DEFAULT_TIMEOUT_MS,
                 send_timeout=constants.ZMQ_SEND_TIMEOUT_MS):
        '''
        timeout_ms is the time in milisecond to wait for a server reply. Because the server
        action could legitimately take a long time to complete, this timeout should be long enough
        not to set an arbitrary limit on how long the server action can take. Default is 100 seconds.
        send_timeout is time in miliseconds how long zmq tries to send. This should be hit quickly when there
        is a network problem. Default is 300 miliseconds
        '''
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.DEALER)
        self.send_timeout = send_timeout
        self.config_send()
        try:
            self.socket.connect(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)
        self.timeout = timeout_ms
        self.fallback_timeout = constants.ZMQ_DEFAULT_TIMEOUT_MS

    def config_send(self, hwm=1):
        '''
        this function must be called before connect/bind is called on the socket
        before the socket reaches the high water mark, if you poll for zmq.POLLOUT,
        it returns right away because (I think) as long as ZMQ places it on the outgoing
        queue, the message is as good as send for a messaging API. So in order to timeout on
        the POLLOUT event, you have to set high water mark to 1.
        '''
        self.socket.sndhwm = hwm
        # if the zmq socket has reached high water mark,
        # the socket.send function will timeout with this value
        self.socket.sndtimeo = self.send_timeout

    def send_and_recv(self, target: bytes, msg: bytes, timeout_ms=None) -> bytes:
        # msg has to be bytes, so pyzmq can use memory view
        try:
            self.socket.send_multipart([target, msg])
            timeout = timeout_ms or self.fallback_timeout
            if self.socket.poll(timeout, zmq.POLLIN):
                return self.socket.recv()
            else:
                raise RPCTransportTimeout(
                      'Time out in ZMQClientTransport, end_point is {0}'.format(self.end_point))
        except zmq.error.ZMQError as exc:
            raise RPCError() from exc

    def send(self, target: bytes, msg: bytes):
        try:
            # once the zmq socket reaches hwm, this call will not return until socket.sendtimeo
            self.socket.send_multipart([target, msg])
        except zmq.Again as e:
            raise RPCTransportTimeout(f"zmq.Again error sending to endpoint {self.end_point}") from e

    def recv(self, timeout_ms=None) -> bytes:
        timeout = timeout_ms or self.timeout
        try:
            if self.socket.poll(timeout, zmq.POLLIN):
                return self.socket.recv()
            else:
                # unlike in the send_and_recv case, receving nothing is not
                # necessarily an error
                return None
        except zmq.error.ZMQError as exc:
            raise RPCError() from exc


class ZMQServerTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None, timeout_ms=constants.ZMQ_DEFAULT_TIMEOUT_MS):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.ROUTER)
        self.socket.rcvtimeo = timeout_ms
        try:
            self.socket.bind(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)
        self.identity = end_point  # by default use the end point as the identity

    def recv(self) -> (bytes, bytes, bytes):
        '''
        return three values: route_id, remote_target, and message.
        If didn't recive a message in poll_interval miliseocnds,
        returns -1, None
        '''
        # what we get is bytes. to deocde to string, msg.decode('utf8')
        msg = self.socket.recv_multipart()
        self.logger.debug(f'from {msg[0]} got {msg[2]} for {msg[1]}')
        return msg[0], msg[1], msg[2]

    def send(self, dest, msg: bytes):
        self.logger.debug('to {0} send {1}'.format(dest, msg))
        # msg has to be bytes
        self.socket.send_multipart([dest, msg], copy=False)


class ZMQPairTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None, binding=False, timeout_ms=constants.ZMQ_DEFAULT_TIMEOUT_MS):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.PAIR)
        try:
            if binding:
                self.socket.bind(end_point)
            else:
                self.socket.connect(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)
        self.time_out = timeout_ms

    def send(self, data: bytes, timeout_ms=None):
        time_out = timeout_ms or self.time_out
        if self.socket.poll(time_out, zmq.POLLOUT):
            self.socket.send(data, copy=False)
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f'sent data {data}')
        else:
            raise RPCTransportTimeout('timeout sending data in pair socket')

    def recv(self, timeout_ms=0) -> bytes:
        time_out = timeout_ms or self.time_out
        if self.socket.poll(time_out, zmq.POLLIN):
            data = self.socket.recv()
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f'received data {data}')
            return data
        else:
            return None


class ZMQConsumerTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None, timeout_ms=constants.ZMQ_DEFAULT_TIMEOUT_MS):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.PULL)
        try:
            self.socket.connect(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)
        self.time_out = timeout_ms

    def consume(self):
        if self.socket.poll(self.time_out, zmq.POLLIN):
            return self.socket.recv()
        else:
            return None


class ZMQProducerTransport(ZMQTransport):
    def __init__(self, end_point, ctx=None):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.PUSH)
        try:
            self.socket.bind(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)

    def produce(self, data):
        self.socket.send(data, copy=False)
