from mix.tools.util.logfactory import create_null_logger
from mix.tools.util.misc import is_valid_ip_addr

import socket
import os
import time
import uuid


class LinuxHelper():

    def __init__(self):
        self.logger = create_null_logger()

    @property
    def ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # connect to a fake ip, it doesn't matter the connect
            # fails, you sill get the local host.
            s.connect(('169.0.0.1', 1))
            ip_addr = s.getsockname()[0]
        except Exception:
            ip_addr = '127.0.0.1'
        finally:
            s.close()
        return ip_addr

    @ip.setter
    def ip(self, new_ip):
        # untested code
        assert is_valid_ip_addr(new_ip)
        print("ifconfig eth0 {}".format(new_ip))
        os.popen("ifconfig eth0 {}".format(new_ip))

    @property
    def time(self):
        # return current time
        return time.time()

    @time.setter
    def time(self, timestamp):
        # timestamp ought to be (float, int)
        if not isinstance(timestamp, (float, int)):
            raise Exception("expected float or int as argument")

        if os.system('date -s @' + str(timestamp)) != 0:
            raise Exception("unable to update system time")

    @property
    def mac_address(self):
        return str(hex(uuid.getnode()))


class LinuxHelperSim(LinuxHelper):

    def __init__(self):
        self._ip = "0.0.0.12"
        self._time = 0
        self._mac = '000000000000'

    @property
    def ip(self):
        return self._ip

    @ip.setter
    def ip(self, new_ip):
        self._ip = new_ip

    @property
    def time(self):
        return self._time

    @time.setter
    def time(self, timestamp):
        # timestamp ought to be (float, int)
        if not isinstance(timestamp, (float, int)):
            raise Exception("expected float or int as argument")
        self._time = timestamp

    @property
    def mac_address(self):
        return self._mac

    @mac_address.setter
    def mac_address(self, new_mac):
        self._mac = new_mac
