import sys
import os

# 模拟RPC客户端，用于测试UI功能
class RpcClient:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.services = ['relay', 'lucifer', 'eeprom', 'sib_board']
        print(f"初始化RPC客户端: {ip}:{port}")
    
    def list_remote_services(self):
        """
        获取所有可调用服务
        """
        return self.services
    
    def get_proxy(self, service_name):
        """
        获取服务代理
        """
        if service_name in self.services:
            return MockService(service_name)
        return None
    
    def send_command(self, service_name, method_name, *args, **kwargs):
        """
        发送指令
        """
        try:
            proxy = self.get_proxy(service_name)
            if proxy:
                method = getattr(proxy, method_name, None)
                if method:
                    return method(*args, **kwargs)
                else:
                    raise Exception(f"方法 {method_name} 不存在")
            else:
                raise Exception(f"服务 {service_name} 不存在")
        except Exception as e:
            print(f"发送指令失败: {e}")
            return None

class MockService:
    """
    模拟服务类，用于测试
    """
    def __init__(self, service_name):
        self.service_name = service_name
    
    def reset(self, *args, **kwargs):
        return f"[{self.service_name}] 执行reset操作成功"
    
    def led_control(self, *args, **kwargs):
        return f"[{self.service_name}] 执行led_control操作成功: {args}"
    
    def read_string_eeprom(self, *args, **kwargs):
        return f"[{self.service_name}] 读取EEPROM成功: {args}"
    
    def write_string_eeprom(self, *args, **kwargs):
        return f"[{self.service_name}] 写入EEPROM成功: {args}"
    
    def reset_gpio(self, *args, **kwargs):
        return f"[{self.service_name}] 重置GPIO成功"
    
    def get_gpio(self, *args, **kwargs):
        return f"[{self.service_name}] 获取GPIO值: {args}"