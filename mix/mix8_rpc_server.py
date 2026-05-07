#!/usr/bin/env python3
"""
简化版RPC服务器
不依赖于mix.driver模块
使用ZeroMQ ROUTER套接字实现基本的RPC功能
兼容MIX_2.0协议和JSON-RPC 2.0协议
"""
import sys
import time
import json
import threading
import zmq

class ServerService:
    """
    服务器服务，提供服务器相关的方法
    """
    def version(self):
        """
        返回服务器版本
        """
        return "3.0.0"
    
    def identity(self):
        """
        返回服务器标识
        """
        return "test_server"
    
    def pid(self):
        """
        返回服务器进程ID
        """
        import os
        return os.getpid()
    
    def get_state(self):
        """
        返回服务器状态
        """
        return "SERVING"
    
    def get_all_services(self):
        """
        获取所有服务
        """
        return ("power", "relay", "baseboard")
    
    def get_service_info(self, service_name):
        """
        获取服务信息
        """
        services_info = {
            "power": {
                "methods": {
                    "measure": {
                        "__doc__": "测量指定通道的电压或电流",
                        "params": ["channel", "count", "sample_rate"]
                    },
                    "measureCurrentByBattery": {
                        "__doc__": "测量电池电流",
                        "params": ["current", "duration"]
                    }
                }
            },
            "relay": {
                "methods": {
                    "reset": {
                        "__doc__": "重置继电器",
                        "params": []
                    },
                    "set_state": {
                        "__doc__": "设置继电器状态",
                        "params": ["relay_id", "state"]
                    }
                }
            },
            "baseboard": {
                "methods": {
                    "read_volt": {
                        "__doc__": "读取电压",
                        "params": ["ch", "timeout_ms"]
                    },
                    "read_current": {
                        "__doc__": "读取电流",
                        "params": ["ch", "timeout_ms"]
                    }
                }
            }
        }
        
        if service_name in services_info:
            return services_info[service_name]
        return {"methods": {}}
    
    def get_all_loggers(self):
        """
        获取所有日志器
        """
        return []
    
    def get_config(self, name):
        """
        获取配置
        """
        return None
    
    def set_config(self, name, value):
        """
        设置配置
        """
        return True
    
    def all_methods(self):
        """
        获取所有方法
        """
        methods = []
        for service_name, service in services.items():
            if service_name.startswith("_"):
                continue
            for method_name in dir(service):
                if not method_name.startswith("_"):
                    methods.append(f"{service_name}.{method_name}")
        return methods


class ClientManagerService:
    """
    客户端管理服务，处理客户端连接和断开
    """
    def hello(self, client_identity):
        """
        客户端连接时调用
        """
        print(f"客户端 {client_identity} 已连接")
        return {"status": "success", "session_id": "test_session"}
    
    def bye(self):
        """
        客户端断开时调用
        """
        print("客户端断开连接")
        return {"status": "success"}


class PowerService:
    """
    电源服务
    """
    def measure(self, channel, count=100, sample_rate=1000):
        """
        测量指定通道的电压或电流
        """
        print(f"测量通道: {channel}, 次数: {count}, 采样率: {sample_rate}")
        import random
        return {
            "channel": channel,
            "value": round(random.uniform(1.7, 1.9), 3),
            "unit": "V",
            "count": count,
            "sample_rate": sample_rate
        }
    
    def measureCurrentByBattery(self, current, duration):
        """
        测量电池电流
        """
        print(f"测量电池电流: {current}, 持续时间: {duration}")
        import random
        return {
            "current": current,
            "duration": duration,
            "result": "success",
            "value": round(random.uniform(18, 22), 2)
        }


class RelayService:
    """
    继电器服务
    """
    def reset(self):
        """
        重置继电器
        """
        print("重置继电器")
        return {"status": "success", "message": "Relay reset"}
    
    def set_state(self, relay_id, state):
        """
        设置继电器状态
        """
        print(f"设置继电器 {relay_id} 状态: {state}")
        return {
            "status": "success",
            "relay_id": relay_id,
            "state": state
        }


class BaseboardService:
    """
    主板服务
    """
    def read_volt(self, ch=1, timeout_ms=3000):
        """
        读取电压
        """
        print(f"读取电压: channel={ch}, timeout_ms={timeout_ms}")
        import random
        return {
            "ch": ch,
            "voltage": round(random.uniform(1.7, 1.9), 3),
            "unit": "V",
            "status": "success"
        }
    
    def read_current(self, ch=1, timeout_ms=3000):
        """
        读取电流
        """
        print(f"读取电流: channel={ch}, timeout_ms={timeout_ms}")
        import random
        return {
            "ch": ch,
            "current": round(random.uniform(0, 1), 3),
            "unit": "A",
            "status": "success"
        }


# 全局服务字典（供 all_methods 使用）
services = {}

