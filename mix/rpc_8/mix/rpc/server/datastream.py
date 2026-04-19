from mix.tools.util.excreport import get_exc_desc
from mix.tools.util.logfactory import create_null_logger
from mix.tools.util.misc import short_id
from ..protocols import DataEvent, DataStreamProtocol
from ..transports import DSServiceTransport, RPCTransportTimeout
from ..util import constants
# from ..util.constants import constants
from threading import Thread
import zmq
from functools import wraps
import time

class DSStateResetError(RuntimeError):
    pass


def reset_upon_error(func):
    @wraps(func)
    def wrapped(self, dss, data=None):
        try:
            func(self, dss, data)
        except RPCTransportTimeout as exc:
            dss.logger.exception(exc)
            # if the connection is lost, we should break out of the loop
            return True
        except Exception as exc:
            dss.logger.error(f'unknown exception when calling {func}')
            dss._send_error(get_exc_desc(exc))
            raise DSStateResetError from exc
    return wrapped


class DSState(object):
    '''
    DataStream Service state machine
    Follow the design pattern at:
    https://learning.oreilly.com/library/view/python-cookbook-3rd/
    9781449357337/ch08.html#_implementing_stateful_objects_or_state_machines
    state: init
        event: hello; event_data: remote end_point
            action: reply with olleh.
            next state: ready
        Other:
            action: return error message
            next state: init
    state:ready
        event:read
            action: reset read state variables
            next state: reading
        event: write
            action: send all the write_read credits
            next state: writing
        event: read_credit
            action: ignore. This must be a spurious credit left over from last time
    state: reading
        event: read_credit
            action: add to read credit, check if there are more data to read
            next state: reading or ready
        event: read_next
            action: read next chunk of data, send back to the client.
                    reduce read credit.
                    check if there are more data to read
            next state: readding or ready
        event: EOF;
            action: client has gotten enough data. we are done reading, send back an EOF
                    event as handshake
            next state: ready
    state: writing
        event: data
            action: write data to stream object, send more write_read credit
            next state: writing
        event: EOF
            action: flush the stream, and send a hand shake signal back to the proxy to
                    signal write is done
            next state: ready

    In any state:
        event: close
            action: close the stream. If reading, finishe serving all the credit first.
                If wrting, flush the stream first. Also, send a hand shake back to the proxy
            next state: end
        event: error
            action: log error message. Raise Exception
    '''

    def new_state(self, new_state):
        self.__class__ = new_state
        self.aborted = False

    def _wrong_state(self, dss, ops):
        msg = f'{ops} is not a valid operation in current state: {self.__class__.__name__}'
        dss._send_error(msg)
        dss.logger.error(msg)

    def hello(self, dss, data=None):
        self._wrong_state(dss, 'hello')

    def read(self, dss, size):
        self._wrong_state(dss, 'read')

    def read_credit(self, dss, data=None):
        pass  # default action is ignore

    def write(self, dss, data=None):
        self._wrong_state(dss, 'write')

    def data(self, dss, data):
        self._wrong_state(dss, 'data')

    def eof(self, dss, data=None):
        self._wrong_state(dss, 'eof')

    def close(self, dss, data=None):
        dss.data_stream.close()
        dss.transport.send(dss.protocol.encode(DataEvent.HAND_SHAKE))
        self.new_state(DSStopState)
        return True

    def hand_shake(self, dss, data=None):
        dss.transport.send(dss.protocol.encode(DataEvent.HAND_SHAKE))

    def error(self, dss, msg):
        dss.logger.error(msg)
        self.new_state(DSReadyState)


class DSStopState(DSState):

    def close(self, dss, data=None):
        self._wrong_state(dss, 'close')

    def hand_shake(self, dss, data=None):
        self._wrong_state(dss, 'hand_shake')

    def error(self, dss, msg):
        self._wrong_state(dss, 'error')


