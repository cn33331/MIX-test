import json
import os

class ConfigManager:
    def __init__(self):
        # 配置文件路径（使用用户应用数据目录）
        self.config_dir = self._get_config_dir()
        self.config_file = os.path.join(self.config_dir, 'config.json')
        # 打印路径用于验证
        # print(f"配置目录: {self.config_dir}")
        print(f"配置文件: {self.config_file}")
        # 确保目录存在
        self._ensure_dir_exists()
        self.config = self.load_config()
    
    def get_config_dir(self):
        """
        获取配置目录
        """
        return self.config_dir
    
    def _get_config_dir(self):
        """
        获取配置目录路径
        """
        # 尝试使用用户应用数据目录
        if os.name == 'posix':  # macOS or Linux
            # 使用用户主目录下的配置目录
            home_dir = os.path.expanduser('~')
            config_dir = os.path.join(home_dir, '.MIX-Tool')
        elif os.name == 'nt':  # Windows
            # 使用AppData目录
            config_dir = os.path.join(os.environ.get('APPDATA', ''), 'MIX-Tool')
        else:
            # 其他系统使用当前目录
            config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
        return config_dir
    
    def _ensure_dir_exists(self):
        """
        确保配置目录存在
        """
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir)
                print(f"创建配置目录: {self.config_dir}")
            except Exception as e:
                print(f"创建配置目录失败: {e}")
                # 如果创建失败，使用应用当前目录作为备选
                self.config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
                self.config_file = os.path.join(self.config_dir, 'config.json')
                try:
                    os.makedirs(self.config_dir)
                    print(f"使用备选配置目录: {self.config_dir}")
                except Exception as e:
                    print(f"创建备选配置目录失败: {e}")
    
    def load_config(self):
        """
        加载配置文件
        """
        default_config = {
            'channels': [
                {'name': 'Slot1', 'ip': '192.168.99.36', 'port': '7801'}
            ],
            'default_service': 'relay',
            'default_method': 'reset',
            'history': []
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载配置文件失败: {e}")
                return default_config
        else:
            # 保存默认配置
            self.save_config(default_config)
            return default_config
    
    def save_config(self, config):
        """
        保存配置文件
        """
        try:
            # 确保目录存在
            self._ensure_dir_exists()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False
    
    def get_channels(self):
        """
        获取通道配置
        """
        return self.config.get('channels', [])
    
    def get_channel(self, index):
        """
        获取指定通道配置
        """
        channels = self.get_channels()
        if 0 <= index < len(channels):
            return channels[index]
        return None
    
    def update_channel(self, index, channel_data):
        """
        更新通道配置
        """
        channels = self.get_channels()
        if 0 <= index < len(channels):
            channels[index].update(channel_data)
            self.config['channels'] = channels
            return self.save_config(self.config)
        return False
    
    def get_history(self):
        """
        获取历史指令
        """
        return self.config.get('history', [])
    
    def save_history(self, history):
        """
        保存历史指令
        """
        self.config['history'] = history
        return self.save_config(self.config)

# 创建全局配置实例
config_manager = ConfigManager()