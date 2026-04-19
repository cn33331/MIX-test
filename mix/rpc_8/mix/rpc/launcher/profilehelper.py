from abc import ABCMeta, abstractmethod
from collections import namedtuple
from typing import List, OrderedDict, Dict

from mix.tools.util.attrcontainer import AttrContainerMixin


class InstRef(AttrContainerMixin):
    '''A reference to a remote instrument in the profile. It can have following inputs 
    service : just a service or,
    service.1 : service with a port or,  
    server.service service belonging to external server
    server.service.1 : service belonging to external server with a port
    inst_name is the service name.
    server is the name of the external server. Is empty string if external server does not exits.
    channel is the port. Its -1 if no port exists.
    '''
    __slots__ = ['inst_name', 'channel', 'server']

    def __init__(self, var_name):
        self.channel = -1
        parts = var_name.split('.')

        part_len = len(parts)
        self.server = ''
        if part_len > 3:
            raise ValueError('Cannot have more than two dots in the input string')
        if part_len > 1:
            if(parts[-1].isnumeric()):
                self.channel = int(parts[-1])
                # conversion to int was successful. Last part is port, the part before that is service,
                # part before service (if it exists, i.e. len(parts) == 3) is server name
                if part_len == 2:
                     self.inst_name = parts[0]#inst_name is service name
                else:
                    self.server = parts[0]
                    self.inst_name = parts[1]
            else:
                #len > 1 and last is not port, so len is 2 and we are provided with server and inst_name 
                self.server = parts[0]
                self.inst_name = parts[1]
        else:#part_len == 0, only service is provided
            self.inst_name = var_name




class ServiceConfig(AttrContainerMixin):
    pass


class GenericServiceConfig(ServiceConfig):
    '''
    Config information for generaic service
    '''
    __slots__ = ['class_name', 'kw_args']

    def __init__(self, class_name, kw_args):
        self.class_name = class_name
        self.kw_args = kw_args


class ICIServiceConfig(ServiceConfig):
    '''
    config information for ICI compatible service
    '''
    __slots__ = ['allowed_list', 'two_step', 'kw_args']

    def __init__(self, allowed_list, two_step_ctrl, kw_args):
        self.allowed_list = allowed_list
        self.two_step = two_step_ctrl
        self.kw_args = kw_args


class ServerProfile(object):
    '''the information needed to start a server'''

    def __init__(self, url=None, config={}):
        self.url = url
        self.config = config
        self.services = OrderedDict()
        self.slot = -1

    def __str__(self):
        indent = '    '
        ret = f'\n{indent}url : {self.url}'
        ret += f'\n{indent}config : {self.config}'
        if self.slot >= 0:
            ret += f'\n{indent}slot : {self.slot}'
        for name, service in self.services.items():
            ret += f'\n{indent}{name} : {service}'
        return ret


class Profile(object):
    '''the information parsed from teh profile files'''

    def __init__(self):
        self.version = 0
        self.driver_dirs = []
        self.namespaces = {}
        self.manager = ServerProfile()
        default_xavier = dict(default_ip='169.254.254.1',
                              base_ip='169.254.1.32',
                              ip_pins=None)
        self.manager.services['xavier'] = default_xavier
        self.app_servers = OrderedDict()

    def __str__(self):
        # todo: use textwrap.TextWrapper to make it nicer
        # or maybe better to just turn it into a json string
        ret = f'\nversion: {self.version}'
        ret += f'\ndriver_dirs : {self.driver_dirs}'
        ret += f'\nnamespaces : {self.namespaces}'
        ret += f'\nmanager : {self.manager}'
        for name, app_server in self.app_servers.items():
            ret += f'\n{name} : {app_server}'
        return ret


ServiceObjects = namedtuple('ServiceObject', 'service, two_step')


class ProfileHelper(metaclass=ABCMeta):
    '''
    this class definds the interface that returns objects and information the launcher
    needs to succesfully start the servers. You need to provide a concrete implementation of this
    interface for your configuration scheme
    On each deployment, what helper class to use is set in the environment variable
    MIX_LAUNCH_HELPER_CLASS
    '''

    @abstractmethod
    def get_xavier_ip(self):
        '''
        returns what the Xavier IP should be based on configuration
        '''
        pass

    @abstractmethod
    def get_manager_settings(self) -> Dict:
        '''
        returns the configuration for the manager server
        It should be a dictionary with these fields:
        return = {

            'url' : url of the manager server
            'config' : configuration corresponding the the manager server config dict

        }
        '''
        pass

    @abstractmethod
    def get_file_system_settings(self) -> Dict:
        '''
        returns the configuration for the file system service
        It should be a dictionary with these fields:
        return = {

           'allow_list' : [list of dirs]

        }
        '''
        pass

    @abstractmethod
    def get_app_server_list(self) -> List:
        '''
        return a lists of app server names. The launcher will start these servers in order
        '''
        pass

    @abstractmethod
    def get_services_for_server(self, server_name: str) -> OrderedDict:
        '''
        return all the serveice objects for the specified server
        The return is an ordered dictionary with the service names as the keys and the
        object for the service as the value.
        Note that each service is a live object, not a configure dictionary or any
        other kind of description
        It's the responsiblity of the concrete implementation of launchhelper to figure
        out which constructor to call and what arguemnts to use in order to create each service
        object
        The return is a ordereddict instead of a dict, because the launcher will initialize and
        register each service in order
        '''
        pass

    @abstractmethod
    def get_app_server_settings(self, server_name: str) -> Dict:
        pass

    def dumps(self, name=''):
        '''
        dump the raw profile content. Used for debug
        name is the name of the server whose setting to return.
        if name is an emtpy string then return everything
        '''
        raise NotImplementedError()
