from mix.rpc.console.mconsole import ManagementConsole
from mix.rpc.constants import MAN_SERVER_PORT
from mix.tools.util.misc import klass_from_class_name
import argparse

phelper_dict = {
    'mcon': 'mix.rpc.launcher.mconprofilehelper.MCONProfileHelper',
    'none': None
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--action',
                        choices=['c', 's', 'C', 'S'],
                        help='the action to perform, it must be either c(onnect) or s(tart)')
    parser.add_argument('-u', '--manager_url',
                        help='the url of the management server, default to tcp://127.0.0.1:50000',
                        default='tcp://127.0.0.1:{0}'.format(MAN_SERVER_PORT))
    parser.add_argument('-d', '--profile_dir',
                        help='the path to where the profiles are stored',
                        default='.')
    parser.add_argument('-p', '--profile_type',
                        help='the tyep of profile helper',
                        choices=['mcon', 'none'],
                        default='mcon')

    args = parser.parse_args()

    helper = None
    if args.action:
        if args.action.lower() == 'c':
            console = ManagementConsole('my_console', helper, try_local=False)
            console.connect_man_server(args.manager_url)
        else:
            helper_class = None
            try:
                helper_class = phelper_dict[args.profile_type]
            except KeyError:
                print(f'unknown profile type {args.profile_type}')
                exit(-1)
            if helper_class is not None:
                profile_dir = args.profile_dir
                klass = klass_from_class_name(helper_class)
                helper = klass(profile_dir)
            if helper is None:
                print(f'You can not start a management server because you did\
                        not provide profile information. Helper type is {args.profile_type}')
                exit(-1)

            console = ManagementConsole('my_console', helper, try_local=False)
            console.start_man_server()
    else:
        console = ManagementConsole('my_console', helper, try_local=True)
    console.cmdloop()
