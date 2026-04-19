import sys
sys.path.append('../../../')
from mix.rpc.launcher import Launcher
from mix.tools.util.misc import klass_from_class_name
from mix.rpc.proxy.proxyfactory import ProxyFactory

import argparse
import time

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

    launcher = Launcher()
    try:
        launcher.go(helper)
    except Exception:
        print('error starting the Lynx system. Please check logs in /var/tmp/xavier')
        for name, info in launcher.started_servers.items():
            pid = info[0]
            url = info[1]
            print(f'shutting down started server {name} @{url}')
            pf = ProxyFactory.DefaultFactory(url, 'kill_proxy')
            pf.stub('__server__', 'shut_down')
            time.sleep(0.1)
            pf.shut_down()
        exit(-1)

    man_url = helper.get_manager_settings().url
    print(f'management server started at {man_url}')

    pf = ProxyFactory.DefaultFactory(man_url, 'test_mc')
    iden = pf.stub('__server__', 'identity')
    assert iden == 'm_server'

    man = pf.get_proxy('manager')
    app_list = man.list()
    for entry in app_list:
        print(entry)
    pf.shut_down()


# python3.10 start_lynx.py ../../../mix/addon/config
