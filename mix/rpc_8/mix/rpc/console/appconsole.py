from ..proxy.proxyfactory import ProxyFactory
from ..util.constants import ICI_POWER_OK, ICI_NOT_COMPATIBLE, ICI_NO_POWER_CONTROL
from .console import ServerConsole


class RPCServerManagerConsole(ServerConsole):
    def __init__(self, server_name, man_proxy):
        super().__init__()
        server_url = man_proxy.get_server_url(server_name)
        self.man_proxy = man_proxy
        self.server_name = server_name
        self.prompt = '{0}@{1}: '.format(server_name, server_url)
        self.pf = ProxyFactory.JsonZmqFactory(
            server_url, '{0}_console'.format(server_name))

    def do_copy(self, line):
        '''copy the server log to the designated local location'''
        pass

    def do_stop(self, line):
        print('stopping app server {0}'.format(self.server_name))
        self.man_proxy.stop_server(self.server_name)
        self.pf.shut_down()
        return True

    def do_list(self, line):
        '''list all the services available on this server'''
        services = self.pf.list_remote_services()
        print('These services are available:')
        indent = '    '
        for s in services:
            print(f"{indent}{s}")

    def show_power_ret(self, inst, ret):
        if ret == ICI_POWER_OK:
            print('power control OK')
        elif ret == ICI_NOT_COMPATIBLE:
            print(f"{inst} is not an ICI compatible instrument")
        elif ret == ICI_NO_POWER_CONTROL:
            print(f"{inst} is ICI compatible, but system does not support two step power control")

    def do_on(self, line):
        '''power on the specified instrument'''
        inst = line.strip()
        try:
            ret = self.pf.power_on(inst)
            self.show_power_ret(inst, ret)
        except Exception as e:
            print(e)

    def do_off(self, line):
        '''power off the specified instrument'''
        inst = line.strip()
        try:
            ret = self.pf.power_off(inst)
            self.show_power_ret(inst, ret)
        except Exception as e:
            print(e)

    def do_quit(self, line):
        '''quit the management console for this server and return to previous menu'''
        self.pf.shut_down()
        return True
