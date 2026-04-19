from mix.rpc.launcher.mixconfig import ProfileLoader
from mix.rpc.launcher.profileerrors import ProfileError

import argparse
from pathlib import Path

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('profile_dir',
                        help='the path to where the profiles are stored')
    parser.add_argument('-p', '--profile_type',
                        help='the type of profile helper',
                        choices=['mcon', 'none'],
                        default='mcon')
    parser.add_argument('-v', '--verbose',
                        help='show the loaded profile',
                        action='store_true')

    args = parser.parse_args()

    print('')
    if args.profile_type == 'mcon':
        try:
            d = Path(args.profile_dir)
            swp_file = d / 'sw_profile.mixconf'
            hwp_file = d / 'hw_profile.mixconf'
            creator = ProfileLoader(swp_file, hwp_file)
            if args.verbose:
                print(creator.profile)
            else:
                print('OK. No error found.')
                print()
        except ProfileError as e:
            print('\n********ERROR***********')
            print(e)
            print()
    else:
        print(f'unknonw profile type {args.profile_type}')
        exit(-1)
