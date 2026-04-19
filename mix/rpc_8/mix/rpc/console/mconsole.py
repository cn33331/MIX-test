from ..proxy import ProxyFactory
from ..launcher import Launcher
from .consoleerror import ConsoleCmdError
from .miniargparser import MiniArgParser
from .console import ServerConsole, with_arg_parser
from .appconsole import RPCServerManagerConsole
from mix.tools.util.excreport import get_exc_desc
from mix.rpc.util import constants
from pprint import pprint


class ManagementConsole(ServerConsole):

    def no_manager(self):
        self.prompt = 'mix>>> '
        self.pf = None
        self.manager = None

    def __init__(self, id, profile_helper, try_local=False):
        super().__init__()
        self.id = id
        self.no_manager()
        self.p_helper = profile_helper
        if self.p_helper is None:
            self.launcher = None
        else:
            self.launcher = Launcher('launcher.mconsole')
        self.pf = None

        if try_local:
            self.connect_man_server(f'tcp://127.0.0.1:{MAN_SERVER_PORT}')

    def preloop(self):
        if self.pf is None:
            if not self.check_mserver_broadcast(100):
                print(
                    'no management beacon found yet. Maybe wait a few seconds and press enter again')
        return super().preloop()

    def precmd(self, line):
        if self.pf is None:
            self.check_mserver_broadcast()
        return super().precmd(line)

    def start_man_server(self):
        '''
        start the management server based on the information in profile
        '''
        if self.launcher is None:
            print(
                'you can not start a server becasue you have not provided profile information')
            return
        settings = self.p_helper.get_manager_settings()
        manager_url = settings.url
        try:
            self.launcher.launch_man_server(self.p_helper)
        except Exception as exc:
            raise RuntimeError(
                f'unable to start manager server at {manager_url}') from exc
        print(f'manager server started at {manager_url}')
        self.connect_man_server(manager_url)

    def connect_man_server(self, manager_url):
        try:
            self.pf = ProxyFactory.DefaultFactory(manager_url, self.id)
            self.manager = self.pf.get_proxy("manager")
            self.intro = 'manager server connected @ {0}. server version is {1}'.format(
                manager_url, self.pf.server_version)
            self.prompt = 'manager@{0}: '.format(manager_url)
        except Exception as exc:
            raise RuntimeError('unable to connect to manager server at {0}'.format(
                manager_url)) from exc

    def _quit(self, shut_down_server=True):
        if self.pf:
            self.pf.stub.transport.timeout = 300
            if shut_down_server:
                print('shutting down the management server ...')
                self.pf.stub('__server__', 'shut_down')
            self.pf.shut_down()

    start_arg_parser = MiniArgParser('start', msg='Start a server')
    start_arg_parser.add_argument('name', True, str, 'manager',
                                  help_msg='the server name. If the name is not given or if the name\
                                 is \u001b[1mmanager\u001b[0m, start the management server')

    def do_start(self, line):
        try:
            args = self.start_arg_parser.parse(line)
            if args.name == 'manager':
                self.start_man_server()
            else:
                if self.launcher is None:
                    print(
                        'you can not start a server becasue you have not provided profile information')
                    return

                server_infos = self.manager.list()
                server_names = [info.split('@')[0] for info in server_infos]
                if args.name in server_names:
                    print(f'server {args.name} already started. Use the connect command to connect')
                    return
                config = self.p_helper.get_app_server_settings(args.name)
                if config is None:
                    print(
                        '!!!Error: There is no config information for {0}'.format(args.name))
                    return
                print('starting application server {0}@{1}...'.format(
                    args.name, config.url))
                self.launcher.launch_app_server(args.name, self.p_helper)
                self.manager.connect(config.url)
                sc = RPCServerManagerConsole(args.name, self.manager)
                sc.cmdloop()
                self.last_sc = sc  # this is purely for testing
        except ConsoleCmdError:
            pass
        except RuntimeError as exc:
            self.print_error(get_exc_desc(exc))

    def help_start(self):
        self.start_arg_parser.print_help(online_help=True)

    stop_arg_parser = MiniArgParser('stop', msg='Stop a server')
    stop_arg_parser.add_argument('name', True, str, 'manager',
                                 help_msg='the server name. If the name is not given,\
                                 It is assumed to be \u001b[1mmanager\u001b[0m')

    def do_stop(self, line):
        '''stop a server. If no server is named, stop the management server'''
        if not self.pf:
            print(('Error: we are not connected to a manger server, please use the connect'
                   ' command to connect to one first'))
        else:
            try:
                args = self.stop_arg_parser.parse(line)
                if args.name == 'manager':
                    self.pf.stub('__server__', 'shut_down')
                    print('stopping the manager server...')
                    self.no_manager()
                else:
                    print(self.manager.stop_server(args.name))
            except ConsoleCmdError:
                pass
            except RuntimeError as exc:
                self.print_error(get_exc_desc(exc))

    def help_stop(self):
        self.stop_arg_parser.print_help(True)

    connect_arg_parser = MiniArgParser('connect', msg='Connect to a server. IF we are not already \
        connected to a management server, assume we are tying to connect to a management server, else \
        connect to an application server')
    connect_arg_parser.add_argument(
        'server', False, str, '', help_msg='the server url or the server name')

    @with_arg_parser(connect_arg_parser)
    def do_connect(self, args):
        try:
            if self.pf is None:
                self.connect_man_server(args.server)
            else:
                server_url = self.manager.get_server_url(args.server)
                if server_url:
                    name = self.manager.connect(server_url)
                else:
                    print("{0} is not a know server. Assume it's the server's URL".format(
                        args.server))
                    name = self.manager.connect(args.server)
                sc = RPCServerManagerConsole(name, self.manager)
                sc.cmdloop()
                self.last_sc = sc
        except Exception as exc:
            self.print_error(get_exc_desc(exc))
        return

    def help_connect(self):
        self.connect_arg_parser.print_help(True)

    def do_profile(self, line):
        '''
        show the loaded profile for the specific server. If no name is given,
        show the complete profile
        '''
        name = line.strip()
        print(self.p_helper.dumps(name))

    def do_list(self, line):
        '''list all the servers we know about'''
        server_info = self.manager.list()
        for server_desc in server_info:
            pprint(server_desc)

    def do_EOF(self, line):
        self._quit()
        return True

    def do_quit(self, line):
        '''
        quit the program and shut down the management server. If you want to
        quit without shutting down the management server, use exit
        '''
        self._quit()
        return True

    def do_q(self, line):
        '''short for quit'''
        return self.do_quit(line)

    def do_exit(self, line):
        '''
        quit the program without shutting down the management server. If you want to
        quit and shut down the management server, use quit
        '''
        self._quit(False)
        return True
