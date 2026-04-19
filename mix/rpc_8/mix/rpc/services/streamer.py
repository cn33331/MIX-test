from mix.rpc.protocols.datarpc import DataStreamProtocol

from abc import ABCMeta, abstractmethod


class DataStream(metaclass=ABCMeta):

    def __init__(self, format_str='c'):
        '''
        format_str is the same string used in struct.pack, by default everything is a raw byte
        '''
        self.meta_data = DataStreamProtocol.make_meta(format_str)

    @abstractmethod
    def close(self):
        '''
        it must be safe to call close multiple times
        '''
        pass

    def read(self, size=0, timeout=0):
        '''
        if you want to read until end, the size must
        be set to 0.
        '''
        raise NotImplementedError

    def write(self, data, timeout=0):
        '''
        for streamer, the only data type supported are bytes
        so write can only write bytes, and read only return bytes
        '''
        raise NotImplementedError

    def flush(self):
        '''
        This asks the underling stream to finish writing all data in the
        buffer.
        '''
        pass
