'''
All Error classes generated in the RPC infrastructure code should inherit from one of the Error classes
in this file
'''


class RPCError(RuntimeError):
    pass


class RPCTimeoutError(RPCError):
    pass


class RPCServiceError(RPCError):
    '''
    an error happened inside an RPC Service
    '''
    pass
