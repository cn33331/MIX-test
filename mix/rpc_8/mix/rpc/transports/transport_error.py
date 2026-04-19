from ..rpc_error import RPCError, RPCTimeoutError


class RPCTransportError(RPCError):
    pass


class RPCTransportTimeout(RPCTimeoutError):
    pass
