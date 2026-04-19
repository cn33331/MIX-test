# -*- coding: utf-8 -*-
from typing import Iterable
from mix.tools.util.logfactory import create_null_logger
from mix.rpc.services.streamer import DataStream
from mix.rpc.protocols import DataStreamProtocol
from ..util import constants
# from ..util.constants import constants
import threading
import uuid
import copy
import time
import weakref
from abc import ABCMeta, abstractmethod


class StreamFilter(metaclass=ABCMeta):
    @abstractmethod
    def filter(self, data : Iterable) -> Iterable:
        '''
        This is the worker method that will be called when data is given to the stream.

        Implement this as efficiently as possible!  Since this is called iteratvely on 
        the stream data, long slow function can slow down your stream performance.
        Consider:
        * Defer any setup operation to __init__().
        * Write separate StreamFilter subclass for different operations needed 
        for different streams.

        Args:
            data: bytearray or list, The raw stream data.

        Returns:
            bytearray or list, the iterable type should be the same as 'data' parameter.
        '''
        pass


class StreamService(object):
    '''
    Base class for drivers performing streaming
    
    Drivers should inherit from this class if they need basic streaming capabilities
    '''
    rpc_data_path_open = 'open_stream'

    streamservice_api = ['start_streaming', 'stop_streaming']

    class Stream(DataStream):
        '''
        A concrete implementation of DataStream, specific to StreamService
        '''

        def __init__(self, module, data_format, buffer_size=1024*30, buffer_drain_time=120):
            '''
            Stream object for user to read and write.

            :param module:      StreamService,        The actual Service class (subclass of StreamService) that owns this stream.
            :param buffer_size: int,    The number of elements the data queue can hold if read() is not called.  
                                        If more data is distributed to this stream and it's not read(), the buffer will be emptied.
            :param buffer_drain_time:  int, If read() is not called within this time, data will be emptied.  Unit in seconds.
            '''
            self.data_format = data_format
            self.meta_data = DataStreamProtocol.make_meta(self.data_format)
            self.module = module
            if self.data_format == 'c':
                self._data_queue = bytearray()
            else:
                self._data_queue = []
            self.buffer_size = buffer_size
            self.buffer_drain_time = buffer_drain_time
            self.last_read_time = time.time()
            self.data_filter = []

        def add_data_to_queue(self, new_data):

            if self.buffer_drain_time is not None:
                if time.time() - self.last_read_time > self.buffer_drain_time:
                    if len(self._data_queue):
                        self.module.logger.info(f'dumping data_queue {len(self._data_queue)} due to timeout')
                        self._data_queue.clear()

            for f in self.data_filter:
                new_data = f.filter(new_data)                

            if self.data_format == 'c':
                self._data_queue.extend(new_data)
            else:
                self._data_queue += new_data
            if self.buffer_size > 0:
                self._data_queue = self._data_queue[-self.buffer_size:]

        def add_data_filter(self, filter):
            assert isinstance(filter, StreamFilter)
            self.data_filter.append(filter)

        @property
        def data_queue(self):
            return self._data_queue

        def close(self):
            '''
            DataStream override, closes the stream session
            '''
            self.module.close_stream(self)

        def read(self, size=-1, timeout=constants.STREAMSERVICE_DEFAULT_READTIMEOUT):
            '''
            DataStream override, perform a read of size
            
            Args:
                size: int, number of samples to return. Default of -1 returns all samples available in the stream
                      buffer. Note, this is different than samples in the hardware buffer.

            Returns:
                list or bytearray depending on stream type
            '''
            self.last_read_time = time.time()

            if size == -1:
                size = len(self.data_queue)

            if size == 0:
                if self.data_format == 'c':
                    return bytearray()
                else:
                    return []

            # if the queue has more data than the requested size, return it
            if len(self.data_queue) >= size:
                ret_data = self.data_queue[:size]
                del self.data_queue[:size]
                return ret_data

            if self.module.cv:
                with self.module.cv:
                    self.module.cv.wait(timeout)
            else:
                new_data = None
                with self.module.read_lock:
                    new_data = self.module.streaming_read(size, timeout)
                    if len(new_data) > 0:
                        self.module.distribute_read_data(new_data)

            if len(self.data_queue) > 0:
                ret_data = self.data_queue[:size]
                del self.data_queue[:size]
                return ret_data

            return []

        def write(self, data):
            '''
            DataStream Override, performs a write with data
            '''
            if (len(data) > 0):
                self.module.streaming_write(data)

        def flush(self):
            self.module.flush()
            self.module.logger.debug("streamservice executed flush")

    def __init__(self, max_streams=100, *args, **kwargs):
        '''
        StreamService           BaseClass to expose stream interfaces

        :param max_streams:     int,        The maximum number of streams can be created.  If caller attempt to create more then
                                            this number, Exception will be thrown.
        '''
        self.streams = weakref.WeakSet()
        self.read_lock = threading.Lock()
        self.distribution_lock = threading.Lock()
        self.logger = create_null_logger()
        self.cv = None
        self._max_streams = max_streams

    def __del__(self):
        self.streams.clear()

    def open_stream(self, data_format, id=None, config={}, autostart=True, buffer_size=1024*1024, buffer_drain_time=120):
        '''
        Opens a DataStream session
        
        Child implementations that choose to extend this method must call the parent open_stream using super().open_stream for proper initialization of StreamService

        :param data_format:     str,        Stream data packing format string
        :param id:              str,        a user provided identifier for the stream. Used with start/stop streaming methods. None by default.
        :param config:          any,        user provided configuration data. This data can be in any form, and is passed to the process_data
                                            method when any data for this stream is processed.
        :param autostart:       bool,       sets whether the stream should be 'started' when the stream is created
        Any other additional param needed by the driver

        Returns:
            A DataStream object
        '''
        if not id:
            if not autostart:
                raise RuntimeError("stream autostart can only be false if an id is provided")
            id = uuid.uuid4()  # still need unique ID
        with self.distribution_lock:
            for stream in self.streams:
                if stream.id == id:
                    raise RuntimeError("id '{}' is already in use".format(id))
        if len(self.streams) >= self._max_streams:
            raise RuntimeError(f'Cannot create more than {self._max_streams} streams, {len(self.streams)} streams currently open')
        stream = self.Stream(module=self, data_format=data_format, buffer_size=buffer_size, buffer_drain_time=buffer_drain_time)
        stream.id = id
        stream.config = config
        stream.active = autostart
        with self.distribution_lock:
            self.streams.add(stream)
        self.logger.info(f"streamservice stream '{id}' opened with autostart '{autostart}' and config of '{config}'. {len(self.streams)} streams open, max is {self._max_streams}")
        return stream

    def close_stream(self, stream):
        with self.distribution_lock:
            if stream in self.streams:
                self.streams.remove(stream)
                self.logger.info("streamservice stream '{}' closed".format(stream.id))

    def distribute_read_data(self, data):
        with self.distribution_lock:
            for stream in self.streams:
                if stream.active:
                    proc_data = copy.copy(data)
                    proc_data = self.process_data(proc_data, stream.config, stream.data_format)
                    stream.add_data_to_queue(proc_data)
                    self.logger.debug("streamservice stream '{}' distributed data with processing config '{}'".format(stream.id, stream.config))

    def start_streaming(self, stream_ids):
        '''
        Instructs the driver to start interacting with the specificed streams

        For input streams, the hardware would start placing data into the buffers.
        For output streams, the hardware would start reading data from the buffers.
        Buffers started at the same time that share the same resource are guarenteed to have their data time-aligned.
        For example, starting two input buffers together that point to the same channel would result in streams with
        identical data.

        Args:
            stream_list: list, a list of buffer ids to start

        Returns:
            None
        '''
        with self.distribution_lock:
            for stream in self.streams:
                if stream.id in stream_ids:
                    stream.active = True
                    self.logger.info("streamservice stream '{}' enabled for data transfer".format(stream.id))

    def stop_streaming(self, stream_ids):
        '''
        Instructs the driver to stop interacting with the specified streams

        For input streams, the hardware would stop placing data into the buffers.
        For output streams, the hardware would stop reading data from the buffers.

        Args:
            stream_list: list, a list of buffer ids to stop

        Returns:
            None
        '''
        with self.distribution_lock:
            for stream in self.streams:
                if stream.id in stream_ids:
                    stream.active = False
                    self.logger.info("streamservice stream '{}' disabled for data transfer".format(stream.id))

    def flush(self):
        '''
        Performs the desired actions when the DataStream flush is called

        This method should be overriden by the child class
        Examples of a flush would be ensuring all data in the buffer has been written to HW
        '''
        pass

    def streaming_read(self, size, timeout):
        '''
        Performs a read from the physical hardware device.

        Attempts to read the number of samples specificed by size, within the timeout.

        Args:
            size: int, the number of samples requested to be read.  0 and negative value's behavior is dependent on the
                        concrete Service's implementation.
            timeout: dbl, timeout in seconds for completing the read.

        Returns:
            Either a bytearray or a list. List should be used for any datatype other than bytes, which should use bytearray.
        '''
        raise NotImplementedError()

    def streaming_write(self, data):
        '''
        Performs a write to the physical hardware device.

        Args:
            data: bytearray or list, to be written to the hardware

        Returns:
            None
        '''
        raise NotImplementedError()

    def process_data(self, data, config, return_format):
        '''
        Processes the data read from self.read prior to placing it into the stream buffers
        
        By default this function does nothing to the data
        
        Args:
            data: bytearray or list, returned from self.read
            config: anything, set to the stream when open_stream was called
            return_format: str, format string provided as data_format in open_stream() specifying the required format of return data
        
        Returns:
            Either a bytearray or a list, should match data type of data
        '''
        return data

    def reset(self):
        '''
        Resets the service to initial state
        '''
        with self.distribution_lock:
            self.streams.clear()

