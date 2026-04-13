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

    def run(self):
        """
        运行应用
        """
        self.main_window.show()
        sys.exit(self.app.exec())

if __name__ == '__main__':
    app = App()
    app.run()