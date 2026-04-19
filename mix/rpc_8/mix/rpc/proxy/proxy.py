from ..services.eventobjects import EventSource, EventListener, REGISTER_CALL, DEREGISTER_CALL
from .dsproxy import DataStreamProxy
from ..transports import RPCError, ZMQTransport
from ..protocols import datarpc
from mix.tools.util.excreport import get_exc_desc
from mix.rpc.protocols.jsonrpc import json_extend_decode

from inspect import Signature


class ProxyMethod(object):

    def __init__(self, remote_obj_id, stub, method_name, method_info):
        self.remote_obj_id = remote_obj_id
        self.stub = stub
        self.method_name = method_name  # kept for error reporting
        self.method_info = method_info  # this doesn't seem necessary to keep
        self.sig = Signature(method_info.get('params', []))
        self.__doc__ = method_info.get('__doc__', '')

    def __call__(self, *args, **kwargs):

        # Strip 'rpc_timeout' before signature binding
        rpc_timeout = None
        if 'rpc_timeout' in kwargs.keys():
            rpc_timeout = kwargs.pop('rpc_timeout')

        try:
            ba = self.sig.bind(*args, **kwargs)
        except TypeError as e:
            raise RPCError("Error calling {0}.{1}: {5}; signature is {2}; got arguments: {3}, {4}".format
                           (self.remote_obj_id, self.method_name, str(self.sig), args, kwargs, str(e)))
        ba.apply_defaults()
        return self.stub(self.remote_obj_id, self.method_name, *ba.args, rpc_timeout=rpc_timeout, **ba.kwargs)


class ProxyProperty(property):
    def __init__(self, remote_obj_id, stub, property_name, remote_property_info):
        self.property_name = property_name
        self.remote_obj_id = remote_obj_id
        self.stub = stub
        if 'fget' in remote_property_info.keys() and remote_property_info['fget']:
            getter = self.proxy_getter
        else:
            getter = None

        if 'fset' in remote_property_info.keys() and remote_property_info['fset']:
            setter = self.proxy_setter
        else:
            setter = None

        if 'fdel' in remote_property_info.keys() and remote_property_info['fdel']:
            deleter = self.proxy_deleter
        else:
            deleter = None

        super().__init__(getter, setter, deleter)

        if '__doc__' in remote_property_info.keys() and remote_property_info['__doc__']:
            self.__doc__ = remote_property_info['__doc__']

    def proxy_getter(self, proxy):
        return self.stub(proxy.remote_obj_id, "__fget__" + self.property_name)

    def proxy_setter(self, proxy, value):
        return self.stub(proxy.remote_obj_id, "__fset__" + self.property_name, value)

    def proxy_deleter(self, proxy):
        return self.stub(proxy.remote_obj_id, "__fdel__" + self.property_name)


class DataStreamOpen(ProxyMethod):

    def __init__(self, remote_obj_id, stub, method_name, method_info):
        prot, addr = ZMQTransport.parse_protocol(stub.transport.end_point)
        self.remote_ip = addr.split(':')[0]
        super().__init__(remote_obj_id, stub, method_name, method_info)

    def __call__(self, *args, **kwargs):
        result = super().__call__(*args, **kwargs)
        assert datarpc.__MIX_DS_VERSION__ == result['meta_data']['version']
        ds_proxy = DataStreamProxy.DefaultProxy(self.remote_ip,
                                                result['port'],
                                                result['meta_data']['packing'])
        ds_proxy.logger = self.logger.getChild(self.remote_obj_id + '.' + ds_proxy.identity)
        return ds_proxy


class RPCProxy(object):

    def __new__(cls, remote_obj_id, obj_info, logger, stub, factory):

        # Dynamically create a RPCProxy subclass
        NEW_CLS = type(remote_obj_id + "_RPCProxy", (_RPCProxy,), {})
        instance = NEW_CLS(remote_obj_id, obj_info, logger, stub, factory)

        # Attach properties
        if '__rpc_properties__' in obj_info.keys():
            for property_name, property_info in obj_info['__rpc_properties__'].items():
                p = ProxyProperty(remote_obj_id, stub, property_name, property_info)
                setattr(instance.__class__, property_name, p)

        # Add rpc_public_api as property
        p = property(lambda x : list(obj_info["methods"].keys()))
        setattr(instance.__class__, "rpc_public_api", p)

        return instance


class _RPCProxy(EventSource, EventListener):

    def __init__(self, remote_obj_id, obj_info, logger, stub, factory):
        obj_info = json_extend_decode(obj_info)
        self.remote_obj_id = remote_obj_id
        self.logger = logger
        self.stub = stub
        self.proxy_factory = factory
        self.__class__.__doc__ = obj_info.get('__doc__', 'a proxy for ' + remote_obj_id)

        # function parameter checking can now done locally
        for method_name, method_info in obj_info['methods'].items():
            m = None
            if datarpc.DATA_PATH in method_info:
                m = DataStreamOpen(self.remote_obj_id,
                                   stub, method_name, method_info)
            else:
                m = ProxyMethod(self.remote_obj_id, stub,
                                method_name, method_info)
            m.logger = self.logger.getChild(method_name)
            setattr(self.__class__, method_name, m)

        if 'events' in obj_info:
            self.rpc_events = obj_info['events']
        super().__init__()

    def notify(self, event_name, event_data):
        results = []
        for listener in self.listeners_map[event_name]:
            try:
                result = listener.notify(event_name, event_data)
            except Exception as exc:
                self.logger.exception(exc)
                result = get_exc_desc(exc)
            results.append(result)
        return results

    def register_listener(self, event_name, listener):
        super().register_listener(event_name, listener)
        e_server = self.proxy_factory.get_event_server()
        self.remote_register(event_name, e_server.transport.end_point)
        self.proxy_factory.listen_for(event_name, self)

    def remote_register(self, event_name, event_server_url):
        self.stub(self.remote_obj_id, REGISTER_CALL,
                  event_server_url, event_name)

    def remove_listener(self, event_name, listener):
        super().remove_listener(event_name, listener)
        e_server = self.proxy_factory.get_event_server()
        self.remote_unregister(event_name, e_server.transport.end_point)
        # last one out turns off the light
        if len(self.listeners_map[event_name]) == 0:
            e_server.unregister(event_name, self)

    def remote_unregister(self, event_name, event_server_url):
        self.stub(self.remote_obj_id, DEREGISTER_CALL,
                  event_server_url, event_name)

    def deregister_all(self):
        for event_name, listeners in self.listeners_map.items():
            # create a new list so that we are not changing
            for listener in list(listeners):
                # the size of the set while iterating over it
                self.remove_listener(event_name, listener)