class DSInitState(DSState):

    def __init__(self):
        '''this is the only state that is explicitly created'''
        self.aborted = False

    def hello(self, dss, data=None):
        dss.transport.send(dss.protocol.encode(DataEvent.OLLEH, dss.identity))
        self.new_state(DSReadyState)

    def error(self, dss, msg):
        dss.logger.error(msg)


class DSReadyState(DSState):

    def read(self, dss, data):
        size, timeout = data
        self.new_state(DSReadingState)
        self.init_read(dss, size, timeout)

    def write(self, dss, data=None):
        self.new_state(DSWritingState)
        self.init_write(dss)

    def eof(self, dss, data=None):
        pass


class DSWritingState(DSState):

    def init_write(self, dss):
        for i in range(dss.protocol.pipe_line):
            dss.transport.send(dss.protocol.encode(DataEvent.READ_CREDIT))

    @reset_upon_error
    def data(self, dss, data):
        dss.data_stream.write(data)
        dss.logger.debug(f'write data length is {len(data)}')
        dss.transport.send(dss.protocol.encode(DataEvent.READ_CREDIT))

    @reset_upon_error
    def eof(self, dss, data=None):
        dss.data_stream.flush()
        dss.logger.debug('finished flushing in write state')
        self.new_state(DSReadyState)
        dss.transport.send(dss.protocol.encode(DataEvent.HAND_SHAKE))


class DSReadingState(DSState):

    def init_read(self, dss, size, timeout):
        self.requested_size = size
        self.timeout = timeout
        if self.timeout is None:
            self.timeout = constants.ZMQ_DEFAULT_TIMEOUT_MS / 1000.0
        self.read_start_time = None
        if size == 0:
            self.left_to_send = dss.protocol.chunk_size
        else:
            self.left_to_send = size

    def _cal_should_read_size(self, dss):
        if self.requested_size == 0:
            return dss.protocol.chunk_size
        else:
            return min(dss.protocol.chunk_size, self.left_to_send)

    def _cal_read_size(self, read_data):
        if read_data is None:
            return 0
        else:
            return len(read_data)

    def _should_continue(self, should_read_size, read_size):
        if self.requested_size == 0:
            return read_size == should_read_size
        else:
            self.left_to_send -= read_size
            return self.left_to_send > 0 and read_size == should_read_size

    def _cal_read_timeout(self):
        '''
        Client provides a timeout for the entire read transaction, but at the state-machine level,
        hardware read() is done during multiple DataEvent.READ_CREDIT.  Hence, the timeout should
        span between the first read_credit() to the last.
        '''
        if self.read_start_time is None:
            self.read_start_time = time.time()
            return self.timeout
        else:
            elapsed = time.time() - self.read_start_time
            timeout = self.timeout - elapsed
            return timeout if timeout > 0 else 0

    def _done_reading(self, dss):
        dss.logger.debug('---Done reading----')
        self.new_state(DSReadyState)
        dss.transport.send(dss.protocol.encode(DataEvent.EOF))

    @reset_upon_error
    def read_credit(self, dss, data=None):
        should_read_size = self._cal_should_read_size(dss)

        timeout = self._cal_read_timeout()

        read_data = dss.data_stream.read(should_read_size, timeout)
        read_size = self._cal_read_size(read_data)
        dss.logger.debug(f'should:{should_read_size}; read:{read_size}')
        dss.transport.send(dss.protocol.encode(DataEvent.DATA, read_data))

        if not self._should_continue(should_read_size, read_size):
            self._done_reading(dss)
            return
        
        if timeout == 0:
            self._done_reading(dss)
            return


