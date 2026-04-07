#!/usr/bin/env python3
"""
Mix7 RPC客户端
基于ZeroMQ实现，参考mix8_rpc_client.py的接口
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

class Mix7RpcClient:
    def __init__(self, ip_tester='169.254.1.32', port_tester='7801'):
        self.ip_tester = ip_tester
        self.port_tester = port_tester
        self.system = platform.system()
        self.context = None
        self.socket = None
        self.connected = False
        self.all_method_doc = {}
        
        # 初始化日志
        self.logger = init_logger(os.path.expanduser("~/mix7_rpc_client.log"))
        
        # 连接到服务器
        self.connect()
    
    def ping(self, ip):
        """
        检测IP是否可达
        """
        try:
            if self.system == "Windows":
                ret_ping = os.popen('ping -w 4 {}'.format(ip))
            elif self.system == "Darwin":
                ret_ping = os.popen('ping -c 2 -i 2 -W 2 {}'.format(ip))
            else:
                ret_ping = os.popen('ping -c 2 -i 2 -W 2 {}'.format(ip))
            
            ret_ping_info = ret_ping.read()
            if "TTL" in ret_ping_info or "trip" in ret_ping_info:
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Ping测试失败: {e}")
            return False
    
    def connect(self):
        """
        连接到服务器
        """
        try:
            # 先进行网络检测
            if not self.ping(self.ip_tester):
                self.logger.info(f'{self.ip_tester} tester ping fail')
                self.connected = False
                return False
            
            # 初始化ZeroMQ连接
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.DEALER)
            
            # Mix7使用双端口连接
            request_endpoint = f"tcp://{self.ip_tester}:{self.port_tester}"
            self.socket.connect(request_endpoint)
            
            # 检查连接
            self._check_version()
            self.connected = True
            self.logger.info(f"成功连接到 {self.ip_tester}:{self.port_tester}")
            return True
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            self.connected = False
            return False
    
    def _check_version(self):
        """
        检查服务器版本
        """
        try:
            request = {
                "version": "MIX_2.0",
                "id": int(time.time() * 1000000),
                "remote_id": "__server__",
                "method": "version"
            }
            response = self._send_request(request)
            if "result" in response:
                self.server_version = response["result"]
                self.logger.info(f"服务器版本: {self.server_version}")
                print(f"服务器版本: {self.server_version}")
            else:
                self.logger.warning(f"获取服务器版本失败: {response.get('error', 'Unknown error')}")
                print(f"获取服务器版本失败: {response.get('error', 'Unknown error')}")
        except Exception as e:
            self.logger.error(f"检查版本失败: {e}")
    
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
            self.logger.warning(f"获取服务列表失败: {response.get('error', 'Unknown error')}")
            print(f"获取服务列表失败: {response.get('error', 'Unknown error')}")
            return []
    
    def _list_remote_services(self):
        """
        获取所有可调用方法
        """
        services = self.list_remote_services()
        print(f"「 {self.port_tester}」可调用的方法列表：{services}")
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
            self.logger.warning(f"获取服务信息失败: {response.get('error', 'Unknown error')}")
            print(f"获取服务信息失败: {response.get('error', 'Unknown error')}")
            return {"methods": {}}
    
    def methods_info(self, obj_id):
        """
        打印可调用对象的所有方法的使用说明文档和传参指引
        """
        self.all_method_doc[obj_id] = {}
        self.methodsObj = self.get_service_info(obj_id)
        self.subMethods = list(self.methodsObj['methods'].keys())
        for methods in self.subMethods:
            if self.methodsObj['methods'][methods]['__doc__']:
                doc = self.methodsObj['methods'][methods]['__doc__'].replace('\n:' and '\n', '\n\t\t\t')
                self.all_method_doc[obj_id][methods] = doc
            else:
                pass
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
            error_msg = response.get('error', 'Unknown error')
            self.logger.error(f"调用方法失败: {error_msg}")
            raise Exception(error_msg)
    
    def call_tester(self, method, *args, **kwargs):
        """
        调用测试设备方法（保持与原Mix7接口兼容）
        """
        return self.stub(method.split('.')[0], method.split('.')[1], *args, **kwargs)
    
    def send_rpc(self, method, *args, **kwargs):
        """
        发送通用RPC调用
        """
        try:
            data_dict = self.call_tester(method, *args, **kwargs)
            return data_dict
        except Exception as e:
            self.logger.error(f"发送RPC失败: {e}")
            return None
    
    def close(self):
        """
        关闭连接
        """
        try:
            # 发送bye消息
            request = {
                "version": "MIX_2.0",
                "id": int(time.time() * 1000000),
                "remote_id": "__MIX_CLIENT_MANAGER__",
                "method": "bye"
            }
            self._send_request(request)
            
            # 关闭套接字和上下文
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            
            self.connected = False
            self.logger.info("连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭连接失败: {e}")

if __name__ == '__main__':
    # 测试代码
    # 通过IP连接
    client = Mix7RpcClient('127.0.0.1', '7801')
    
    if client.connected:
        try:
            # 测试获取服务列表
            services = client._list_remote_services()
            print(f"服务列表: {services}")
            
            # 测试获取方法文档
            if 'power' in services:
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
            
            # 测试通用RPC调用
            print("\n测试通用RPC调用:")
            ret = client.send_rpc("relay.reset")
            print(f"通用RPC调用结果: {ret}")
            
        except Exception as e:
            print("*"*100)
            print(f"错误: {e}")
            print("*"*100)
        finally:
            # 关闭连接
            client.close()
    else:
        print("连接失败，无法执行测试")
