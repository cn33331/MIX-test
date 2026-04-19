from ..util import constants
import zmq
from ..transports import RPCTransportTimeout
import time

class RPCClient(object):
    '''
    the stub for making an rpc call, it turns a function call into a request, shielding
    the applicatoin layer from the implmentation of the protocol layer and transport layer.
    This woulc be the entry point for a non-dynamic language.

    Example:
    stub = RPCClient(transport, protocol)
    stub(remote_obj_id, remote_method_name, pos_arg1, pos_arg2, kwarg1=val1, kwarg2=val2)
    stub.close()
    '''

    def __init__(self, transport, protocol):
        self.transport = transport
        self.protocol = protocol
        self.timeout = self.transport.timeout

    def __call__(self, remote_object_id, method, *args, rpc_timeout=None, **kwargs):

        if rpc_timeout is not None:
            timeout_ms = rpc_timeout * 1000    # convert to milliseconds
        else:
            timeout_ms = self.timeout          # transport timeout already in millisecond

        end_time = int(time.time() * 1000) + timeout_ms

        self.logger.info('calling {0}.{1} with {2}; {3}'.format(
            remote_object_id, method, args, kwargs))
        request = self.protocol.create_request(
            remote_object_id, method, args, kwargs)

        with self.transport.lock:

            self.transport.send(remote_object_id.encode('utf8'), request.serialize())

            while True:

                response_str = self.transport.recv(timeout_ms)                

                if response_str is not None:
                    response = self.protocol.parse_response(response_str)
                    
                    # Verify the respond is for this request.
                    if response.request_id == request.id:
                        return response.result
                    else:
                        self.logger.warning(f'Received respond {response}, but does not much our ' \
                                                'expected id {request.id}.')

                timeout_ms = end_time - int(time.time() * 1000)
                self.logger.debug(f'  timeout_ms remaining : {timeout_ms}')
                if timeout_ms <= 0:
                    self.logger.error(f'Timeout, no respond for request {request}')
                    raise RPCTransportTimeout(f'Timeout, no respond for request {request}')


    def say_bye_to_server(self):
        self.logger.info('sending bye message to server...')
        target = constants.MIX_CLIENT_MANAGER
        request = self.protocol.create_request(target, constants.MIX_CLIENT_BYE, None, None)
        with self.transport.lock:
            try:
                self.transport.send(target.encode('utf8'), request.serialize())
            except RPCTransportTimeout:
                self.logger.info('server is probably already down')
            except zmq.error.ZMQError:
                self.logger.info('Ignored ZMQError when saying bye. ')
        # we don't want for a response here. the server could have gone down already

    def __del__(self):
        self.close()

    def close(self):
        if self.transport:
            # give it some time for the bye message to go out
            self.transport.shut_down(linger=100)
            self.transport = None
