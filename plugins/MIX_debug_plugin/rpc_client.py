import sys
import os

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

class RpcClient:
    def __init__(self, ip, port, log_callback=None):
        self.ip = ip
        self.port = port
        self.services = []
        self.mix8_client = None
        self.connected = False
        self.log_callback = log_callback
        self._log(f"初始化RPC客户端: {ip}:{port}")
    
    def _log(self, message):
        """
        记录日志
        """
        print(message)
        if self.log_callback:
            self.log_callback(message)
    
    def connect(self):
        """
        连接到MIX8设备
        """
        self._initialize_mix8_client()
        return self.connected
    
    def _initialize_mix8_client(self):
        """
        初始化MIX8客户端（支持开发环境和打包后环境）
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
        """
        获取所有可调用服务
        """
        if self.connected and self.mix8_client:
            try:
                return self.mix8_client._list_remote_services()
            except Exception as e:
                self._log(f"获取服务列表失败: {e}")
                return self.services
        return self.services
    
    def send_command(self, service_name, method_name, *args, **kwargs):
        """
        发送指令
        """
        if not self.connected:
            self._log(f"RPC客户端未连接: {self.ip}:{self.port}")
            return f"错误: RPC客户端未连接"
        
        try:
            ret = self.mix8_client.stub(service_name, method_name, *args, **kwargs)
            return ret
        except Exception as e:
            self._log(f"发送指令失败: {e}")
            return f"错误: {str(e)}"
    
    def get_all_commands(self):
        """
        获取所有命令信息，包括服务列表和每个服务的方法及其文档
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
        """
        关闭连接
        """
        if self.mix8_client:
            try:
                self.mix8_client.close()
                self._log("RPC连接已关闭")
            except Exception as e:
                self._log(f"关闭连接失败: {e}")
        self.connected = False