class StreamServiceBuffered(StreamService):

    def __init__(self, thread_readsize=2048, thread_readtimeout=constants.STREAMSERVICE_DEFAULT_READTIMEOUT, *args, **kwargs):
        '''
        StreamServiceBuffered class adds a workloop to StreamService that continously read data
        into it's own internal buffer.  The workloop and buffer allows client side's stream.streaming_read()
        call to occur at a less strict interval, with lowered risk of saturating hw buffer.

        Args:
            thread_readsize: int, number of samples that the workloop should attempt to read each cycle. It is important to calculate this
                             value carefully, along with the thread_readtimeout, based on the expected data production of the hardware.
                             Sampling too few elements each iteration of the workloop will result in the workloop polling the hardware continuously
                             and using too much CPU time. However, setting the value too high will result in some latency between data acquisition
                             and data being placed into the stream buffers. However, when in doubt, use higher readsizes to reduce CPU loading.
            thread_readtimeout: dbl, timeout in seconds for the workloop to read the number of samples requested by thread_readsize.
            Other args and kwargs as needed by driver
        '''

        super().__init__(*args, **kwargs)
        self.readThread = None
        self.readThreadStop = False
        self.streams_mutex = threading.Lock()

        self.cv_mutex = threading.Lock()
        self.cv = threading.Condition(self.cv_mutex)

        self.thread_readtimeout = thread_readtimeout
        self.thread_readsize = thread_readsize

    def open_stream(self, data_format, id=None, config={}, autostart=True):
        '''
        Opens a DataStream session.
        
        Args:
            data_format:  str, Stream data packing format string
        
        This is an extension of StreamService.open_stream, refer to that methods docstring for parameter and usage documentation. Calls the
        parent (StreamService) open_stream to initialize buffers, then starts the workoop if it does not exist yet.
        '''
        stream = None
        with self.streams_mutex:
            stream = super().open_stream(data_format=data_format, id=id, config=config, autostart=autostart)
            if self.readThread is None:
                self.pre_thread_launch()
                self.logger.info("streamservice pre_thread_launch executed")
                self.readThread = threading.Thread(target=self.readloop)
                self.readThreadStop = False
                self.readThread.start()
        return stream

    def close_stream(self, stream):
        with self.streams_mutex:
            super().close_stream(stream)
            if len(self.streams) == 0:
                self.stop_readloop()

    def stop_readloop(self):
        if self.readThread is not None:
            self.readThreadStop = True
            self.readThread.join(5)
            if self.readThread.is_alive():
                self.logger.critical("streamservice readthread for final stream '{}' did not die!".format(stream.id))
            self.readThread = None
            self.post_thread_shutdown()
            self.logger.info("streamservice post_thread_shutdown executed")

    def readloop(self):
        self.logger.info("streamservice readloop started")
        while not self.readThreadStop:
            data = self.streaming_read(self.thread_readsize, self.thread_readtimeout)
            if len(data) > 0:
                with self.cv:
                    self.distribute_read_data(data)
                    self.cv.notify()
            self.logger.debug("streamservice readloop attempted to read {} samples, actually read {} samples with "
                               "timeout of {}".format(self.thread_readsize, len(data), self.thread_readtimeout))
        self.logger.info("streamservice readloop stopped")

    def pre_thread_launch(self):
        '''
        Called immediately before the workloop thread is launched
        
        Perform any actions here that are necessary for initializing the hardware prior to data streaming. Examples
        could be resetting or clearing of a DMA or other hardware buffers, configuring hardware for continuous acquisiton, etc.
        
        Params:
            None
        
        Returns:
            None
        '''
        pass

    def post_thread_shutdown(self):
        '''
        Called immediately after the workloop thread is shut down
        
        Perform any actions here that are necessary when data is not longer needed from the hardware. Examples include
        stopping of any continuous acquisitions, resetting or clearing of a DMA or other hardware buffers, etc.
        
        Params:
            None
        
        Returns:
            None
        '''
        pass

    def reset(self):
        '''
        Resets the service to initial state
        '''
        with self.streams_mutex:
            self.stop_readloop()
        super(StreamServiceBuffered, self).reset()
