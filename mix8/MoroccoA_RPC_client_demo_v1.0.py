#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__author__ = 'junjie.liu@prmeasure.com'
__date__ = '2022/11/26 19:50'
__version__ = '1.0'

import threading
import sys
import time
import random
import string
import logging


# level=logging.INFO) # Text logging level for the message ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
def init_logger(file_path):
    max_size = 5 * 1000 * 1000  # ~5MB
    logger = logging.getLogger("Logger")
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(file_path, mode='a', maxBytes=max_size, backupCount=5)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

sys.path.append("./mix")
from time import sleep
from mix.rpc.proxy.proxyfactory import ProxyFactory
import base64


class RpcClient(object):
    def __init__(self, xavier_ip, xavier_port):
        self.xavier_ip = xavier_ip
        self.xavier_port = xavier_port
        name = {'7801': 'slot1', '7803': 'slot2', '7805': 'control_Board', '50000': 'manager'}
        self.slotName = name[str(xavier_port)]
        self.client = ProxyFactory.JsonZmqFactory('tcp://%s:%s' % (self.xavier_ip, self.xavier_port))
        self._list_remote_services()
        # self.methods_info("sib_board")
        self.logger = init_logger("./rpcClient.log")

    def _list_remote_services(self):
        """
        获取所有可调用方法
        """
        remote_service_list = self.client.list_remote_services()
        print(f"「{self.slotName} {self.xavier_port}」可调用的方法列表：{remote_service_list}")
        # for x in remote_service_list:
        #     self.methods_info(x)
        return remote_service_list

    def methods_info(self, obj_id):
        """
        打印可调用对象的所有方法的使用说明文档和传参指引
        """
        # a = self.client.get_proxy('file_system')
        # print(RPCProxy(self.client.get_proxy('file_system')))
        # print(self.client.get_proxy(obj_id))
        # print(self.client.get_server_identity())
        # print(self.client.stub('__server__', 'get_service_info', obj_id))
        methodsObj = self.client.stub('__server__', 'get_service_info', obj_id)
        subMethods = list(methodsObj['methods'].keys())
        print(f"obj: [{obj_id}] 的方法列表：{subMethods}\n\n")
        for methods in subMethods:
            if methodsObj['methods'][methods]['__doc__']:
                doc = methodsObj['methods'][methods]['__doc__'].replace('\n:' and '\n', '\n\t\t\t')
                print(f"[{methods}]:\n\t\t\t{doc}")
                print(f"\targs:\t{methodsObj['methods'][methods]['params']}", end='\n\n\n')
            else:
                print(f"{methodsObj['methods'][methods]} 没有参考文档")

    def fwdl_obj(self):
        md5_readBack_file = self.client.get_proxy('fwdl_obj').get_md5_readBack_file(
            '/mix/addon/dut_firmware/ch1/ACE_FW.readback')
        with open(f'./{self.slotName}_ACE_FW.readback', 'wb') as f:
            f.write(base64.b64decode(md5_readBack_file.encode('utf-8')))

    def controlBoardA(self):
        print(self.client.get_proxy('lucifer').led_control("UUT4", "BLUE"))
        print(self.client.get_proxy('lucifer').led_control("UUT4", "RED"))
        # lucifer.fixture_io_set [[10,0],[11,0]]

    def controlBoardB(self):
        print(self.client.get_proxy('lucifer').led_control("UUT2", "BLUE"))
        print(self.client.get_proxy('lucifer').led_control("UUT2", "RED"))
        # lucifer.fixture_io_set [[10,0],[11,0]]

    def sibBoard(self, xavier_port):
        startTime = time.time()
        self.client.get_proxy('relay').reset('reset')
        endTime = time.time()
        print(f"开始时间{startTime}, 结束时间：{endTime}, 消耗时间：{endTime - startTime}")

        print(f"{xavier_port}", self.client.get_proxy('sib_board').reset_gpio())
        print(f"{xavier_port}", self.client.get_proxy('sib_board').get_gpio('gpio_ocp_in'))

        print(f"{xavier_port}", self.client.get_proxy('sib_board').lock_xadc_measure(0, 0, 20))
        print(f"{xavier_port}", self.client.get_proxy('sib_board').read_string_eeprom(0x20, 20))

    @staticmethod
    def generate_random_string(length):
        """Generate a random string of specified length"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def log_message(self, log_file, write_type, message):
        """Write a message to the log file"""
        if write_type == 'a':
            with open(log_file, 'a') as f:
                f.write(message + '\n')
        if write_type == 'w':
            with open(log_file, 'w') as f:
                f.write(message + '\n')

    def ft4222_eerprm(self, xavier_port):
        print(self.client.get_proxy('eeprom').read_string_eeprom(0x20, 30))
        print(self.client.get_proxy('eeprom').write_string_eeprom(0x20, "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))

    def test_eeprom(self, log_file='i2c_eeprom_test_log.csv', iterations=2000):
        title = "Iteration,Memory address,Read and write length,Data matches Result,Written,Read"
        self.log_message(log_file, 'w', title)
        eeprom = self.client.get_proxy('eeprom')
        re_wr_len = 256
        for i in range(iterations):
            # Generate random string data to write
            test_string = self.generate_random_string(re_wr_len)
            write_address = 0x00

            # Write the generated string to EEPROM
            eeprom.write_string_eeprom(write_address, test_string)

            # Read back the data
            read_data = eeprom.read_string_eeprom(write_address, len(test_string))

            # Check if the written data matches the read data
            print(f'test_string:{test_string}')
            print(f'  read_data:{read_data}')
            if test_string == read_data:
                result = f"{i+1},0x{write_address:02X},{re_wr_len},SUCCES,{test_string},{read_data}"
            else:
                result = f"{i+1},0x{write_address:02X},{re_wr_len},FAILURE,{test_string},{read_data}"

            # Log the result
            self.log_message(log_file, 'a', result)

            # Print result to console for immediate feedback
            print(result)

            # Small delay between iterations
            # time.sleep(0.1)

    def mac_demo(self):
        # self.client.get_proxy("mac_demo")
        ret = self.client.get_proxy('relay').reset()
        self.logger.info(ret)
        print(ret)

    def main(self, xavier_port):
        print("-" * 50)
        print('\n')
        # self.fwdl_obj()
        # self.controlBoardA()
        # self.controlBoardB()
        # self.sibBoard(xavier_port)
        # self.ft4222(xavier_port)
        # self.test_eeprom()
        self.mac_demo()


class Multitasking(object):
    def __init__(self):
        pass


def slotObj(xavier_ip, xavier_port):
    slotClient = RpcClient(xavier_ip, xavier_port)
    slotClient.main(xavier_port)


if __name__ == '__main__':
    threads = []
    # client = RpcClient('169.254.1.32', 7805)
    # client.methods_info('lucifer')
    # exit()
    threadSlot1 = threading.Thread(name='slot1', target=slotObj, args=('192.168.99.36', 7801))
    threadSlot1.start()

    client = RpcClient('169.254.1.36', 7801)

