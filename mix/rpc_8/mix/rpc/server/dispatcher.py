from abc import ABCMeta, abstractmethod


class Dispatcher(metaclass=ABCMeta):
    '''The interface definition for a class that can be registered
    with the main loop's poller and handle POLLIN events detected by
    server
    '''

    @abstractmethod
    def dispatch(self):
        pass

    @property
    def listening_socket(self):
        return NotImplementedError()