class SimpleRPCServer:
    """
    简化的RPC服务器
    兼容MIX_2.0协议和JSON-RPC 2.0协议
    """
    def __init__(self, host="0.0.0.0", port=7801):
        global services
        
        self.host = host
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind(f"tcp://{host}:{port}")
        self.services = {}
        self.running = False
        self.server_thread = None
        
        # 注册服务
        self.register_service("__server__", ServerService())
        self.register_service("__MIX_CLIENT_MANAGER__", ClientManagerService())
        self.register_service("power", PowerService())
        self.register_service("relay", RelayService())
        self.register_service("baseboard", BaseboardService())
        
        # 更新全局服务字典
        services = self.services
    
    def register_service(self, service_name, service):
        """
        注册服务
        """
        self.services[service_name] = service
    
    def _process_request(self, request_data, client_id):
        """
        处理请求（支持多种协议格式）
        
        支持的格式：
        1. JSON-RPC 2.0: {"jsonrpc": "2.0", "id": "...", "method": "service.method", "kwargs": {...}}
        2. MIX_2.0: {"version": "MIX_2.0", "id": "...", "remote_id": "...", "method": "...", "args": [...]}
        """
        try:
            data = json.loads(request_data)
            
            # 检测协议格式
            is_jsonrpc2 = "jsonrpc" in data
            is_mix2 = "version" in data and data.get("version") == "MIX_2.0"
            
            if is_jsonrpc2:
                # JSON-RPC 2.0 格式
                request_id = data.get("id")
                method_full = data.get("method")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
                
                # 解析 method: "service.method"
                if "." in method_full:
                    remote_id, method = method_full.split(".", 1)
                else:
                    return self._error_response(request_id, "Method must be in format 'service.method'", is_jsonrpc2=True)
                    
            elif is_mix2:
                # MIX_2.0 格式
                request_id = data.get("id")
                remote_id = data.get("remote_id")
                method = data.get("method")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
                
            else:
                # 默认尝试解析
                request_id = data.get("id")
                method_full = data.get("method")
                if "." in method_full:
                    remote_id, method = method_full.split(".", 1)
                else:
                    remote_id = data.get("remote_id", method_full)
                    method = data.get("method", "")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
            
            if not remote_id or not method:
                return self._error_response(request_id, "Missing service or method", is_jsonrpc2)
            
            if remote_id not in self.services:
                return self._error_response(request_id, f"Service {remote_id} not found", is_jsonrpc2)
            
            service = self.services[remote_id]
            if not hasattr(service, method):
                return self._error_response(request_id, f"Method {method} not found in service {remote_id}", is_jsonrpc2)
            
            # 调用方法
            method_func = getattr(service, method)
            
            # 处理参数
            if kwargs and isinstance(kwargs, dict) and len(kwargs) > 0:
                result = method_func(*args, **kwargs)
            else:
                result = method_func(*args)
            
            # 返回响应（根据请求格式返回对应格式）
            if is_jsonrpc2:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
            else:
                return {
                    "version": "MIX_2.0",
                    "request_id": request_id,
                    "result": result
                }
            
        except Exception as e:
            try:
                data = json.loads(request_data)
                request_id = data.get("id")
                is_jsonrpc2 = "jsonrpc" in data
            except:
                request_id = None
                is_jsonrpc2 = False
            
            return self._error_response(request_id, str(e), is_jsonrpc2)
    
    def _error_response(self, request_id, error_msg, is_jsonrpc2=False):
        """
        创建错误响应
        """
        if is_jsonrpc2:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": error_msg}
            }
        else:
            response = {
                "version": "MIX_2.0",
                "error": {
                    "code": -32603,
                    "message": error_msg
                }
            }
            if request_id is not None:
                response["request_id"] = request_id
            return response
    
    def _run(self):
        """
        运行服务器
        """
        while self.running:
            try:
                # 接收消息（ROUTER套接字格式：[client_id, empty, message]）
                msg_parts = self.socket.recv_multipart()
                
                if len(msg_parts) >= 2:
                    client_id = msg_parts[0]
                    # 处理不同的消息格式
                    if len(msg_parts) >= 3:
                        # 标准 ROUTER 格式：[client_id, empty, message]
                        request_data = msg_parts[2].decode('utf8')
                    else:
                        # 可能只有 [client_id, message]
                        request_data = msg_parts[1].decode('utf8')
                    
                    print(f"收到请求 from {client_id.hex()[:8]}: {request_data[:100]}...")
                    
                    # 处理请求
                    response = self._process_request(request_data, client_id)
                    
                    # 发送响应（ROUTER格式：[client_id, empty, response]）
                    response_str = json.dumps(response)
                    self.socket.send_multipart([
                        client_id,
                        b'',
                        response_str.encode('utf8')
                    ])
                    print(f"发送响应: {str(response)[:100]}...")
                    
            except zmq.ZMQError as e:
                if self.running:
                    print(f"ZMQ错误: {e}")
            except Exception as e:
                print(f"错误: {e}")
    
    def start(self):
        """
        启动服务器
        """
        self.running = True
        self.server_thread = threading.Thread(target=self._run)
        self.server_thread.daemon = True
        self.server_thread.start()
        print(f"RPC服务器已启动，监听端口 {self.port}")
    
    def stop(self):
        """
        停止服务器
        """
        self.running = False
        if self.server_thread:
            self.server_thread.join(timeout=1)
        self.socket.close()
        self.context.term()
        print("RPC服务器已关闭")


def main():
    """
    启动RPC服务器
    """
    server = SimpleRPCServer("0.0.0.0", 7801)
    
    print("可用服务:")
    print("  - __server__: 服务器服务")
    print("    * version()")
    print("    * get_all_services()")
    print("    * get_service_info(service_name)")
    print("    * get_state()")
    print("    * all_methods()")
    print("  - power: 电源服务")
    print("    * measure(channel, count=100, sample_rate=1000)")
    print("    * measureCurrentByBattery(current, duration)")
    print("  - relay: 继电器服务")
    print("    * reset()")
    print("    * set_state(relay_id, state)")
    print("  - baseboard: 主板服务")
    print("    * read_volt(ch=1, timeout_ms=3000)")
    print("    * read_current(ch=1, timeout_ms=3000)")
    
    try:
        server.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭RPC服务器...")
        server.stop()


if __name__ == "__main__":
    main()