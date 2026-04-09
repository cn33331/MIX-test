#!/usr/bin/env python3
"""
测试RPC客户端
直接使用zmq.DEALER而不是ProxyFactory.JsonZmqFactory
"""
import sys
import time
import json
import zmq
import os
import platform
import logging
from logging.handlers import RotatingFileHandler

# 初始化日志
def init_logger(file_path):
    max_size = 5 * 1000 * 1000  # ~5MB
    logger = logging.getLogger("Logger")
    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(file_path, mode='a', maxBytes=max_size, backupCount=5)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

class RpcClient:
    def __init__(self, xavier_ip, xavier_port):
        self.xavier_ip = xavier_ip
        self.xavier_port = xavier_port
        self.system = platform.system()
        self.context = None
        self.socket = None
        self.connected = False
        self.identity = os.urandom(16)
        self.logger = init_logger(os.path.expanduser("~/rpcClient.log"))
        self.all_method_doc = {}
        
        # 连接到服务器
        self.connect()
    
    def ping(self, ip):
        """
        检测IP是否可达
        使用socket直接尝试建立TCP连接，比系统ping命令更快
        """
        try:
            import socket
            # 创建socket连接，使用端口7801（RPC服务端口）
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # 设置1秒超时，比系统ping更快
            result = sock.connect_ex((ip, 7801))
            sock.close()
            # 如果连接成功，result为0
            return result == 0
        except Exception as e:
            self.logger.error(f"网络检测失败: {e}")
            return False
    
    def connect(self):
        """
        连接到服务器
        """
        try:
            # 先进行网络检测
            if not self.ping(self.xavier_ip):
                self.logger.info(f'{self.xavier_ip} tester ping fail')
                self.connected = False
                return False
            
            # 初始化ZeroMQ连接
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.DEALER)
            self.socket.connect(f"tcp://{self.xavier_ip}:{self.xavier_port}")
            
            # 检查连接
            self._check_version()
            self.connected = True
            self.logger.info(f"成功连接到 {self.xavier_ip}:{self.xavier_port}")
            return True
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            self.connected = False
            return False
    
    def _check_version(self):
        """
        检查服务器版本
        """
        request = {
            "version": "MIX_2.0",
            "id": int(time.time() * 1000000),
            "remote_id": "__server__",
            "method": "version"
        }
        response = self._send_request(request)
        if "result" in response:
            self.server_version = response["result"]
            print(f"服务器版本: {self.server_version}")
        else:
            print(f"获取服务器版本失败: {response.get('error', 'Unknown error')}")
    
    def _send_request(self, request):
        """
        发送请求并获取响应
        """
        try:
            # 发送消息格式: [target, message]
            target = b""
            message = json.dumps(request).encode('utf8')
            self.socket.send_multipart([target, message])
            
            # 接收响应
            response_parts = self.socket.recv_multipart()
            if len(response_parts) >= 1:
                response_str = response_parts[0].decode('utf8')
                return json.loads(response_str)
            else:
                return {"error": "Invalid response format"}
        except Exception as e:
            return {"error": str(e)}
    
    def list_remote_services(self):
        """
        获取所有可调用方法
        """
        request = {
            "version": "MIX_2.0",
            "id": int(time.time() * 1000000),
            "remote_id": "__server__",
            "method": "get_all_services"
        }
        response = self._send_request(request)
        if "result" in response:
            return response["result"]
        else:
            print(f"获取服务列表失败: {response.get('error', 'Unknown error')}")
            return []
    
    def _list_remote_services(self):
        """
        获取所有可调用方法
        """
        services = self.list_remote_services()
        print(f"「 {self.xavier_port}」可调用的方法列表：{services}")
        # for x in services:
        #     self.methods_info(x)
        return services
    
    def get_service_info(self, service_name):
        """
        获取服务信息
        """
        request = {
            "version": "MIX_2.0",
            "id": int(time.time() * 1000000),
            "remote_id": "__server__",
            "method": "get_service_info",
            "args": [service_name]
        }
        response = self._send_request(request)
        if "result" in response:
            return response["result"]
        else:
            print(f"获取服务信息失败: {response.get('error', 'Unknown error')}")
            return {"methods": {}}
    
    def methods_info(self, obj_id):
        """
        打印可调用对象的所有方法的使用说明文档和传参指引
        """
        self.all_method_doc[obj_id] = {}
        self.methodsObj = self.get_service_info(obj_id)
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
        return self.methodsObj, self.subMethods
    
    def subMethods_info(self, obj_id, method_name):
        if obj_id in self.all_method_doc:
            pass
        else:
            self.methods_info(obj_id)
        if method_name in self.all_method_doc[obj_id]:
            return self.all_method_doc[obj_id][method_name]
        else:
            return "没有参考文档"
    
    def stub(self, service, method, *args, **kwargs):
        """
        调用远程方法
        """
        request = {
            "version": "MIX_2.0",
            "id": int(time.time() * 1000000),
            "remote_id": service,
            "method": method,
            "args": args,
            "kwargs": kwargs
        }
        response = self._send_request(request)
        if "result" in response:
            return response["result"]
        else:
            raise Exception(response.get('error', 'Unknown error'))
    
    def close(self):
        """
        关闭连接
        """
        # 发送bye消息
        request = {
            "version": "MIX_2.0",
            "id": int(time.time() * 1000000),
            "remote_id": "__MIX_CLIENT_MANAGER__",
            "method": "bye"
        }
        self._send_request(request)
        
        # 关闭套接字和上下文
        self.socket.close()
        self.context.term()

if __name__ == '__main__':
    # 创建客户端实例
    client = RpcClient('127.0.0.1', 7801)
    
    if client.connected:
        try:
            # 测试获取服务列表
            services = client._list_remote_services()
            print(f"服务列表: {services}")
            
            # 测试获取方法文档
            measure_info = client.subMethods_info("power", "measure")
            print(f"power.measure 文档: {measure_info}")
            
            # 测试调用远程方法
            print("\n测试调用 relay.reset():")
            ret = client.stub("relay", "reset")
            print("*"*100)
            print(ret)
            print("*"*100)
            
            # 测试调用带参数的方法
            print("\n测试调用 power.measure():")
            ret = client.stub("power", "measure", "PP1V8_SYS", count=400, sample_rate=4000)
            print("*"*100)
            print(ret)
            print("*"*100)
            
        except Exception as e:
            print("*"*100)
            print(f"错误: {e}")
            print("*"*100)
        finally:
            # 关闭连接
            client.close()
    else:
        print("连接失败，无法执行测试")
