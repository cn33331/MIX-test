from abc import abstractmethod
from datetime import datetime
from inspect import Parameter
import builtins

'''
This module provides json encoding/decoding extension.

To add additional codec that jsonrpc::json_extend_encode() and jsonrpc::json_extend_decode() can support:
  1) Add a new subclass to 'JSONRPCExtendedCodec'
  2) Add the class and type to 'JSON_EXTENSION_ENCODER'
'''

class JSONRPCExtendedCodec():
    '''
    ABC for defining Codec
    '''

    @staticmethod
    @abstractmethod
    def id(self):
        '''
        Extended type identifier
        '''

    @staticmethod
    @abstractmethod
    def encode(self, obj):
        '''
        Encode python type to serializable format
        '''
    @staticmethod
    @abstractmethod
    def decode(self, obj):
        '''
        Decode JSONRPC data back to python types
        '''

class DateTimeCodec(JSONRPCExtendedCodec):
    
    id = '__MRPC_EXTENDED_0'    
    
    @staticmethod
    def encode(obj):
        return {DateTimeCodec.id: str(obj.timestamp())}

    @staticmethod
    def decode(obj):
        return datetime.fromtimestamp(float(obj))


class ParameterCodec(JSONRPCExtendedCodec):

    id = '__MRPC_EXTENDED_1'

    @staticmethod
    def encode(obj):
        param_dict = {'name': obj.name, 'kind': int(obj.kind)}
        if not obj.default == Parameter.empty:
            param_dict['default'] = obj.default
        if not obj.annotation == Parameter.empty:
            param_dict['annotation'] = obj.annotation.__name__
        return {ParameterCodec.id : param_dict}

    @staticmethod
    def decode(obj):
        p = Parameter(obj['name'], obj['kind'])
        if "default" in obj.keys():
            p = p.replace(default=obj['default'])
        if "annotation" in obj.keys():
            clas = getattr(builtins, obj['annotation'])
            p = p.replace(annotation=clas)
        return p

'''
Register new codec support here
'''
JSON_EXTENSION_ENCODER = {
    datetime : DateTimeCodec,
    Parameter : ParameterCodec,
}

JSON_EXTENSION_DECODER = {v.id: v for k, v in JSON_EXTENSION_ENCODER.items()}