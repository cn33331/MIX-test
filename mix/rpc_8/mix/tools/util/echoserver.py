from threading import Thread
import zmq


class EchoServer(Thread):

    def __init__(self, transport):
        # we are really assuming a ZMQServerTransport here.
        # to make sure the run loop will wak up to check if it's
        # still serving, the transport should be setup
        # with a rcv timeout
        super(EchoServer, self).__init__()
        self.transport = transport
        self.serving = False

    def run(self):
        """
        This runs the echoserver and loops if it sends and receives anything
        but b'__quit'.
        """
        self.serving = True
        while self.serving:
            try:
                route_id, target, msg = self.transport.recv()
                if msg:
                    if msg == b'__quit':
                        break
                    self.transport.send(route_id, msg)
            except zmq.error.Again:
                # transport recv timeout.
                pass
        self.transport.shut_down()
