import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from core.rpc_client import RpcClient
from utils.logger import logger
from utils.config import config_manager

class App:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.main_window = MainWindow()
        # 移除自动初始化RPC客户端，只在用户点击连接按钮时才创建
        # self.rpc_clients = {}
        # self.init_rpc_clients()
    
    # def init_rpc_clients(self):
    #     """
    #     初始化RPC客户端
    #     """
    #     channels = config_manager.get_channels()
    #     for i, channel in enumerate(channels):
    #         try:
    #             client = RpcClient(channel['ip'], channel['port'])
    #             self.rpc_clients[i] = client
    #             logger.info(f"通道 {channel['name']} RPC客户端初始化成功")
    #         except Exception as e:
    #             logger.error(f"通道 {channel['name']} RPC客户端初始化失败: {e}")
    #             self.rpc_clients[i] = None
    
    def run(self):
        """
        运行应用
        """
        self.main_window.show()
        sys.exit(self.app.exec())

if __name__ == '__main__':
    app = App()
    app.run()