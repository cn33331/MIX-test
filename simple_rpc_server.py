#!/usr/bin/env python3
"""
简化版RPC服务器
不依赖于mix.driver模块
使用ZeroMQ ROUTER套接字实现基本的RPC功能
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
        return "3.0.0"  # 返回格式为 major.minor.revision，与客户端匹配
    
    def get_service_info(self, service_name):
        """
        获取服务信息
        """
        return {
            "methods": {
                "measure": {
                    "__doc__": "测量指定通道的电压或电流",
                    "params": ["channel", "count", "sample_rate"]
                },
                "measureCurrentByBattery": {
                    "__doc__": "测量电池电流",
                    "params": ["current", "duration"]
                },
                "reset": {
                    "__doc__": "重置继电器",
                    "params": []
                },
                "set_state": {
                    "__doc__": "设置继电器状态",
                    "params": ["relay_id", "state"]
                }
            }
        }
    
    def get_all_services(self):
        """
        获取所有服务
        """
        return ("power", "relay")

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

class SimpleRPCServer:
    def __init__(self, host="0.0.0.0", port=7801):
        self.host = host
        self.port = port
        self.context = zmq.Context()
        # 使用 ROUTER 套接字来与 DEALER 客户端通信
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind(f"tcp://{host}:{port}")
        self.services = {}
        self.running = False
        self.server_thread = None
        
        # 注册服务器服务
        self.register_service("__server__", ServerService())
        self.register_service("__MIX_CLIENT_MANAGER__", ClientManagerService())
    
    def register_service(self, service_name, service):
        """
        注册服务
        """
        self.services[service_name] = service
    
    def _process_request(self, request_data):
        """
        处理请求
        """
        try:
            data = json.loads(request_data)
            
            # 检查是否是 mix8 客户端的请求格式
            if "remote_id" in data and "method" in data:
                # mix8 客户端格式
                service_name = data.get("remote_id")
                method_name = data.get("method")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
            elif "service" in data and "method" in data:
                # 标准格式
                service_name = data.get("service")
                method_name = data.get("method")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
            elif "obj" in data and "func" in data:
                # 另一种格式
                service_name = data.get("obj")
                method_name = data.get("func")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
            else:
                return {"error": "Invalid request format"}
            
            if not service_name or not method_name:
                return {"error": "Missing service or method"}
            
            if service_name not in self.services:
                return {"error": f"Service {service_name} not found"}
            
            service = self.services[service_name]
            if not hasattr(service, method_name):
                return {"error": f"Method {method_name} not found in service {service_name}"}
            
            method = getattr(service, method_name)
            result = method(*args, **kwargs)
            
            # 检查是否需要返回特定格式
            if "id" in data:
                return {
                    "version": "MIX_2.0",
                    "request_id": data.get("id"),
                    "result": result
                }
            else:
                return {"result": result}
        except Exception as e:
            # 检查是否需要返回特定格式的错误
            try:
                data = json.loads(request_data)
                if "id" in data:
                    return {
                        "version": "MIX_2.0",
                        "request_id": data.get("id"),
                        "error": str(e)
                    }
            except:
                pass
            return {"error": str(e)}
    
    def _run(self):
        """
        运行服务器
        """
        while self.running:
            try:
                # 使用 recv_multipart 接收 DEALER 客户端的消息
                # 格式: [client_identity, target, message]
                msg_parts = self.socket.recv_multipart()
                if len(msg_parts) >= 3:
                    client_id = msg_parts[0]
                    target = msg_parts[1].decode('utf8')
                    request_data = msg_parts[2].decode('utf8')
                    
                    print(f"收到请求 from {client_id}: {request_data}")
                    
                    # 处理请求
                    response = self._process_request(request_data)
                    
                    # 发送响应
                    response_str = json.dumps(response)
                    self.socket.send_multipart([client_id, response_str.encode('utf8')])
                    print(f"发送响应: {response}")
                else:
                    print(f"收到格式错误的消息: {msg_parts}")
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
    
    def stop(self):
        """
        停止服务器
        """
        self.running = False
        if self.server_thread:
            self.server_thread.join(timeout=1)
        self.socket.close()
        self.context.term()

class PowerService:
    """
    电源服务
    """
    def measure(self, channel, count=100, sample_rate=1000):
        """
        测量指定通道的电压或电流
        
        参数:
            channel: 通道名称，如 "PP1V8_SYS"
            count: 测量次数，默认100
            sample_rate: 采样率，默认1000
        
        返回:
            测量结果
        """
        print(f"测量通道: {channel}, 次数: {count}, 采样率: {sample_rate}")
        # 模拟测量结果
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
        
        参数:
            current: 电流值，如 "20MA"
            duration: 测量持续时间
        
        返回:
            测量结果
        """
        print(f"测量电池电流: {current}, 持续时间: {duration}")
        # 模拟测量结果
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
        
        返回:
            操作结果
        """
        print("重置继电器")
        return {"status": "success", "message": "Relay reset"}
    
    def set_state(self, relay_id, state):
        """
        设置继电器状态
        
        参数:
            relay_id: 继电器ID
            state: 状态，"on" 或 "off"
        
        返回:
            操作结果
        """
        print(f"设置继电器 {relay_id} 状态: {state}")
        return {
            "status": "success",
            "relay_id": relay_id,
            "state": state
        }

def main():
    """
    启动RPC服务器
    """
    # 创建服务器实例
    server = SimpleRPCServer("0.0.0.0", 7801)
    
    # 注册服务
    server.register_service("power", PowerService())
    server.register_service("relay", RelayService())
    
    print("RPC服务器已启动，监听端口 7801...")
    print("可用服务:")
    print("  - power: 电源服务")
    print("    * measure(channel, count=100, sample_rate=1000)")
    print("    * measureCurrentByBattery(current, duration)")
    print("  - relay: 继电器服务")
    print("    * reset()")
    print("    * set_state(relay_id, state)")
    
    try:
        # 启动服务器
        server.start()
        # 保持服务器运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭RPC服务器...")
        server.stop()
        print("RPC服务器已关闭")

if __name__ == "__main__":
    main()