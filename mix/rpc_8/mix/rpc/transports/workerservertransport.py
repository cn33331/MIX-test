from .zmqtransport import ZMQTransport

import zmq


class ZMQWorkerTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.DEALER)
        try:
            self.socket.connect(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)

    def send(self, dest: bytes, msg: bytes):
        '''
        if you are using an inproc end point,
        the send will hang if it's not received on
        the other side
        '''
        self.socket.send_multipart([dest, msg], copy=False)

    def recv(self):
        '''return values are client_id and message'''
        msg = self.socket.recv_multipart()
        client = msg[0]
        rest = msg[1]
        return client, rest


class ZMQServerWorkerTransport(ZMQTransport):

    def __init__(self, end_point, ctx=None):
        super().__init__(ctx)
        self.socket = self.ctx.socket(zmq.ROUTER)
        try:
            self.socket.bind(end_point)
        except zmq.error.ZMQError as e:
            self.wrap_zmq_error(e, end_point)

    def send(self, worker_id, client, msg):
        self.socket.send_multipart([worker_id, client, msg], copy=False)

    def recv(self, flags=0):
        '''flags can be 0 or zmq.NOBLOCK'''
        msg = self.socket.recv_multipart(flags)
        return msg[0], msg[1], msg[2]
