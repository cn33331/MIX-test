import threading


class BytesFifo(object):
    """
    there may be a way to build more efficient fifo in c with
    io.BytesIO like https://github.com/hbock/byte-fifo/blob/master/fifo.py
    """

    def __init__(self, size):
        self.capacity = size
        self.buffer = bytearray(size)
        self._lock = threading.Lock()

    def write(self, data):
        assert isinstance(data, (bytes, bytearray))
        with self._lock:
            data_size = len(data)
            if data_size >= self.capacity:
                # we can not hold everything. drop the left most bytes because
                # this is a fifo
                self.buffer = data[-self.capacity:]
            else:
                self.buffer.extend(data)
                if len(self.buffer) > self.capacity:
                    self.buffer = self.buffer[-self.capacity:]

    def read(self, size=0):
        with self._lock:
            if size == 0:
                size = len(self.buffer)
            else:
                size = min(size, len(self.buffer))
            data = self.buffer[:size]
            self.buffer = self.buffer[size:]
            return data

    def __len__(self):
        """
        this returns current how many elements are in the buffer
        to find out the capacity of the buffer you should read the capacity
        property
        """
        return len(self.buffer)

    def __str__(self):
        return str(self.buffer)
