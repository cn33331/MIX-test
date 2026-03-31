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
        self.client = ProxyFactory.JsonZmqFactory('tcp://%s:%s' % (self.xavier_ip, self.xavier_port))
        self.logger = init_logger("./rpcClient.log")
        self.all_method_doc = {}

    def _list_remote_services(self):
        """
        获取所有可调用方法
        """
        remote_service_list = self.client.list_remote_services()
        print(f"「 {self.xavier_port}」可调用的方法列表：{remote_service_list}")
        # for x in remote_service_list:
        #     self.methods_info(x)
        return remote_service_list

    def methods_info(self, obj_id):
        """
        打印可调用对象的所有方法的使用说明文档和传参指引
        """
        self.all_method_doc[obj_id] = {}
        self.methodsObj = self.client.stub('__server__', 'get_service_info', obj_id)
        self.subMethods = list(self.methodsObj['methods'].keys())
        # print(f"obj: [{obj_id}] 的方法列表：{self.subMethods}\n\n")
        for methods in self.subMethods:
            if self.methodsObj['methods'][methods]['__doc__']:
                doc = self.methodsObj['methods'][methods]['__doc__'].replace('\n:' and '\n', '\n\t\t\t')
                self.all_method_doc[obj_id][methods] = doc
                # print(f"[{methods}]:\n\t\t\t{doc}")
                # print(f"\targs:\t{self.methodsObj['methods'][methods]['params']}", end='\n\n\n')
            else:
                pass
                # print(f"{self.methodsObj['methods'][methods]} 没有参考文档")
        return self.methodsObj,self.subMethods

    def subMethods_info(self, obj_id, method_name):
        if obj_id in self.all_method_doc:
            pass
        else:
            self.methods_info(obj_id)
        if method_name in self.all_method_doc[obj_id]:
            return self.all_method_doc[obj_id][method_name]
        else:
            return "没有参考文档"




if __name__ == '__main__':
    RPC = RpcClient('192.168.99.36', 7801)
    measure_info = RPC.subMethods_info("power","measure")
    # power.measureCurrentByBattery(20MA,100)
    # ret = RPC.client.stub("power","measureCurrentByBattery","20MA",100)
    # ret = RPC.client.stub("power","measure","PP1V8_SYS",count=400, sample_rate=4000)
    try:
        ret = RPC.client.stub("relay","reset")
        print("*"*100)
        print(ret)
        print("*"*100)
    except Exception as e:
        print("*"*100)
        print(e)
        print("*"*100)
    print(measure_info)


