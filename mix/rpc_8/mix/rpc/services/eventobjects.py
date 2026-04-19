from abc import ABCMeta, abstractmethod

REGISTER_CALL = '__MIX_EVENT_REGISTER__'
DEREGISTER_CALL = '__MIX_EVENT_LISTENER_REMOVE__'


class EventListener(metaclass=ABCMeta):

    @abstractmethod
    def notify(self, event_name, event_data):
        '''
        this function can return value(s)
        If the event source does not want to be blcoked by notify,
        it has to manage the concurrency outside of this call
        '''
        return None


class EventSource(metaclass=ABCMeta):
    '''
    abstact base class for event sources. All services that want to
    raise evetns uisng the RPC event infrastructure must inherit from
    this base class
    '''

    # list of rpc event names
    rpc_events = []

    def __init__(self):
        self.listeners_map = {event: set() for event in self.rpc_events}

    def register_listener(self, event_name: str, listener: EventListener):
        assert event_name in self.rpc_events
        assert isinstance(listener, EventListener)

        self.listeners_map[event_name].add(listener)

    def remove_listener(self, event_name: str, listener: EventListener):
        assert event_name in self.rpc_events
        self.listeners_map[event_name].discard(listener)

    def get_listeners(self, event_name):
        return self.listeners_map[event_name]
