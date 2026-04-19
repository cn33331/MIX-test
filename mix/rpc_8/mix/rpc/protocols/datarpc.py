from enum import IntEnum
import struct

from ..util import constants
# from ..util.constants import constants

__MIX_DS_VERSION__ = constants.DS_VERSION


# default transfer parameter based on https://zguide.zeromq.org/docs/chapter7/#Transferring-Files
CHUNK_SIZE = constants.DS_CHUNK_SIZE
PIPE_LINE = constants.DS_PIPE_LINE
DATA_PATH = constants.DATA_PATH_MARKER


class DataEvent(IntEnum):
    # event value shoudl not be 0, code may be testing for event value
    READ_CREDIT = 1  # A read credit arrived
    READ_NEXT = 2  # read the next chunk of data
    WRITE = 3  # A write request arrive
    EOF = 4  # our peer is done
    DATA = 5  # data arrived
    CLOSE = 6  # we are asked to close the stream
    ERROR = 7  # error
    READ = 8  # Start a new read operation. Any read credit received
    HELLO = 9  # Initial message to establish connection between Proxy and Service
    OLLEH = 10  # reply to HELLLO
    HAND_SHAKE = 11  # outside of READ and EOF is not valid
    ABORT = 12  # abort the current operation. This is not implemented for now


class DataStreamProtocol(object):
    '''
    The data stream protocol.
    Each message contains two parts: event, data
    event is one byte. Valid event include:
    0: ; data are either size of data or 0, which means this is a read credit.
    1. write; data is the data size
    2: EOF; data are empty
    3: data_arrived; data are the data delivered
    4. close. Date will be empty
    5: Error; Data will be a JSONRPCResponse with error code
    '''

    @staticmethod
    def make_meta(packing='c'):
        '''make a meta data dictionary that describe the raw bytes
        packing must be a valid format string recognized by struct.pack
        '''
        meta_data = {'version': __MIX_DS_VERSION__,
                     'packing': packing,
                     'chunk_size': CHUNK_SIZE,
                     'pipe_line': PIPE_LINE,
                     }
        return meta_data

    def __init__(self, meta_data=None):
        # todo: this is a problem keeping the same version of both data
        self.meta_data = meta_data or self.make_meta()
        self.version = self.meta_data['version'].to_bytes(1, 'little')
        self.chunk_size = self.meta_data['chunk_size']
        self.pipe_line = self.meta_data['pipe_line']

    @property
    def format_str(self):
        return self.meta_data['packing']

    @format_str.setter
    def format_str(self, value):
        self.meta_data['packing'] = value

    def _encode_read_data(self, data):
        size, timeout = data
        size = int(size)
        return struct.pack('>id', size, timeout)

    def _decode_read_data(self, data):
        return struct.unpack('>id', data)
        
    def _encode_hello_data(self, data):
        if isinstance(data, str):
            return bytes(data, 'utf-8')
        else:   # assume we have bytes
            return data

    def _encode_olleh_data(self, data):
        if isinstance(data, str):
            return bytes(data, 'utf-8')
        else:   # assume we have bytes
            return data

    def _decode_hello_data(self, data):
        return str(data, 'utf-8')

    def _decode_olleh_data(self, data):
        return str(data, 'utf-8')

    def _encode_data_data(self, data):
        format_str = self.meta_data['packing']
        if format_str == 'c':
            return data
        else:
            pack_str = '>{0}{1}'.format(len(data), format_str)
            return struct.pack(pack_str, *data)

    def _decode_data_data(self, data):
        format_str = self.meta_data['packing']
        if format_str == 'c':
            return data
        else:
            byte_width = struct.calcsize(format_str)
            data_size = int(len(data) / byte_width)
            pack_str = '>{0}{1}'.format(data_size, format_str)
            return struct.unpack(pack_str, data)

    def _encode_error_data(self, data):
        assert isinstance(data, str)
        return bytes(data, 'utf-8')

    def _decode_error_data(self, data):
        return str(data, 'utf-8')

    def _encode_default(self, data):
        return bytes()

    def _decode_default(self, data):
        return None

    def encode(self, event: DataEvent, data=None) -> bytes:
        '''
        first byte is the protocol version, second byte is the event, rest are data
        '''
        byte_data = bytearray(self.version)
        byte_data.append(int(event))
        if data is None:
            return bytes(byte_data)
        else:
            encode_data_method = getattr(
                self, f'_encode_{event.name.lower()}_data', self._encode_default)
            byte_data.extend(encode_data_method(data))
            return bytes(byte_data)

    def decode(self, data: bytes):
        assert isinstance(data, bytes)
        assert data[0:1] == self.version  # check we have the right version
        try:
            event = DataEvent(data[1])
        except ValueError:
            raise RuntimeError(
                'the first byte "{0}" is not a valid event'.format(data[0]))

        decode_method_name = f'_decode_{event.name.lower()}_data'
        decode_method = getattr(self, decode_method_name, self._decode_default)
        return event, decode_method(data[2:])
