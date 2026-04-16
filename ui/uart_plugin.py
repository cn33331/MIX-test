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
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor
from core.uart_manager import UartManager
import sys
import os

class UartPlugin(QWidget):
    """
    串口调试插件
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # 生成日志文件路径
        if os.name == 'posix':  # macOS or Linux
            # 使用用户主目录下的日志目录
            home_dir = os.path.expanduser('~')
            log_dir = os.path.join(home_dir, '.MIX-Tool', 'logs')
        elif os.name == 'nt':  # Windows
            # 使用AppData目录
            log_dir = os.path.join(os.environ.get('APPDATA', ''), 'MIX-Tool', 'logs')
        else:
            # 其他系统使用当前目录
            log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
        
        # 确保日志目录存在
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except Exception:
                pass
        
        log_file = os.path.join(log_dir, 'uart.log')
        self.uart_manager = UartManager(callback=self.log_message, log_file=log_file)
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI
        """
        main_layout = QVBoxLayout(self)
        
        # 配置区域 - 左右布局
        config_container = QWidget()
        config_layout = QHBoxLayout(config_container)
        
        # 左侧：串口配置
        left_config_group = QGroupBox("串口配置")
        left_layout = QVBoxLayout()
        
        # 串口选择
        port_layout = QVBoxLayout()
        port_label = QLabel("串口:")
        port_layout.addWidget(port_label)
        
        combo_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        self.port_combo.addItem("手动输入串口地址", "")
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_ports)
        combo_layout.addWidget(self.port_combo)
        combo_layout.addWidget(self.refresh_button)
        port_layout.addLayout(combo_layout)
        
        # 手动输入串口地址
        self.manual_port_input = QLineEdit()
        self.manual_port_input.setPlaceholderText("输入自定义串口地址")
        self.manual_port_input.setEnabled(False)
        port_layout.addWidget(self.manual_port_input)
        
        # 波特率
        baud_layout = QVBoxLayout()
        baud_label = QLabel("波特率:")
        baud_layout.addWidget(baud_label)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200", "57600", "38400", "19200"])
        self.baud_combo.setCurrentText("115200")
        baud_layout.addWidget(self.baud_combo)
        
        # 连接按钮
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.toggle_connection)
        
        left_layout.addLayout(port_layout)
        left_layout.addLayout(baud_layout)
        left_layout.addWidget(self.connect_button)
        left_config_group.setLayout(left_layout)
        
        # 右侧：串口参数（上下结构）
        right_params_group = QGroupBox("串口参数")
        right_layout = QVBoxLayout()
        
        # 数据位
        data_bits_layout = QVBoxLayout()
        self.data_bits_label = QLabel("数据位:")
        data_bits_layout.addWidget(self.data_bits_label)
        self.data_bits_combo = QComboBox()
        self.data_bits_combo.addItems(["5", "6", "7", "8"])
        self.data_bits_combo.setCurrentText("8")
        data_bits_layout.addWidget(self.data_bits_combo)
        
        # 校验位
        parity_layout = QVBoxLayout()
        self.parity_label = QLabel("校验位:")
        parity_layout.addWidget(self.parity_label)
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["无", "奇", "偶", "标记", "空格"])
        self.parity_combo.setCurrentText("无")
        parity_layout.addWidget(self.parity_combo)
        
        # 停止位
        stop_bits_layout = QVBoxLayout()
        self.stop_bits_label = QLabel("停止位:")
        stop_bits_layout.addWidget(self.stop_bits_label)
        self.stop_bits_combo = QComboBox()
        self.stop_bits_combo.addItems(["1", "1.5", "2"])
        self.stop_bits_combo.setCurrentText("1")
        stop_bits_layout.addWidget(self.stop_bits_combo)
        
        right_layout.addLayout(data_bits_layout)
        right_layout.addLayout(parity_layout)
        right_layout.addLayout(stop_bits_layout)
        right_params_group.setLayout(right_layout)
        
        # 监听串口选择变化
        self.port_combo.currentIndexChanged.connect(self.on_port_selection_changed)
        
        config_layout.addWidget(left_config_group)
        config_layout.addWidget(right_params_group)
        main_layout.addWidget(config_container)
        
        # 数据显示区域
        self.data_display = QTextEdit()
        self.data_display.setReadOnly(True)
        self.data_display.setFont(QFont("Courier New", 10))
        main_layout.addWidget(self.data_display)
        
        # 发送区域
        send_group = QGroupBox("发送数据")
        send_layout = QHBoxLayout()
        
        self.send_input = QLineEdit()
        self.send_input.setPlaceholderText("输入要发送的数据")
        self.send_input.returnPressed.connect(self.send_data)
        
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_data)
        
        send_layout.addWidget(self.send_input)
        send_layout.addWidget(self.send_button)
        send_group.setLayout(send_layout)
        main_layout.addWidget(send_group)
        
        # 刷新串口列表
        self.refresh_ports()
    
    def refresh_ports(self):
        """
        刷新串口列表
        """
        # 保存当前选择
        current_text = self.port_combo.currentText()
        
        # 清空并添加手动输入选项
        self.port_combo.clear()
        self.port_combo.addItem("手动输入串口地址", "")
        
        # 使用UartManager扫描串口
        ports = self.uart_manager.scan_ports()
        if ports:
            for port, desc in ports:
                self.port_combo.addItem(f"{port} - {desc}", port)
        else:
            self.port_combo.addItem("无可用串口", "")
    
    def on_port_selection_changed(self, index):
        """
        处理串口选择变化
        """
        # 获取当前选择的数据
        port = self.port_combo.currentData()
        
        # 如果选择的是"手动输入串口地址"，启用手动输入框
        if port == "":
            self.manual_port_input.setEnabled(True)
        else:
            self.manual_port_input.setEnabled(False)
    
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
        port = self.port_combo.currentData()
        
        # 如果选择的是手动输入，使用手动输入的地址
        if port == "":
            port = self.manual_port_input.text().strip()
            if not port:
                QMessageBox.warning(self, "警告", "请输入有效的串口地址")
                return
        elif not port:
            QMessageBox.warning(self, "警告", "请选择一个有效的串口")
            return
        
        # 获取串口参数
        baudrate = int(self.baud_combo.currentText())
        data_bits = int(self.data_bits_combo.currentText())
        
        # 映射校验位
        parity_map = {
            "无": 'N',
            "奇": 'O',
            "偶": 'E',
            "标记": 'M',
            "空格": 'S'
        }
        parity = parity_map[self.parity_combo.currentText()]
        
        # 映射停止位
        stop_bits_map = {
            "1": 1,
            "1.5": 1.5,
            "2": 2
        }
        stop_bits = stop_bits_map[self.stop_bits_combo.currentText()]
        
        # 使用UartManager连接串口
        if self.uart_manager.connect(port, baudrate, data_bits, parity, stop_bits):
            self.connect_button.setText("断开")
    
    def disconnect_serial(self):
        """
        断开串口连接
        """
        self.uart_manager.disconnect()
        self.connect_button.setText("连接")
    
    def send_data(self):
        """
        发送数据
        """
        data = self.send_input.text()
        if not data:
            return
        
        if not self.uart_manager.is_connected():
            QMessageBox.warning(self, "警告", "请先连接串口")
            return
        
        if self.uart_manager.send(data):
            self.send_input.clear()
    
    def log_message(self, message):
        """
        记录消息到显示区域
        """
        self.data_display.append(message)
        # 自动滚动到底部
        cursor = self.data_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.data_display.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """
        关闭事件处理
        """
        self.disconnect_serial()
        event.accept()
