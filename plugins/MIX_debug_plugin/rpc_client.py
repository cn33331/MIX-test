"""RPC客户端模块。

提供MIX8设备的RPC通信功能，支持服务发现、命令发送、连接管理等功能。
该模块是对底层mix8_rpc_client的封装，提供更友好的接口和错误处理。
"""

import sys
import os

# 插件目录路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

class RpcClient:
    """MIX8设备RPC通信客户端类。

    封装MIX8设备的RPC连接和命令发送功能，支持多服务调用、
    命令信息获取和连接状态管理。

    Attributes:
        ip: 设备IP地址
        port: 设备端口号
        services: 可用服务列表
        mix8_client: 底层MIX8客户端实例
        connected: 连接状态标志
        log_callback: 日志回调函数
    """

    def __init__(self, ip, port, log_callback=None):
        """初始化RPC客户端。

        Args:
            ip: MIX8设备IP地址
            port: MIX8设备端口号
            log_callback: 日志回调函数，用于接收日志消息，可选

        Example:
            >>> def my_logger(msg):
            ...     print(f"[LOG] {msg}")
            >>> client = RpcClient("192.168.1.100", 7801, log_callback=my_logger)
        """
        self.ip = ip
        self.port = port
        self.services = []
        self.mix8_client = None
        self.connected = False
        self.log_callback = log_callback
        self._log(f"初始化RPC客户端: {ip}:{port}")
    
    def _log(self, message):
        """记录日志消息。

        将日志消息打印到控制台，并通过回调函数传递给上层。

        Args:
            message: 日志消息字符串
        """
        print(message)
        if self.log_callback:
            self.log_callback(message)
    
    def connect(self):
        """连接到MIX8设备。

        初始化底层MIX8客户端并建立连接。

        Returns:
            bool: 连接是否成功，True表示成功，False表示失败
        """
        self._initialize_mix8_client()
        return self.connected
    
    def _initialize_mix8_client(self):
        """初始化MIX8客户端。

        动态导入mix8_rpc_client模块，创建底层客户端实例。
        支持开发环境和PyInstaller打包后的运行环境。
        自动检测mix目录并添加到Python路径。

        Returns:
            None: 无返回值，连接状态通过self.connected属性体现

        Warning:
            如果导入失败，会记录详细错误信息但不会抛出异常
        """
        try:
            mix_dir = os.path.join(PLUGIN_DIR, 'mix')
            print(f"[插件环境] mix目录路径: {mix_dir}")
            
            if mix_dir not in sys.path:
                sys.path.insert(0, mix_dir)
                print(f"已将mix目录添加到Python路径")
            
            from mix8_rpc_client import RpcClient as Mix8RpcClient
            
            self.mix8_client = Mix8RpcClient(self.ip, int(self.port))
            
            if hasattr(self.mix8_client, 'connected') and self.mix8_client.connected:
                self.connected = True
                self._log(f"成功连接到MIX8设备: {self.ip}:{self.port}")
            else:
                self.connected = False
                self._log(f"连接MIX8设备失败: 客户端初始化失败")
                
        except ImportError as e:
            self._log(f"导入MIX8客户端失败: {e}")
            self._log("请确保mix目录包含mix8_rpc_client.py文件")
            self.connected = False
        except Exception as e:
            self._log(f"初始化MIX8客户端失败: {e}")
            self.connected = False
    
    def list_remote_services(self):
        """获取所有可用的远程服务列表。

        Returns:
            list: 服务名称列表，连接失败时返回空列表

        Example:
            >>> client = RpcClient("192.168.1.100", 7801)
            >>> if client.connect():
            ...     services = client.list_remote_services()
            ...     print(f"可用服务: {services}")
        """
        if self.connected and self.mix8_client:
            try:
                return self.mix8_client._list_remote_services()
            except Exception as e:
                self._log(f"获取服务列表失败: {e}")
                return self.services
        return self.services
    
    def send_command(self, service_name, method_name, *args, rpc_timeout=None, **kwargs):
        """发送RPC命令到MIX8设备。

        向指定服务的指定方法发送调用请求，支持位置参数和关键字参数。

        Args:
            service_name: 服务名称字符串
            method_name: 方法名称字符串
            *args: 位置参数，可变长度
            rpc_timeout: 超时时间（秒），可选
            **kwargs: 关键字参数，字典形式

        Returns:
            str or Any: 命令执行结果，连接失败时返回错误信息字符串

        Example:
            >>> client = RpcClient("192.168.1.100", 7801)
            >>> if client.connect():
            ...     result = client.send_command("system", "version")
            ...     print(f"版本: {result}")
        """
        if not self.connected:
            self._log(f"RPC客户端未连接: {self.ip}:{self.port}")
            return f"错误: RPC客户端未连接"
        
        try:
            ret = self.mix8_client.stub(service_name, method_name, *args, rpc_timeout=rpc_timeout, **kwargs)
            return ret
        except Exception as e:
            self._log(f"发送指令失败: {e}")
            return f"错误: {str(e)}"
    
    def get_all_commands(self):
        """获取所有命令的详细信息。

        遍历所有服务及其方法，获取每个命令的说明和参数信息。
        用于构建命令自动补全和命令文档显示功能。

        Returns:
            dict: 命令信息字典，结构为 {service: {method: {'doc': str, 'params': list}}}
            连接失败时返回空字典

        Note:
            返回的params字段包含参数名称和默认值信息

        Example:
            >>> client = RpcClient("192.168.1.100", 7801)
            >>> if client.connect():
            ...     commands = client.get_all_commands()
            ...     for service, methods in commands.items():
            ...         print(f"服务: {service}")
            ...         for method, info in methods.items():
            ...             print(f"  - {method}: {info['doc']}")
        """
        if not self.connected:
            self._log(f"RPC客户端未连接: {self.ip}:{self.port}")
            return {}
        
        try:
            services = self.mix8_client._list_remote_services()
            commands_info = {}
            
            # 检查 services 是否为 None
            if services is None:
                self._log("服务列表为 None")
                return commands_info
            
            for service in services:
                # 检查服务名是否有效
                if not service:
                    continue
                if service =='power':
                    print("=================>power")
                try:
                    result = self.mix8_client.methods_info(service)
                    # 检查返回值是否为 None
                    if result is None:
                        self._log(f"服务 {service} 的 methods_info 返回 None")
                        continue
                    
                    # 尝试解包结果
                    if isinstance(result, tuple) and len(result) >= 2:
                        methods_obj, sub_methods = result[0], result[1]
                    else:
                        self._log(f"服务 {service} 的 methods_info 返回格式不正确")
                        continue
                    
                    # 检查 methods_obj 是否为 None
                    if methods_obj is None:
                        self._log(f"服务 {service} 的方法对象为 None")
                        continue
                    
                    # 检查 methods_obj 是否包含 'methods' 键
                    if 'methods' not in methods_obj:
                        self._log(f"服务 {service} 的方法对象不包含 methods 键")
                        continue
                    
                    # 检查 sub_methods 是否为 None
                    if sub_methods is None:
                        self._log(f"服务 {service} 的方法列表为 None")
                        continue
                    
                    commands_info[service] = {}
                    
                    for method in sub_methods:
                        if method in methods_obj['methods']:
                            method_info = methods_obj['methods'][method]
                            doc = method_info.get('__doc__', '') or ''
                            params = method_info.get('params', []) or []
                            commands_info[service][method] = {
                                'doc': doc,
                                'params': params
                            }
                except Exception as e:
                    self._log(f"获取服务 {service} 的方法信息失败: {e}")
            
            return commands_info
        except Exception as e:
            self._log(f"获取命令信息失败: {e}")
            return {}
    
    def close(self):
        """关闭RPC连接。

        断开与MIX8设备的连接，释放相关资源。
        调用后connection状态会被设置为False。

        Warning:
            关闭后如需再次使用，需要重新调用connect()方法建立连接
        """
        if self.mix8_client:
            try:
                self.mix8_client.close()
                self._log("RPC连接已关闭")
            except Exception as e:
                self._log(f"关闭连接失败: {e}")
        self.connected = False