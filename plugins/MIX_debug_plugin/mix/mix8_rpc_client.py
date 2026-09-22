#!/usr/bin/env python3
"""MIX8 RPC客户端模块。

纯ZeroMQ + JSON-RPC实现的MIX_2.0协议客户端，用于与MIX8设备进行通信。
使用DEALER套接字与ROUTER服务器通信，支持服务发现、方法调用等功能。

主要特性：
- 纯Python实现，无外部依赖（除ZeroMQ）
- 兼容MIX_2.0协议
- 支持客户端自动注册
- 完整的错误处理和日志记录
"""

import sys
import time
import os
import platform
import json
import uuid
import socket

# 导入ZeroMQ
import zmq

# 添加utils目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import init_logger


class JsonRpcClient:
    """MIX8设备JSON-RPC通信客户端类。

    使用纯ZeroMQ实现的JSON-RPC客户端，兼容MIX_2.0协议。
    通过DEALER套接字与ROUTER服务器通信，支持自动注册、服务发现和方法调用。

    Attributes:
        xavier_ip: 目标设备IP地址
        xavier_port: 目标设备端口号
        system: 操作系统类型
        socket: ZeroMQ DEALER套接字
        context: ZeroMQ上下文
        connected: 连接状态标志
        logger: 日志记录器
        all_method_doc: 方法文档缓存字典
        request_id: 请求ID计数器
        server_version: 服务器版本信息

    Example:
        >>> client = JsonRpcClient('192.168.1.100', 7801)
        >>> if client.connected:
        ...     services = client.list_remote_services()
        ...     result = client.stub("system", "version")
        ...     print(f"服务器版本: {result}")
        ...     client.close()
    """
    
    def __init__(self, xavier_ip, xavier_port):
        """初始化JSON-RPC客户端并建立连接。

        Args:
            xavier_ip: MIX8设备IP地址
            xavier_port: MIX8设备端口号

        Note:
            构造函数会自动尝试建立连接，连接失败时connected属性为False
        """
        self.xavier_ip = xavier_ip
        self.xavier_port = xavier_port
        self.system = platform.system()
        self.socket = None
        self.context = None
        self.connected = False
        self.logger = init_logger(name="RpcClient", log_file="rpc.log")
        self.all_method_doc = {}
        self.request_id = 0
        
        # 连接到服务器
        self.connect()
    
    def _generate_request_id(self):
        """生成唯一的请求ID。

        使用UUID生成唯一的请求标识符，确保每个请求都有唯一的ID。

        Returns:
            str: UUID格式的请求ID字符串
        """
        return uuid.uuid4().hex
    
    def ping(self, ip, port=None):
        """检测目标IP和端口是否可达。

        使用TCP socket直接尝试建立连接，比系统ping命令更快且更可靠。
        适用于检测服务器是否正在监听指定端口。

        Args:
            ip: 目标IP地址
            port: 目标端口号，默认为None时使用xavier_port

        Returns:
            bool: True表示端口可达，False表示不可达

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> if client.ping('192.168.1.100', 7801):
            ...     print("目标可达")
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
        """连接到MIX8设备服务器。

        执行完整的连接流程，包括：
        1. 网络连通性检测
        2. ZeroMQ上下文和socket创建
        3. TCP连接建立
        4. 连接验证
        5. 客户端身份注册（MIX_2.0协议要求）

        Returns:
            bool: 连接是否成功，True表示成功，False表示失败

        Warning:
            连接过程包含最多3次注册重试机制，每次间隔0.5秒
        """
        self.logger.info("="*60)
        self.logger.info(f"开始连接到服务器: {self.xavier_ip}:{self.xavier_port}")
        self.logger.info("="*60)
        
        try:
            # 先进行网络检测
            self.logger.info(f"[步骤1] 检测网络连通性...")
            if not self.ping(self.xavier_ip):
                self.logger.error(f"[步骤1] FAILED - {self.xavier_ip} 网络不可达")
                self.connected = False
                return False
            self.logger.info(f"[步骤1] SUCCESS - {self.xavier_ip} 网络可达")
            
            # 创建ZeroMQ上下文和socket
            self.logger.info("[步骤2] 创建ZeroMQ上下文和socket...")
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.DEALER)
            self.socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5秒超时
            self.socket.setsockopt(zmq.SNDTIMEO, 3000)  # 3秒发送超时
            # 不手动设置IDENTITY，让zmq自动生成短身份标识（与标准RPC客户端保持一致）
            self.logger.info("[步骤2] SUCCESS - ZeroMQ socket创建成功")
            
            # 连接到服务器
            server_url = f"tcp://{self.xavier_ip}:{self.xavier_port}"
            self.logger.info(f"[步骤3] 连接到服务器: {server_url}")
            self.socket.connect(server_url)
            self.logger.info(f"[步骤3] SUCCESS - 已连接到 {server_url}")
            
            # 验证连接
            self.logger.info("[步骤4] 验证连接...")
            if self._test_connection():
                self.logger.info("[步骤4] SUCCESS - 连接验证通过")
                
                # 向服务器注册客户端身份（兼容MIX8D协议）
                self.logger.info("[步骤5] 注册客户端身份...")
                max_retries = 3
                registered = False
                
                self.logger.info(f"  最多重试 {max_retries} 次")
                for attempt in range(max_retries):
                    try:
                        self.logger.info(f"  注册尝试 {attempt + 1}/{max_retries}")
                        self.stub("__MIX_CLIENT_MANAGER__", "hello", "MIX8D")
                        self.logger.info(f"  SUCCESS - 客户端身份已注册: MIX8D")
                        registered = True
                        break
                    except Exception as e:
                        self.logger.error(f"  FAILED (尝试 {attempt+1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            self.logger.info(f"  等待 0.5 秒后重试...")
                            time.sleep(0.5)
                
                if registered:
                    self.logger.info("[步骤5] SUCCESS - 客户端注册成功")
                    self.connected = True
                    self.logger.info(f"="*60)
                    self.logger.info(f"成功连接到 {self.xavier_ip}:{self.xavier_port}")
                    self.logger.info("="*60)
                    return True
                else:
                    self.logger.error("[步骤5] FAILED - 注册客户端身份失败，无法继续")
                    self.logger.info("="*60)
                    self.connected = False
                    return False
            else:
                self.logger.error("[步骤4] FAILED - 连接验证失败")
                self.logger.info("="*60)
                self.connected = False
                return False
                
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            self.logger.info("="*60)
            self.connected = False
            return False
    
    def _test_connection(self):
        """测试与服务器的连接是否正常。

        通过调用 __server__ 服务的 version 方法来验证连接。

        Returns:
            bool: True表示连接正常，False表示连接失败

        Raises:
            无异常抛出，错误通过返回值体现
        """
        try:
            # 获取服务器版本
            self.logger.debug(f"  发送请求: __server__.version()")
            result = self._send_request("__server__", "version", [])
            if result is not None:
                self.server_version = result
                self.logger.debug(f"  响应: {result}")
                return True
            self.logger.debug(f"  响应为空")
            return False
        except Exception as e:
            self.logger.error(f"  连接测试失败: {e}")
            return False
    
    def _send_request(self, remote_id, method, params, rpc_timeout=None):
        """发送JSON-RPC请求（MIX_2.0协议）。

        使用DEALER套接字发送请求到ROUTER服务器。
        自动处理客户端注册、请求序列化、响应反序列化和错误处理。

        DEALER -> ROUTER 通信格式:
        - 发送: [remote_id, request_data]
        - 接收: [empty_frame, response_data]

        Args:
            remote_id: 服务ID，如 "__server__"、"power" 等
            method: 方法名称
            params: 参数列表
            rpc_timeout: 超时时间（秒），可选，默认为None

        Returns:
            Any: 服务器返回的结果

        Raises:
            Exception: 网络错误、超时、RPC错误等

        Warning:
            对于业务服务（非系统服务），会自动检查并重新注册客户端身份
        """
        try:
            if not self.socket:
                raise Exception("未建立连接")
            
            # 对于业务服务（非系统服务），确保已注册
            if remote_id not in ["__server__", "__MIX_CLIENT_MANAGER__"]:
                self.logger.debug(f"  业务服务请求，先检查注册状态")
                try:
                    self.stub("__MIX_CLIENT_MANAGER__", "hello", "MIX8D")
                    self.logger.debug(f"  注册检查通过")
                except Exception as e:
                    raise Exception(f"客户端未注册，且注册失败: {e}")
            
            # 构建请求（兼容标准JSON-RPC格式）
            request = {
                "id": self._generate_request_id(),
                "remote_id": remote_id,
                "method": method
            }
            # 如果有参数，添加args字段
            if params:
                request["args"] = params
            
            # 发送请求（DEALER -> ROUTER 格式: [remote_id, request_data]）
            # DEALER会自动在前面添加client_id，ROUTER收到的格式是: [client_id, remote_id, request_data]
            request_data = json.dumps(request).encode('utf8')
            self.socket.send_multipart([remote_id.encode('utf8'), request_data])
            
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
                self.logger.error(f"  请求超时")
                raise Exception("请求超时")
            
            # 恢复默认超时
            if rpc_timeout:
                self.socket.setsockopt(zmq.RCVTIMEO, 5000)
            
            # 检查响应
            if "error" in response:
                error_info = response["error"]
                error_msg = f"RPC错误: {error_info.get('message', error_info)}"
                self.logger.error(f"  {error_msg}")
                raise Exception(error_msg)
            
            result = response.get("result")
            return result
            
        except Exception as e:
            raise Exception(f"发送请求失败: {e}")
    
    def stub(self, service, method, *args, rpc_timeout=None, **kwargs):
        """调用远程服务方法。

        便捷方法，用于调用指定服务的指定方法。自动处理参数转换和结果记录。

        Args:
            service: 服务名称，如 "system"、"power"、"relay" 等
            method: 方法名称
            *args: 位置参数，会被转换为浮点数（如果可能）
            rpc_timeout: 超时时间（秒），可选
            **kwargs: 关键字参数，会作为最后一个参数附加

        Returns:
            Any: 远程方法调用的结果

        Raises:
            Exception: 调用失败时抛出异常

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> # 无参数调用
            >>> result = client.stub("system", "version")
            >>> # 有参数调用
            >>> result = client.stub("power", "measure", 1, 100)
            >>> # 关键字参数
            >>> result = client.stub("config", "set", name="value")
        """
        try:
            # 构建参数列表
            params = []
            if args:
                params = list(args)
            params = self.to_float(params)
            if kwargs:
                params.append(kwargs)
            
            # 发送请求
            result = self._send_request(service, method, params, rpc_timeout=rpc_timeout)
            
            if method != "get_service_info" and method != "get_all_services":
                # 记录日志（格式化JSON）
                self.logger.info(f"send:{service}.{method}")
                self.logger.info(f"recv:{json.dumps(result, indent=2, ensure_ascii=False)}")
            
            return result
            
        except Exception as e:
            raise Exception(f"调用远程方法失败: {e}")
    
    def list_remote_services(self):
        """获取所有可调用的远程服务列表。

        Returns:
            list: 服务名称列表，如 ["system", "power", "relay", ...]
            连接失败时返回空列表

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> services = client.list_remote_services()
            >>> print(f"可用服务: {services}")
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
        """获取所有可调用服务（带详细日志输出）。

        与list_remote_services功能相同，但会输出更详细的日志信息，
        包括服务数量和完整的服务器地址信息。

        Returns:
            list: 服务名称列表

        Note:
            此方法主要用于调试，正常使用建议使用list_remote_services
        """
        services = self.list_remote_services()
        self.logger.info(f"「 {self.xavier_port}」可调用的服务列表：{services}")
        return services
    
    def get_service_info(self, service_name):
        """获取指定服务的详细信息。

        Args:
            service_name: 服务名称

        Returns:
            dict: 服务信息字典，包含 'methods' 键及其下的所有方法信息
            格式: {"methods": {"method1": {...}, "method2": {...}}}

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> info = client.get_service_info("power")
            >>> for method, details in info['methods'].items():
            ...     print(f"方法: {method}")
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
        """获取对象的完整方法信息。

        获取指定服务/对象的名称、方法和子方法列表。
        结果会缓存到all_method_doc和methodsObj/subMethods属性中。

        Args:
            obj_id: 服务/对象ID

        Returns:
            tuple: (methods_obj, sub_methods)
                - methods_obj: 方法对象字典，包含 'methods' 键
                - sub_methods: 方法名称列表

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> methods_obj, sub_methods = client.methods_info("power")
            >>> print(f"power服务有 {len(sub_methods)} 个方法")
        """
        self.all_method_doc[obj_id] = {}
        self.methodsObj = self.get_service_info(obj_id)
        self.subMethods = list(self.methodsObj['methods'].keys())
        return self.methodsObj, self.subMethods
    
    def subMethods_info(self, obj_id, method_name):
        """获取指定方法的文档字符串。

        Args:
            obj_id: 服务/对象ID
            method_name: 方法名称

        Returns:
            str: 方法的文档字符串，如果不存在则返回"没有参考文档"

        Note:
            如果obj_id不在缓存中，会先调用methods_info加载
        """
        if obj_id not in self.all_method_doc:
            self.methods_info(obj_id)
        
        if method_name in self.all_method_doc.get(obj_id, {}):
            return self.all_method_doc[obj_id][method_name]
        else:
            return "没有参考文档"
    
    def get_server_version(self):
        """获取MIX8服务器的软件版本号。

        Returns:
            str or None: 服务器版本字符串，失败时返回None

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> version = client.get_server_version()
            >>> print(f"服务器版本: {version}")
        """
        try:
            return self.stub("__server__", "version")
        except Exception as e:
            self.logger.error(f"获取服务器版本失败: {e}")
            return None
    
    def get_server_state(self):
        """获取MIX8服务器的当前状态。

        Returns:
            dict or None: 服务器状态字典，失败时返回None

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> state = client.get_server_state()
        """
        try:
            return self.stub("__server__", "get_state")
        except Exception as e:
            self.logger.error(f"获取服务器状态失败: {e}")
            return None
    
    def close(self):
        """关闭RPC连接。

        执行优雅关闭：
        1. 发送bye消息通知服务器（兼容MIX_2.0协议）
        2. 关闭ZeroMQ socket
        3. 终止ZeroMQ上下文
        4. 重置connected状态为False

        Warning:
            关闭后如需再次使用，需要重新创建JsonRpcClient实例

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> # ... 使用客户端 ...
            >>> client.close()  # 关闭连接
        """
        try:
            if self.socket:
                # 发送断开通知（兼容MIX_2.0协议）
                try:
                    self.stub("__MIX_CLIENT_MANAGER__", "bye")
                    self.logger.info("已发送断开通知")
                except Exception as e:
                    self.logger.warning(f"发送断开通知失败: {e}")
                
                self.socket.close()
                self.socket = None
            
            if self.context:
                self.context.term()
                self.context = None
            
            self.connected = False
            self.logger.info("连接已关闭")
            
        except Exception as e:
            self.logger.error(f"关闭连接失败: {e}")

    def to_float(self, test_list):
        """将列表中的元素尝试转换为浮点数。

        遍历列表，尝试将每个元素转换为float类型。
        如果转换失败，保持原值不变。

        Args:
            test_list: 输入列表

        Returns:
            list: 转换后的列表

        Example:
            >>> client = JsonRpcClient('192.168.1.100', 7801)
            >>> result = client.to_float(['1', '2.5', 'hello', '100'])
            >>> # result = [1.0, 2.5, 'hello', 100.0]
        """
        pass_list = []
        for test in test_list:
            try:
                test = float(test)
            except Exception as e:
                pass
            pass_list.append(test)
        return pass_list


# 保持向后兼容的别名
RpcClient = JsonRpcClient


if __name__ == '__main__':
    """模块自测代码。

    创建客户端实例并执行以下测试：
    1. 获取服务列表
    2. 获取方法文档
    3. 调用远程方法
    """
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