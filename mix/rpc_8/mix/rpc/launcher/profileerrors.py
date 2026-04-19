class ProfileError(Exception):

    def __init__(self, msg, token=None):
        err_str = msg
        if token:
            sym = token.getSymbol()
            error_msg = msg or f'error from {sym.source}'
            self.line = sym.line
            self.column = sym.column
            self.offendingSymbol = sym
            err_str = f"line {self.line}:{self.column} {error_msg}"
        super().__init__(err_str)


class ProfileValueError(ProfileError):
    '''
    An invalid value is found in the profile even though it's legal syntax.
    These errors are found during the walk of the parsed tree
    '''
    pass


class ProfileParseError(ProfileError):
    '''An error happened during parsing of the profile files'''
    pass


class AntlrProfileParseError(ProfileParseError):
    '''
    Errors are found in the syntax of a profile file
    defined with an Antlr grammer
    '''

    def __init__(self, error_listener):
        err_str = '\n=====================\n'.join(error_listener.errors)
        super().__init__(err_str)
