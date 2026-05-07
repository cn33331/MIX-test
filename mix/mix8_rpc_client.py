#!/usr/bin/env python3
"""
RPC客户端 - 原始实现版本
不依赖第三方库，使用纯ZeroMQ + JSON-RPC实现
与 mix8 设备通信
"""
import sys
import time
import os
import platform
import logging
import json
import uuid
import socket
from logging.handlers import RotatingFileHandler

# 导入ZeroMQ
import zmq

# 初始化日志
def init_logger(file_path):
    max_size = 5 * 1000 * 1000  # ~5MB
    logger = logging.getLogger("RpcClient")
    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(file_path, mode='a', maxBytes=max_size, backupCount=5)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

class JsonRpcClient:
    """
    纯ZeroMQ实现的JSON-RPC客户端
    兼容 mix8 设备的 MIX_2.0 协议
    使用 DEALER 套接字与 ROUTER 服务器通信
    """
    
    def __init__(self, xavier_ip, xavier_port):
        self.xavier_ip = xavier_ip
        self.xavier_port = xavier_port
        self.system = platform.system()
        self.socket = None
        self.context = None
        self.connected = False
        self.logger = init_logger(os.path.expanduser("~/rpcClient.log"))
        self.all_method_doc = {}
        self.request_id = 0
        self.client_identity = f"client_{uuid.uuid4().hex[:8]}"
        
        # 连接到服务器
        self.connect()
    
    def _generate_request_id(self):
        """生成唯一的请求ID（使用时间戳纳秒）"""
        return time.monotonic_ns()
    
    def ping(self, ip, port=None):
        """
        检测IP是否可达
        使用socket直接尝试建立TCP连接，比系统ping命令更快
        """
        try:
            target_port = port if port else self.xavier_port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((ip, target_port))
            sock.close()
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
                self.logger.info(f'{self.xavier_ip} 网络不可达')
                self.connected = False
                return False
            
            # 创建ZeroMQ上下文和socket
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.DEALER)
            self.socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5秒超时
            self.socket.setsockopt(zmq.SNDTIMEO, 3000)  # 3秒发送超时
            self.socket.setsockopt(zmq.IDENTITY, self.client_identity.encode('utf8'))
            
            # 连接到服务器
            server_url = f"tcp://{self.xavier_ip}:{self.xavier_port}"
            self.socket.connect(server_url)
            self.logger.info(f"连接到服务器: {server_url}")
            
            # 验证连接
            if self._test_connection():
                # 向服务器注册客户端身份（兼容MIX8D协议）
                try:
                    self.stub("__MIX_CLIENT_MANAGER__", "hello", "MIX8D")
                    self.logger.info("客户端身份已注册: MIX8D")
                except Exception as e:
                    self.logger.warning(f"注册客户端身份失败: {e}")
                
                self.connected = True
                self.logger.info(f"成功连接到 {self.xavier_ip}:{self.xavier_port}")
                return True
            else:
                self.connected = False
                return False
                
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            self.connected = False
            return False
    
    def _test_connection(self):
        """
        测试连接是否正常
        """
        try:
            # 获取服务器版本
            result = self._send_request("__server__", "version", [])
            if result is not None:
                self.server_version = result
                self.logger.info(f"服务器版本: {result}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"连接测试失败: {e}")
            return False
    
    def _send_request(self, remote_id, method, params, rpc_timeout=None):
        """
        发送JSON-RPC请求（MIX_2.0协议）
        
        DEALER -> ROUTER 通信格式:
        - 发送: [empty_frame, request_data]  (DEALER会自动添加client_id)
        - 接收: [empty_frame, response_data] (DEALER会自动移除client_id)
        
        Args:
            remote_id: 服务ID
            method: 方法名
            params: 参数列表
            rpc_timeout: 超时时间（秒）
        """
        try:
            if not self.socket:
                raise Exception("未建立连接")
            
            # 构建请求（MIX_2.0协议格式）
            request = {
                "version": "MIX_2.0",
                "id": self._generate_request_id(),
                "remote_id": remote_id,
                "method": method,
                "args": params
            }
            
            # 发送请求（DEALER格式: [empty, request_data]）
            request_data = json.dumps(request).encode('utf8')
            self.socket.send_multipart([b'', request_data])
            
            # 设置接收超时
            if rpc_timeout:
                self.socket.setsockopt(zmq.RCVTIMEO, int(rpc_timeout * 1000))
            
            # 接收响应（DEALER格式: [empty, response_data]）
            try:
                msg_parts = self.socket.recv_multipart()
                # DEALER会自动移除client_id，返回 [empty, response] 或直接 response
                if len(msg_parts) >= 2:
                    response_data = msg_parts[1]
                else:
                    response_data = msg_parts[0]
                response = json.loads(response_data.decode('utf8'))
            except zmq.error.Again:
                raise Exception("请求超时")
            
            # 恢复默认超时
            if rpc_timeout:
                self.socket.setsockopt(zmq.RCVTIMEO, 5000)
            
            # 检查响应
            if "error" in response:
                error_info = response["error"]
                raise Exception(f"RPC错误: {error_info.get('message', error_info)}")
            
            return response.get("result")
            
        except Exception as e:
            raise Exception(f"发送请求失败: {e}")
    
    def stub(self, service, method, *args, **kwargs):
        """
        调用远程方法
        """
        try:
            # 构建参数列表
            params = list(args)
            if kwargs:
                params.append(kwargs)
            
            # 发送请求
            result = self._send_request(service, method, params)
            
            # 记录日志（格式化JSON）
            self.logger.info(f"send:{service}.{method}")
            self.logger.info(f"recv:{json.dumps(result, indent=2, ensure_ascii=False)}")
            
            return result
            
        except Exception as e:
            raise Exception(f"调用远程方法失败: {e}")
    
    def list_remote_services(self):
        """
        获取所有可调用服务
        """
        try:
            # 调用 __server__ 服务的 get_all_services 方法
            result = self.stub("__server__", "get_all_services")
            if isinstance(result, (list, tuple)):
                return list(result)
            return []
        except Exception as e:
            self.logger.error(f"获取服务列表失败: {e}")
            return []
    
    def _list_remote_services(self):
        """
        获取所有可调用方法（带日志输出）
        """
        services = self.list_remote_services()
        self.logger.info(f"「 {self.xavier_port}」可调用的服务列表：{services}")
        return services
    
    def get_service_info(self, service_name):
        """
        获取服务信息
        """
        try:
            # 调用__server__服务的get_service_info方法
            result = self.stub('__server__', 'get_service_info', service_name)
            if isinstance(result, dict) and 'methods' in result:
                return result
            return {"methods": {}}
        except Exception as e:
            self.logger.error(f"获取服务信息失败: {e}")
            return {"methods": {}}
    
    def methods_info(self, obj_id):
        """
        获取对象的所有方法信息
        """
        self.all_method_doc[obj_id] = {}
        self.methodsObj = self.get_service_info(obj_id)
        self.subMethods = list(self.methodsObj['methods'].keys())
        
        for method in self.subMethods:
            if '__doc__' in self.methodsObj['methods'][method]:
                doc = self.methodsObj['methods'][method]['__doc__']
                clean_doc = doc.replace('\n:', '\n\t\t\t')
                self.all_method_doc[obj_id][method] = clean_doc
        
        return self.methodsObj, self.subMethods
    
    def subMethods_info(self, obj_id, method_name):
        """
        获取指定方法的文档
        """
        if obj_id not in self.all_method_doc:
            self.methods_info(obj_id)
        
        if method_name in self.all_method_doc.get(obj_id, {}):
            return self.all_method_doc[obj_id][method_name]
        else:
            return "没有参考文档"
    
    def get_server_version(self):
        """
        获取服务器版本
        """
        try:
            return self.stub("__server__", "version")
        except Exception as e:
            self.logger.error(f"获取服务器版本失败: {e}")
            return None
    
    def get_server_state(self):
        """
        获取服务器状态
        """
        try:
            return self.stub("__server__", "get_state")
        except Exception as e:
            self.logger.error(f"获取服务器状态失败: {e}")
            return None
    
    def close(self):
        """
        关闭连接
        """
        try:
            if self.socket:
                self.socket.close()
                self.socket = None
            
            if self.context:
                self.context.term()
                self.context = None
            
            self.connected = False
            self.logger.info("连接已关闭")
            
        except Exception as e:
            self.logger.error(f"关闭连接失败: {e}")

# 保持向后兼容的别名
RpcClient = JsonRpcClient

if __name__ == '__main__':
    # 创建客户端实例
    client = RpcClient('127.0.0.1', 7801)
    
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
            print(json.dumps(ret, indent=2, ensure_ascii=False))
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