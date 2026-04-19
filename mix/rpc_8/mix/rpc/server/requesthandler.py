from ..protocols import JSONRPCResponse


class RequestHandlerMixin:

    '''
    for any class that contain this mix in, it needs to have a member called
    protocol, and it shoudl be a JSONRPCProtocol
    '''

    def call_method(self, request, service):

        if hasattr(service, 'rpc_public_property'):
            if request.method[:8] == '__fget__':
                if request.method[8:] in service.rpc_public_property:
                    return getattr(service, request.method[8:])
            if request.method[:8] == '__fset__':
                if request.method[8:] in service.rpc_public_property:
                    return setattr(service, request.method[8:], request.args[0])
            if request.method[:8] == '__fdel__':
                if request.method[8:] in service.rpc_public_property:
                    return delattr(service, request.method[8:])

        if request.method not in service.rpc_public_api:
            raise AttributeError('{0} is not a public function on {1}'.format(
                request.method, service.__class__))

        method = getattr(service, request.method)
        # it doesn't seem necessary to validate the arguments here. If the arguments dont'
        # match, excpetoin will be raised when the function is called anyway.
        # I know the following if...else.. block is ugly, I can't think of a better way now
        if not hasattr(request, "args"):
            if not hasattr(request, 'kwargs'):
                result = method()
            else:
                result = method(**request.kwargs)
        else:
            if not hasattr(request, 'kwargs'):
                result = method(*request.args)
            else:
                result = method(*request.args, **request.kwargs)
        return result

    def handle_request(self, request, service):
        response = None
        result = None
        try:
            result = self.call_method(request, service)
            response = JSONRPCResponse(request.id, result)
        except Exception as e:  # todo: more exception type, better excpetion information
            extra_msg = "error calling {0}.{1}".format(
                service.__class__, request.method)
            response = self.protocol.exp_error_response(
                request.id, e, extra_msg)
        return response
