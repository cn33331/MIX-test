from ..protocols import DataStreamProtocol, DataEvent
from ..transports import DSProxyTransport, RPCTransportTimeout
from ..util import constants
# from ..util.constants import constants

from mix.tools.util.logfactory import create_null_logger
from mix.tools.util.misc import cmt
import inspect


class DataStreamProxy(object):
    '''the proxy of a datastream on the server side'''

    # timeout for each chunk of data in milliseconds
    write_chunk_timeout = constants.DS_WRITE_CHUNK_TIMEOUT_MS
    read_chunk_timeout = constants.DS_READ_CHUNK_TIMEOUT_MS

    '''
    The fall back timeout is not supposed to be an application layer timeout.
    It's really fallback for when something is wrong with the physical connection,
    hence it's so long. The unit is milisecond.
    '''
    fallback_timeout = constants.ZMQ_DEFAULT_TIMEOUT_MS

    def __init__(self, transport, protocol, identity=None):
        self.transport = transport
        self.protocol = protocol
        self.logger = create_null_logger()
        self.transport.send(self.protocol.encode(
            DataEvent.HELLO, transport.end_point))
        msg = self.transport.recv(timeout_ms=constants.DS_OPEN_TIMEOUT_MS)
        if msg is None:
            raise RPCTransportTimeout(
                'DataStream proxy can not establish communication with server')
        event, event_data = self.protocol.decode(msg)
        assert event == DataEvent.OLLEH
        assert event_data is not None
        self.identity = identity or f'{event_data}'
        # we are not checking version here, because version should've been checked
        # by the DataStreamOpen proxy method

    def __enter__(self):
        self.logger.debug('entered DataStreamProxy context manager')
        return self

    def __exit__(self, exc_ty, exc_val, tb):
        if exc_val is not None:
            self.logger.exception(exc_val)
        self.logger.debug('exit DataStreamProxy context manager')
        self.close()

    def _check_timeout(self, start_time, timeout_ms):
        elapsed_time = cmt() - start_time
        self.logger.debug(f'checking e:{elapsed_time}, o:{timeout_ms}')
        if elapsed_time > timeout_ms:
            raise RuntimeError(f'in {self.identity} operation {inspect.stack()[1].function} has timed out')

    def write(self, data, timeout_ms=None):
        _timeout = timeout_ms or self.fallback_timeout
        self.transport.drain()
        start_time = cmt()

        chunk_size = self.protocol.chunk_size
        data_size = len(data)
        offset = 0
        self.transport.send(self.protocol.encode(
            DataEvent.WRITE), self.write_chunk_timeout)
        self.logger.debug('started write')
        while offset < data_size:
            self._check_timeout(start_time, _timeout)
            msg = self.transport.recv(timeout_ms=self.read_chunk_timeout)
            if msg is None:
                continue  # didn't get anything from server
            event, event_data = self.protocol.decode(msg)
            self.logger.info('got event {0}'.format(event.name))
            if event == DataEvent.ERROR:
                raise RuntimeError(
                    'error writing the data stream: {0}'.format(str(event_data)))
            if event == DataEvent.READ_CREDIT:
                end = min(offset + chunk_size, data_size)
                write_data = data[offset:end]
                self.transport.send(self.protocol.encode(
                    DataEvent.DATA, write_data), self.write_chunk_timeout)
                self.logger.info(f'sent data range [{offset} : {end}]')
                if end == data_size:
                    self.logger.info(f'sending EOF : {data_size}, {end}]')
                    self.transport.send(self.protocol.encode(
                        DataEvent.EOF), self.write_chunk_timeout)
                    break
                else:
                    offset = end

        self.logger.debug('finished write, waiting for ackonwledgement')
        event = DataEvent.READ_CREDIT  # flush out all the extra read credits
        while event == DataEvent.READ_CREDIT:
            self._check_timeout(start_time, _timeout)
            msg = self.transport.recv(self.read_chunk_timeout)
            if msg is None:
                continue
            event, data = self.protocol.decode(msg)
        if event != DataEvent.HAND_SHAKE:
            raise RuntimeError(f'unexpected event at the end of write: '
                               f'{event.name.lower()}, {data}')
        self.logger.debug('got acknowledgement')

    def read(self, data_size=0, timeout_ms=constants.DS_PROXY_READ_TIMEOUT_MS_DEFAULT):
        """
        Read data from stream

        Args:
            data_size: int, number of elements to read.  0 and negative value behavior
                            is dependent on the concrete Service's implementation.
            timeout_ms  - int,  timeout in milliseconds
        Returns:
            list of data elements.
        """

        proxy_timeout_ms_buffer = constants.DS_PROXY_READ_TIMEOUT_MS_BUFFER
        proxy_timeout_ms = timeout_ms + proxy_timeout_ms_buffer
        start_time = cmt()
        credit = self.protocol.pipe_line
        read_data = []

        self.transport.drain()

        self.logger.debug(f'started read {data_size}  timeout {timeout_ms}')
        self.transport.send(self.protocol.encode(DataEvent.READ, (data_size, (timeout_ms/1000.0))), self.write_chunk_timeout)

        # send a bunch or credit in the begining
        while credit:
            self.transport.send(self.protocol.encode(DataEvent.READ_CREDIT), self.write_chunk_timeout)
            credit -= 1

        while True:
            self._check_timeout(start_time, proxy_timeout_ms)
            msg = self.transport.recv(self.read_chunk_timeout)
            if msg is None:
                continue
            event, data = self.protocol.decode(msg)
            self.logger.info(f'got event {event.name.lower()}')
            self.logger.debug(f'data is {data}')
            if event == DataEvent.READ_CREDIT:
                # spurious READ_CREDIT, read again
                continue
            if event == DataEvent.ERROR:
                raise RuntimeError(
                    'error reading data stream: {0}'.format(data))
            if event == DataEvent.EOF:
                break
            assert event == DataEvent.DATA
            assert data is not None
            read_data.extend(data)
            # we do not keep track of the data. The server side will send EOF when all the data are sent
            self.transport.send(self.protocol.encode(DataEvent.READ_CREDIT), self.write_chunk_timeout)

        self.logger.debug('finished read')
        return read_data

    def close(self, timeout_ms=2000):
        self.logger.debug(f"closing the stream, time out is {timeout_ms}milliseconds")
        self.transport.drain()
        start_time = cmt()
        self.transport.send(self.protocol.encode(DataEvent.CLOSE), self.write_chunk_timeout)

        self.logger.debug('sent close message, waiting for ackonwledgement')
        event = DataEvent.ERROR
        try:
            while event != DataEvent.HAND_SHAKE:
                self._check_timeout(start_time, timeout_ms)
                # there may be spurious result from aborted actions
                msg = self.transport.recv(self.read_chunk_timeout)
                if msg is None:
                    self.logger.warning('WARNING: dsproxy did not get acknwledgement for closing')
                    continue
                event, data = self.protocol.decode(msg)
            self.logger.debug('got acknowledgement')
        except RuntimeError as e:
            self.logger.exception(e)
        finally:
            self.transport.shut_down()  # we need to shut down even if we don't get acknowledgement

    @classmethod
    def ZmqDealerDataStreamProxy(cls, ip, port, format_str, identity=None):
        end_point = "tcp://{0}:{1}".format(ip, port)
        transport = DSProxyTransport(end_point)
        meta_data = DataStreamProtocol.make_meta(format_str)
        protocol = DataStreamProtocol(meta_data)
        return cls(transport, protocol, identity)

    DefaultProxy = ZmqDealerDataStreamProxy
