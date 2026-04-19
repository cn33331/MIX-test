import sys
sys.path.append('../../../')

from mix.tools.util.misc import klass_from_class_name
from mix.rpc.proxy.proxyfactory import ProxyFactory
from mix.rpc.transports.transport_error import RPCTransportTimeout

import argparse
import time
import sys

phelper_dict = {
    'mcon': 'mix.rpc.launcher.mconprofilehelper.MCONProfileHelper',
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('profile_dir',
                        help='the path to where the profiles are stored')
    parser.add_argument('-p', '--profile_type',
                        help='the tyep of profile helper',
                        choices=['mcon', 'none'],
                        default='mcon')

    args = parser.parse_args()
    helper = None
    try:
        helper_class = phelper_dict[args.profile_type]
        profile_dir = args.profile_dir
        klass = klass_from_class_name(helper_class)
        helper = klass(profile_dir)
    except KeyError:
        print(f'unknown profile type {args.profile_type}')
        exit(-1)

    # stopping the server in reverse order.
    servers = helper.app_server_list
    servers.reverse()
    for s in servers:
        server_cfg = helper.get_app_server_settings(s)
        sys.stdout.write(f'stopping server {s}@{server_cfg.url}...')
        try:
            pf = ProxyFactory.DefaultFactory(server_cfg.url, 'kill_proxy')
            pf.stub('__server__', 'shut_down')
            time.sleep(0.1)
            pf.shut_down()
            print('done')
        except RPCTransportTimeout:
            print(f'no server @{server_cfg.url}')

    # finally stopping the manager server
    man_url = helper.get_manager_settings().url
    sys.stdout.write('stopping the management server...')
    try:
        pf = ProxyFactory.DefaultFactory(man_url, 'kill_proxy')
        pf.stub('__server__', 'shut_down')
        time.sleep(0.1)
        pf.shut_down()
        print('done')
    except RPCTransportTimeout:
        print('no management server')
