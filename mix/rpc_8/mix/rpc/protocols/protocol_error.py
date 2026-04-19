from ..rpc_error import RPCError


class RPCProtocolError(RPCError):
    pass


class RPCProtocolInvalidParam(RPCProtocolError):
    pass


class DataProtocolError(RPCProtocolError):
    pass


class InvalidEvent(DataProtocolError):
    def __init__(self, code, extra=''):
        super.__init__('unknown event code {0}. {1}'.format(code, extra))
