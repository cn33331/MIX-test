import multiprocessing
from collections import OrderedDict
import queue
import time


class InterProcessEvents(object):
    def __init__(self, inter_process_queue):
        self.events = OrderedDict()
        self.queue = inter_process_queue

    def __getitem__(self, name):
        return self.events[name]

    def __setitem__(self, name, e):
        self.events[name] = e

    def create(self, name):
        self.events[name] = multiprocessing.Event()

    def set(self, name):
        self.events[name].set()

    def wait_on(self, name, time_out):
        e = self.events[name]
        e.wait(time_out)
        if not e.is_set():
            error_msg = '!!!ERROR: timeout waiting for event {0}'.format(name)
            e = self._get_first_error_from_queue()
            if e is None:
                raise RuntimeError(error_msg)
            else:
                raise RuntimeError(error_msg) from e

    def items(self):
        for name, value in self.events.items():
            yield name, value

    def event_names(self):
        for name in self.events.keys():
            yield name

    def _get_first_error_from_queue(self):
        non_error_queue = queue.SimpleQueue()
        exc = []
        while not self.queue.empty():
            m = self.queue.get(False)
            if isinstance(m, Exception):
                exc.append(m)
            else:
                non_error_queue.put(m)

        while not non_error_queue.empty():
            val = non_error_queue.get(False)
            self.queue.put(val)

        # objects put on multiprocessing queue might not be available righ away
        # todo: consider using a queue created by a manager
        time.sleep(0.1)
        if len(exc) > 0:
            return exc[0]
        else:
            return None
