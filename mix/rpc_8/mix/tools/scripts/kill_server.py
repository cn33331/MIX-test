'''
simple script for when you just want to shut down a server
'''

from mix.rpc.proxy.proxyfactory import ProxyFactory
from mix.rpc.transports.transport_error import RPCTransportTimeout
import argparse


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('url',
                        help='the url of the server to kill')

    args = parser.parse_args()

    try:
        factory = ProxyFactory.DefaultFactory(args.url)
        factory.stub('__server__', 'shut_down')
        factory.shut_down()
        print('Done!')
    except RPCTransportTimeout:
        print('Nothing to kill.')
