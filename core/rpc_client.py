import sys
import os
import importlib.util

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
        #debug
        # if self.log_callback:
        #     self.log_callback(message)
    
    def connect(self):
        """
        连接到MIX8设备
        """
        self._initialize_mix8_client()
        return self.connected
    
    def _initialize_mix8_client(self):
        """
        动态加载MIX8客户端
        """
        try:
            # 尝试动态加载MIX8模块
            # 尝试多个可能的路径
            possible_paths = []
            
            # 检查是否在PyInstaller打包环境中
            if hasattr(sys, '_MEIPASS'):
                # 在打包环境中，添加临时目录作为搜索路径
                meipass_path = os.path.join(sys._MEIPASS, 'mix', 'mix8_rpc_client.py')
                possible_paths.insert(0, meipass_path)

            
            #添加绝对路径
            absolute_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mix', 'mix8_rpc_client.py'))
            possible_paths.append(absolute_path)
            
            self._log(f"尝试加载MIX8模块，搜索路径:")
            for i, path in enumerate(possible_paths, 1):
                exists = "存在" if os.path.exists(path) else "不存在"
                self._log(f"  {i}. {path} [{exists}]")
            
            mix8_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    mix8_path = path
                    break
            
            if mix8_path:
                self._log(f"找到MIX8模块: {mix8_path}")
                # 动态添加mix8目录和mix子目录到Python路径
                mix8_dir = os.path.dirname(mix8_path)
                mix_dir = os.path.join(mix8_dir, 'mix')
                sys.path.append(mix8_dir)
                sys.path.append(mix_dir)
                
                try:
                    spec = importlib.util.spec_from_file_location("mix8_client", mix8_path)
                    mix8_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mix8_module)
                    
                    # 初始化MIX8客户端
                    try:
                        self.mix8_client = mix8_module.RpcClient(self.ip, int(self.port))
                        self.connected = True
                        self._log(f"成功连接到MIX8设备: {self.ip}:{self.port}")
                    except Exception as e:
                        self._log(f"连接MIX8设备失败: {e}")
                        self.connected = False
                except Exception as e:
                    self._log(f"加载MIX8模块失败: {e}")
                    self._log("请确保mix8目录包含所有必要的依赖文件")
                    self.connected = False
            else:
                self._log(f"MIX8客户端文件不存在")
                self._log("请将mix8目录放在应用程序旁边")
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
                # 调用MIX8客户端的方法获取服务列表
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
            ret = self.mix8_client.client.stub(service_name, method_name, *args, **kwargs)
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
            # 获取所有服务列表
            services = self.mix8_client._list_remote_services()
            commands_info = {}
            
            # 为每个服务获取方法信息
            for service in services:
                try:
                    # 调用methods_info获取服务的方法信息
                    methods_obj, sub_methods = self.mix8_client.methods_info(service)
                    commands_info[service] = {}
                    
                    # 提取每个方法的文档
                    for method in sub_methods:
                        if method in methods_obj['methods'] and methods_obj['methods'][method].get('__doc__'):
                            doc = methods_obj['methods'][method]['__doc__']
                            params = methods_obj['methods'][method].get('params', [])
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