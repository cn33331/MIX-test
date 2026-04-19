class Symbol(object):
    def __init__(self, name, sdef, scope=None):
        self.name = name
        self.definition = sdef
        self.scope = scope

    def __eq__(self, other):
        if self.name == other.name \
                and self.definition == other.definition \
                and self.scope.name == other.scope.name:
            return True
        else:
            return False

    def __str__(self):
        return f'{self.scope.name}.{self.name}: {self.definition}'


class Scope(object):
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.symbols = {} # values of dictionary are symbols, which are abstractions of services

    def define(self, sym):
        ''' Adds a new symbol to symbols dictionary. Use resolve to retrieve the symbol'''
        if sym.name in self.symbols.keys():
            raise NameError(f"{sym.name} has already been defined")
        self.symbols[sym.name] = sym
        sym.scope = self

    def service_exists(self, service: str):
        return self.symbols.get(service) is not None

    def resolve(self, service_name, server_name = ''):
        ''' Retrieves symbol that was added by define. If symbol was not added to this scope then 
        parent scope is searched for the symbol. Need to have server_name, to look for the symbol
        in the parent scope.'''
        if server_name:
            return self.parent.resolve(server_name = server_name , service_name = service_name)
        return self.symbols.get(service_name)
    
    def find_servers_with_service(self, service_name: str):
        if self.parent:
            return self.parent.find_servers_with_service(service_name)

    def __eq__(self, other):
        if self.name == other.name \
                and self.parent == other.parent:
            if self.symbols.keys() == other.symbols.keys():
                for symbol in self.symbols.values():
                    if not symbol == other.symbols[symbol.name]:
                        return False
                else:
                    return True
        return False

    def __str__(self):
        return f'{self.name} : ' + ', '.join([f'{s.scope.name}.{s.name}' for s in self.symbols.values()])


class GlobalScope():
    def __init__(self):
        self.server_scopes = {}

    def add_child(self, scope : Scope):
        self.server_scopes[scope.name] = scope

    def resolve(self, service_name, server_name):
        ''' Will return the symbol if the server_name has the service_name'''
        if server_scope := self.server_scopes.get(server_name):
            return server_scope.symbols.get(service_name)
    
    def find_servers_with_service(self, service_name: str):
        possible_servers = []

        for scope in self.server_scopes.values():
            if scope.service_exists(service_name):
                possible_servers.append( scope.name )
        return possible_servers