class DataStreamService(Thread):
    '''
    this class wraps a data stream object and present a service on a network endpoint
    '''

    poll_timeout = constants.DATA_STREAM_DORMANT_MAX  # default to 20 minutes

    def __init__(self, data_stream, worker, id='DS', ctx=None):
        super().__init__()
        self.identity = f'{id}_{short_id()}'
        self.data_stream = data_stream
        # this is the service worker for the service tha spawns this data stream
        # we need to update the data stream count for this worker
        self.worker = worker
        self.protocol = DataStreamProtocol(meta_data=data_stream.meta_data)
        self.logger = create_null_logger()
        self.poller = zmq.Poller()

        self.setup_comm(ctx)
        self.state = DSInitState()
        self.running = False

    def setup_comm(self, ctx):
        # set up communication with DataStreamProxy on the client side
        self.transport = DSServiceTransport('tcp://*:*', ctx=ctx)
        prot, addr = self.transport.parse_protocol(self.transport.end_point)
        self.port = self.transport.parse_ip_port(addr)

        # set up communication with worker
        control_ep = f'inproc://{self.identity}_DS_{short_id(8)}'
        ctx = ctx or zmq.Context().instance()
        self.control_sock = ctx.socket(zmq.PAIR)
        self.control_sock.bind(control_ep)
        self.control_pipe = ctx.socket(zmq.PAIR)
        self.control_pipe.connect(control_ep)

    def _send_error(self, error_msg):
        self.transport.send(self.protocol.encode(DataEvent.ERROR, error_msg))
        self.logger.error(error_msg)

    def _handle_request(self):
        '''
        if True is returned from this function, the DataStreamService
        main loop will be stopped
        '''
        try:
            msg = self.transport.recv()
            if msg is None:
                # this is an exception because the poller told us there is somethign to receive
                raise RPCTransportTimeout(
                    'timeout trying to receive from DataStream')
            event, data = self.protocol.decode(msg)
            event_name = event.name.lower()
            self.logger.info(f'received event {event_name}')
            event_handler = getattr(self.state, event_name, None)
            if event_handler is None:
                self._send_error(f'no handler for event {event_name}')
            return event_handler(self, data)
        except ValueError as exc:
            error_msg = 'Value error in handle_request, probably invalid event. '
            error_msg += get_exc_desc(exc)
            self._send_error(error_msg)
        except DSStateResetError as exc:
            self.logger.info(f'got state reset error in {self.identity}')
            self.logger.exception(exc)
            self.state.new_state(DSReadyState)
        except RPCTransportTimeout as exc:
            self.logger.error(f'DataStream Timeout: {get_exc_desc(exc)}')
            return True

    def _handle_control_request(self):
        msg = self.control_sock.recv()
        if msg == b'close':
            self.logger.info('worker told us to close')
            return True

    def run(self):
        self.running = True
        self.poller.register(self.transport.socket, zmq.POLLIN)
        self.poller.register(self.control_sock, zmq.POLLIN)
        self.logger.info(f'{self.identity} start serving...')
        while self.running:
            try:
                self.logger.debug(f'waiting for next request in {self.state.__class__}')
                socks = dict(self.poller.poll(self.poll_timeout))
                if self.transport.socket in socks:
                    if self._handle_request():
                        self.logger.info("closing per client request or connection lost")
                        # we don't call remove_dss if the closing request comes from the
                        # worker.
                        self.worker.remove_dss(self)
                        break
                elif self.control_sock in socks:
                    if self._handle_control_request():
                        break
                else:  # we have timed out
                    msg = f'No communication from client for {self.poll_timeout/1000} seconds'
                    self.logger.info(f'stopping the DataStream serivce. {msg}')
                    self.worker.remove_dss(self)
                    break
            except zmq.error.ZMQError as e:
                self.logger.info(
                    'Got ZMQError, are you trying to shutdown the data stream service?')
                self.logger.exception(e)
                self.worker.remove_dss(self)
                break
            except Exception as e:
                self.logger.error(
                    'Unexpected error in the data stream main loop')
                self.logger.exception(e)
                self.worker.remove_dss(self)
                break
        self.shut_down()

    def shut_down(self):
        self.running = False
        self.data_stream.close()
        self.transport.shut_down()
        self.state.new_state(DSStopState)
        if not self.control_sock.closed:
            self.control_sock.close(linger=0)
        if not self.control_pipe.closed:
            self.control_pipe.close(linger=0)

    def quit(self):
        if self.running:
            self.control_pipe.send(b'close')
