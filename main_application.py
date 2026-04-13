#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
主应用程序
"""

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QApplication, QVBoxLayout, QWidget
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
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1000, 600)
        
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
        # 创建MIX-debug插件容器
        mix_plugin_widget = QWidget()
        mix_layout = QVBoxLayout(mix_plugin_widget)
        
        # 创建MainWindow实例
        mix_window = MainWindow()
        
        # 将MainWindow的中央部件添加到插件中
        if mix_window.centralWidget():
            mix_layout.addWidget(mix_window.centralWidget())
        
        # 添加到标签页
        self.tab_widget.addTab(mix_plugin_widget, "MIX-debug")
    
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
