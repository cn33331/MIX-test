from functools import wraps
import cmd
import os
from pprint import pprint

from .consoleerror import ConsoleCmdError
from .miniargparser import MiniArgParser
from ..server import RPCServer
from mix.tools.util.excreport import get_exc_desc


def with_arg_parser(parser):
    def wrap_f(func):
        @wraps(func)
        def wrapped(self, line):
            try:
                args = parser.parse(line)
                return func(self, args)
            except ConsoleCmdError:
                pass
        return wrapped
    return wrap_f


class ServerConsole(cmd.Cmd):

    def do_version(self, line):
        '''show the version of the connected server is'''
        if not self.pf:
            print('!!!Not connected to a server!!!')
        print(self.pf.get_server_version())

    def do_loggers(self, line):
        '''show all the loggers registerd on the connected server'''
        if not self.pf:
            print('!!!Not connected to a server!!!')
        loggers = self.pf.get_server_loggers()
        for logger_info in loggers:
            pprint(logger_info)

    def do_identity(self, line):
        '''show the identity of the connected server'''
        if not self.pf:
            print('!!!Not connected to a server!!!')
        print(self.pf.get_server_identity())

    def do_dir(self, line):
        '''
        list all the services registerd on this server, or all the exposed
        functions of the named service
        '''
        pass

    def print_error(self, msg):
        print('!!!!ERROR!!!!!: {0}\t{1}'.format(os.linesep, msg))

    def do_services(self, line):
        '''
        show all the services currently registered on this server
        '''
        if self.pf:
            pprint(self.pf.stub('__server__', 'get_all_services'))
        else:
            print('we are not connected to a server yet!')

    config_arg_parser = MiniArgParser(
        'configure the server, if not property is sepcified, showed the current config')
    config_arg_parser.add_argument(
        'name', True, str, help_msg='the server property to configure')
    config_arg_parser.add_argument('value', True, str, help_msg='the value to be configured. If not specified,'
                                   ' display the of the specific property')

    def do_config(self, line):
        args = self.config_arg_parser.parse(line)
        if self.pf is None:
            self.print_error('You are not connected to a server.')
            return
        else:
            try:
                if len(args.name) == 0:
                    for name in RPCServer.DEFAULT_CONFIG.keys():
                        print('{0:<20}:  {1}'.format(
                            name, self.pf.get_config(name)))
                else:
                    if len(args.value) == 0:
                        print('{0:<20}:  {1}'.format(
                            args.name, self.pf.get_config(args.name)))
                    else:
                        value = eval(args.value)
                        self.pf.set_config(args.name, value)
            except Exception as e:
                print(get_exc_desc(e))

    def help_config(self, line):
        self.config_arg_parser.print_help()
