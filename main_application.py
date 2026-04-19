#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
主应用程序
"""

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QApplication, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from ui.uart_plugin import UartPlugin
import sys

class MainApplication(QMainWindow):
    """
    主应用程序类
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自动化任务管理平台")
        self.setGeometry(100, 100, 780, 600)
        self.setMinimumSize(780, 600)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建标签页管理
        self.tab_widget = QTabWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(self.tab_widget)
        
        # 添加插件
        self.add_mix_plugin()
        self.add_uart_plugin()
        
    def add_mix_plugin(self):
        """
        添加MIX-debug插件
        """
        # 创建MainWindow实例
        mix_window = MainWindow()
        
        # 由于MainWindow继承自QMainWindow，有自己的centralWidget
        # 直接将其作为标签页添加，但隐藏其窗口标题
        mix_window.setWindowFlags(Qt.WindowType.Widget)
        
        # 添加到标签页
        self.tab_widget.addTab(mix_window, "MIX-debug")
    
    def add_uart_plugin(self):
        """
        添加串口调试插件
        """
        # 创建UartPlugin实例
        uart_plugin = UartPlugin()
        
        # 添加到标签页
        self.tab_widget.addTab(uart_plugin, "串口调试")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_app = MainApplication()
    main_app.show()
    sys.exit(app.exec())
