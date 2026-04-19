from ..util import constants
# from ..util.constants import constants
from .zmqtransport import ZMQTransport
from .transport_error import RPCTransportTimeout

import zmq
import logging

'''
When a DEALER socekt binds, the sndtimeo and rcvtimeo socket option has effect,
when a DEALER socket connects, the sndtimeo and rcvtimeo socket option seem to have no effect
And a ROUTER socket binds, the sndtimeo and rcvtimeo socket option seem to have no effect
'''


class DSServiceTransport(ZMQTransport):
    '''
    The transport for DataStream Service side
    '''

    SEND_TIMEOUT_MS = 5000

    def __init__(self, end_point, ctx=None,
                 read_timeout=constants.DS_READ_CHUNK_TIMEOUT_MS,
                 write_timeout=SEND_TIMEOUT_MS):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.DEALER)
        self.socket.sndtimeo = write_timeout
        self.socket.rcvtimeo = read_timeout
        try:
            self.socket.bind(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)

    def send(self, data: bytes):
        try:
            self.socket.send(data, copy=False)
            if self.logger.getEffectiveLevel() <= logging.DEBUG:
                self.logger.debug(f'sent data {data}')
        except zmq.Again as e:
            raise RPCTransportTimeout(f'DSService send timeout @{self.end_point} ') from e

    def recv(self) -> bytes:
        try:
            data = self.socket.recv()
            if self.logger.getEffectiveLevel() <= logging.DEBUG:
                self.logger.debug(f'received data {data}')
            return data
        except zmq.Again as e:
            raise RPCTransportTimeout(f'DSService recv timeout @{self.end_point}') from e


class DSProxyTransport(ZMQTransport):
    '''
    The transport for DataStream Proxy side
    '''
    def __init__(self, end_point, ctx=None,
                 read_timeout=constants.DS_READ_CHUNK_TIMEOUT_MS,
                 write_timeout=constants.DS_WRITE_CHUNK_TIMEOUT_MS):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.DEALER)
        self.send_timeout = write_timeout
        self.recv_timeout = read_timeout
        self.socket.sndtimeo = write_timeout
        self.socket.rcvtimeo = read_timeout
        self.socket.hwm = constants.DS_PIPE_LINE + 5    # there is some buffer above the pipe line
        try:
            self.socket.connect(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)

    def send(self, data: bytes, timeout_ms=None):
        '''
        the timeout has no effect if the socket has reached hwm, because socket.send
        will not return until the socket.sndtimeo at that point.
        '''
        _timeout = timeout_ms or self.send_timeout
        try:
            # once the zmq socket reaches hwm, this call will not return until socket.sendtimeo
            self.socket.send(data)

            if self.socket.poll(_timeout, zmq.POLLOUT):
                return
            else:
                raise RPCTransportTimeout(f"DSProxy send timeout @{self.end_point}")
        except zmq.Again as e:
            raise RPCTransportTimeout(f"DSProxy send timeout @{self.end_point}") from e

    def recv(self, timeout_ms=None) -> bytes:
        '''
        on the server side, we only receive when there is something to receive.
        However on the client side, we try to receive when the client code tell us to receive.
        A recv timeout may just be the server is not ready
        with the data. So we just log the timeout, and return None to let the application
        decide if it wants to wait.
        '''
        _timeout = timeout_ms or self.recv_timeout
        try:
            val = self.socket.poll(_timeout, zmq.POLLIN)
            if val:
                data = self.socket.recv()
                if self.logger.getEffectiveLevel() <= logging.DEBUG:
                    self.logger.debug(f'received data {data}')
                return data
            else:
                self.logger.info(f"DSProxy recv timeout @{self.end_point}")
                return None
        except zmq.Again as e:
            self.logger.info(f"DSProxy recv timeout @{self.end_point}")
            self.logger.exception(e)
            return None
