import ipaddress
import time
import importlib
import platform
import uuid
import os

def is_valid_ip_addr(addr_str):
    """
    Validates an IPv4 Address
    """
    try:
        ip = ipaddress.ip_address(addr_str)
    except ValueError:
        return False
    else:
        return isinstance(ip, ipaddress.IPv4Address)


def cmt():
    """
    Gets current time in milliseconds
    """
    return round(time.time() * 1000)


def klass_from_class_name(class_str):
    """
    Return the klass object based on the python full path string
    """
    module_path, _, class_name = class_str.rpartition('.')
    if len(module_path) > 0:
        return getattr(importlib.import_module(module_path), class_name)
    else:
        return globals()[class_str]


def short_id(length=8):
    """
    Return a Random ID of the specified length, default to 8

    Uniqueness will depend on the length.  The shorter the lenght, the higher
    chance of collision.

    'bf70c8e3'
    'c2b8'

    One use case for this in your test, when you are using a QueueLogger, you
    want to make sure you only capture the logs from that partiuclar test. By
    giving your QueueLogger a unique identity, you won't capture logs from other
    tests inadvertantly
    """
    unique_id = str(uuid.uuid4())[:length]
    return unique_id


class Singleton(type):
    """
    Metaclass is a better way to implement the singleton
    design pattern than overriding __new__. metaclass is how you
    customize the creation of a class
    """
    _instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__call__(*args, **kwargs)
        return cls._instance


def is_running_on_zynq():
    """
    Checks if the os and hardware are correct.
    """
    info = platform.uname()
    os_name = info[0]
    hw_arch = info[-1]
    if 'Linux' in os_name and "armv7" in hw_arch:
        return True
    else:
        return False


def wait_pid(pid, timeout=30):
    """
    Wait for a pid to die.  
    Return True if pid is dead or dies within timeout window.  Otherwise False.
    """
    time_start = time.time()
    pid_running = True
    while pid_running:
        try:
            os.kill(pid, 0)
        except:
            pid_running = False
            break
    
        time.sleep(0.05)
        
        if time.time() - time_start > timeout:
            break

    return pid_running is False
