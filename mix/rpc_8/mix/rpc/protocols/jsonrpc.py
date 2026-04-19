from mix.tools.util.excreport import get_exc_desc
from ..util import constants
# from ..util.constants import constants
import ujson as json
import os

from .jsoncodec import *
import time

class JSONRPCError(RuntimeError):
    def __init__(self, request_id, error_dict):
        self.request_id = request_id
        self.code = error_dict['code']
        self.msg = error_dict['message']

    def __str__(self):
        return 'RPC error({0}: {1}'.format(self.code, self.msg)


def json_extend_encode(obj):
    '''
    Helper function to perform extended data encoding, so we 
    can serialize the non JSON compliance types.
    '''
    if obj.__class__ in JSON_EXTENSION_ENCODER:
        return JSON_EXTENSION_ENCODER[obj.__class__].encode(obj)
    if isinstance(obj, tuple):
        obj = list(obj)
    if isinstance(obj, list):
        for i in range(len(obj)):
            if obj[i].__class__ in JSON_EXTENSION_ENCODER:
                obj[i] = JSON_EXTENSION_ENCODER[obj[i].__class__].encode(obj[i])
            elif isinstance(obj[i], list):
                obj[i] = json_extend_encode(obj[i])
            elif isinstance(obj[i], dict):
                for k in obj[i].keys():
                    obj[i][k] = json_extend_encode(obj[i][k])
    elif isinstance(obj, dict):
        for k in obj.keys():
            obj[k] = json_extend_encode(obj[k])

    return obj


def json_extend_decode(obj):
    '''
    Helper function to perform extended data decoding, back to native python type.
    '''
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = json_extend_decode(obj[i])
    elif isinstance(obj, dict):
        for k in obj.keys():
            if k in JSON_EXTENSION_DECODER.keys():
                return JSON_EXTENSION_DECODER[k].decode(obj[k])
            else:
                obj[k] = json_extend_decode(obj[k])

    return obj


class JSONPacketMixin:
    __slots__ = ()

    def dump_json(self):
        d = {}
        for k in self.__slots__:
            try:
                v = getattr(self, k)
                d[k] = v
            except AttributeError:
                continue
        return json.dumps(d)

    def serialize(self):
        s = self.dump_json()
        return s.encode('utf8')

    def __str__(self):
        return self.dump_json()


class JSONRPCResponse(JSONPacketMixin, object):

    __slots__ = ['version', 'request_id', 'error', 'result']

    def __init__(self, request_id, result=None, error_code=0, error_msg=None):
        self.version = JSONRPCProtocol.version
        self.request_id = request_id
        if error_code != 0:
            self.error = {'code': error_code, 'message': error_msg}
        else:
            self.result = result

    def summary(self):
        '''
        returns a summary of the response. This is a helper function for logging
        '''
        if hasattr(self, 'error'):
            return '!!!!!!ERROR: ' + self.error['message']
        else:
            return str(self.result)

    def __eq__(self, other):
        if not isinstance(other, JSONRPCResponse):
            return False
        if self is other:
            return True
        if self.version == other.version and \
           self.request_id == other.request_id:
            if hasattr(self, 'error'):
                if hasattr(other, 'error'):
                    if self.error == other.error:
                        return True
            else:  # we must have result
                if hasattr(other, 'result'):
                    if self.result == other.result:
                        return True
        return False


class JSONRPCRequest(JSONPacketMixin, object):

    __slots__ = ['version', 'id', 'remote_id', 'method', 'args', 'kwargs']

    def __init__(self, remote_id, method, args=None, kwargs=None):
        self.version = JSONRPCProtocol.version
        self.id = time.monotonic_ns()
        self.remote_id = remote_id
        self.method = method
        '''
        python would have automatically assigned args=[], kwargs={} if the
        caller didn't provide them. Here we dont' even assign them so
        1. Less data to transmit
        2. don't confuse the callee.
        '''
        if args:
            if isinstance(args, str):
                args = [args]
            self.args = args
        if kwargs and len(kwargs) > 0:
            self.kwargs = kwargs

    def __eq__(self, other):
        if not isinstance(other, JSONRPCRequest):
            return False
        if self is other:
            return True
        if self.version == other.version and \
           self.id == other.id and \
           self.remote_id == other.remote_id and \
           self.method == other.method and \
           self._identical_args(other) and \
           self._identical_kwargs(other):
            return True
        return False

    def _identical_args(self, other):
        if hasattr(self, 'args'):
            if hasattr(other, 'args'):
                if self.args == other.args:
                    return True
        else:
            if not hasattr(other, 'args'):
                return True
        return False

    def _identical_kwargs(self, other):
        if hasattr(self, 'kwargs'):
            if hasattr(other, 'kwargs'):
                if self.kwargs == other.kwargs:
                    return True
        else:
            if not hasattr(other, 'kwargs'):
                return True
        return False


class JSONRPCProtocol(object):
    version = 'MIX_2.0'

    def create_request(self, remote_id, method, args, kwargs):
        request = JSONRPCRequest(remote_id, method, args, kwargs)
        return request

    def create_response(self, request_id, result):
        response = JSONRPCResponse(request_id, result)
        return response

    def error_response(self, request_id, error_code, error_msg):
        response = JSONRPCResponse(
            request_id, result=None, error_code=error_code, error_msg=error_msg)
        return response

    def exp_error_response(self, request_id, exc, extra_msg=None,
                           error_code=constants.SERVER_ERROR):
        error_msg = get_exc_desc(exc)
        if extra_msg:
            error_msg = extra_msg + os.linesep + error_msg
        return JSONRPCResponse(request_id, result=None, error_code=error_code, error_msg=error_msg)

    def parse_response(self, bytes):
        data = bytes.decode('utf8')
        d = json.loads(data)
        if 'error' in d.keys():
            raise JSONRPCError(d['request_id'], d['error'])
        result = d['result']
        response = JSONRPCResponse(d['request_id'], result)
        return response

    def parse_request(self, bytes):
        data = bytes.decode('utf8')
        d = json.loads(data)
        request = JSONRPCRequest(d["remote_id"], d["method"], d.get(
            "args", []), d.get("kwargs", {}))
        request.id = d['id']
        return request
