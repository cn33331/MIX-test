from ..util import constants
# from ..util.constants import constants
from mix.tools.util.logfactory import create_null_logger

import zmq
from abc import ABCMeta, abstractmethod
from urllib.parse import urlparse
import os


class PingTransportError(RuntimeError):
    pass


class PingClientTransport(metaclass=ABCMeta):

    @abstractmethod
    def ping(self, identity, addr, session_id):
        pass

    @abstractmethod
    def connect(self, endpoint):
        pass

    @abstractmethod
    def shut_down(self):
        pass


class PingServerTransport(metaclass=ABCMeta):

    @abstractmethod
    def bind(self, end_point):
        pass

    @abstractmethod
    def recv(self):
        '''
        recved results include:
        identity, addr, up_since
        returns None if no ping message received
        '''
        pass

    @abstractmethod
    def shut_down(self):
        pass


'''
below is ZMQ Router Dealer socket implementation of the ping transport.
but there could be a UDP version of this too.
'''


class ZMQPingClientTransport(PingClientTransport):

    HWM = 50
    SNDTIMEO = 20  # 20 milisecond timeout

    def __init__(self, ctx=None):
        self.ctx = ctx or zmq.Context.instance()
        self.socket = None
        self.logger = create_null_logger()

    def connect(self, end_point=constants.MAN_SERVER_PING_EP):
        self.end_point = end_point
        self.shut_down()
        self.socket = self.ctx.socket(zmq.DEALER)
        self.socket.hwm = self.HWM
        self.socket.sndtimeo = self.SNDTIMEO
        self.socket.connect(end_point)

    def ping(self, identity: str, addr: str, session_id: str):
        msg = [bytes(identity, 'utf8'), bytes(addr, 'utf8'),
               bytes(session_id, 'utf8')]
        try:
            self.socket.send_multipart(msg)
        except Exception:
            # we probably hit the high water mark
            self.logger.debug(f'ping client reconnecting...{session_id}')
            self.connect(self.end_point)

    def shut_down(self):
        if self.socket:
            if not self.socket.closed:
                self.socket.close(linger=0)


class ZMQPingServerTransport(PingServerTransport):

    def __init__(self, ctx=None):
        self.ctx = ctx or zmq.Context.instance()
        self.socket = self.ctx.socket(zmq.ROUTER)
        self.logger = create_null_logger()

    def bind(self, end_point=constants.MAN_SERVER_PING_EP):
        uri = urlparse(end_point)
        if uri.scheme == 'ipc':
            os.makedirs(os.path.dirname(uri.path), exist_ok=True)
        self.socket.bind(end_point)

    def recv(self):
        try:
            msgs = self.socket.recv_multipart(zmq.NOBLOCK)
            if len(msgs) != 4:
                error_msg = f'unexpected ping message received: f{msgs}'
                raise PingTransportError(error_msg)
            self.logger.debug(f'got msgs {msgs}')
            identity = msgs[1].decode('utf8')
            addr = msgs[2].decode('utf8')
            session_id = msgs[3].decode('utf8')
            return identity, addr, session_id
        except zmq.error.Again:
            self.logger.debug('not receving ping from any server')
            return None

    def shut_down(self):
        if self.socket:
            if not self.socket.closed:
                self.socket.close(linger=0)
