#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
串口调试插件
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QPushButton, QTextEdit, QLineEdit, QGroupBox, QFormLayout,
    QSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QObject, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.uic import loadUi
from core.uart_manager import UartManager
from utils.logger import init_logger
import sys
import os

def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径，支持打包后的应用
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的路径
        base_path = sys._MEIPASS
    else:
        # 开发环境路径
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

class UartPlugin(QWidget):
    """
    串口调试插件
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # 从ui文件加载UI
        ui_path = get_resource_path('ui/uart_plugin.ui')
        loadUi(ui_path, self)
        # 直接使用UartManager的默认日志配置
        # 它会自动使用utils.logger模块并创建uart.log文件
        # 使用线程安全的日志回调
        self.uart_manager = UartManager(callback=self.safe_log_message)
        self.init_signals()
        
    def init_signals(self):
        """
        初始化信号连接
        """
        # 刷新按钮
        self.refreshButton.clicked.connect(self.refresh_ports)
        
        # 连接按钮
        self.connectButton.clicked.connect(self.toggle_connection)
        
        # 发送按钮
        self.sendButton.clicked.connect(self.send_data)
        self.sendInput.returnPressed.connect(self.send_data)
        
        # 串口选择变化
        self.portCombo.currentIndexChanged.connect(self.on_port_selection_changed)
        
        # 设置默认值
        self.baudCombo.setCurrentText("115200")
        self.dataBitsCombo.setCurrentText("8")
        self.parityCombo.setCurrentText("无")
        self.stopBitsCombo.setCurrentText("1")
        
        # 刷新串口列表
        self.refresh_ports()
        
        # 设置字体
        self.dataDisplay.setFont(QFont("Courier New", 10))
    
    def refresh_ports(self):
        """
        刷新串口列表
        """
        # 保存当前选择
        current_text = self.portCombo.currentText()
        
        # 清空并添加手动输入选项
        self.portCombo.clear()
        self.portCombo.addItem("手动输入串口地址", "")
        
        # 使用UartManager扫描串口
        ports = self.uart_manager.scan_ports()
        if ports:
            for port, desc in ports:
                self.portCombo.addItem(f"{port} - {desc}", port)
        else:
            self.portCombo.addItem("无可用串口", "")
    
    def on_port_selection_changed(self, index):
        """
        处理串口选择变化
        """
        # 获取当前选择的数据
        port = self.portCombo.currentData()
        
        # 如果选择的是"手动输入串口地址"，启用手动输入框
        if port == "":
            self.manualPortInput.setEnabled(True)
        else:
            self.manualPortInput.setEnabled(False)
    
    def toggle_connection(self):
        """
        切换连接状态
        """
        if self.uart_manager.is_connected():
            self.disconnect_serial()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        """
        连接串口
        """
        # 获取串口地址
        port = self.portCombo.currentData()
        
        # 如果选择的是手动输入，使用手动输入的地址
        if port == "":
            port = self.manualPortInput.text().strip()
            if not port:
                QMessageBox.warning(self, "警告", "请输入有效的串口地址")
                return
        elif not port:
            QMessageBox.warning(self, "警告", "请选择一个有效的串口")
            return
        
        # 获取串口参数
        baudrate = int(self.baudCombo.currentText())
        data_bits = int(self.dataBitsCombo.currentText())
        
        # 映射校验位
        parity_map = {
            "无": 'N',
            "奇": 'O',
            "偶": 'E',
            "标记": 'M',
            "空格": 'S'
        }
        parity = parity_map[self.parityCombo.currentText()]
        
        # 映射停止位
        stop_bits_map = {
            "1": 1,
            "1.5": 1.5,
            "2": 2
        }
        stop_bits = stop_bits_map[self.stopBitsCombo.currentText()]
        
        # 使用UartManager连接串口
        if self.uart_manager.connect(port, baudrate, data_bits, parity, stop_bits, auto_reconnect=True):
            self.connectButton.setText("断开")
    
    def disconnect_serial(self):
        """
        断开串口连接
        """
        self.uart_manager.disconnect()
        self.connectButton.setText("连接")
    
    def send_data(self):
        """
        发送数据
        """
        data = self.sendInput.text()
        if not data:
            return
        
        if not self.uart_manager.is_connected():
            QMessageBox.warning(self, "警告", "请先连接串口")
            return
        
        if self.uart_manager.send(data):
            self.sendInput.clear()
    
    def safe_log_message(self, message):
        """
        线程安全的日志消息记录（用于从SerialReader线程调用）
        """
        # 使用QMetaObject.invokeMethod确保在主线程中执行
        from PyQt6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(self, "append_log", Qt.ConnectionType.QueuedConnection, Q_ARG(str, message))
    
    @pyqtSlot(str)
    def append_log(self, message):
        """
        在日志显示区域追加消息（仅在主线程中调用）
        """
        self.dataDisplay.append(message)
        # 自动滚动到底部
        cursor = self.dataDisplay.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.dataDisplay.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """
        关闭事件处理
        """
        self.disconnect_serial()
        event.accept()
