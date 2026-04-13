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
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
import serial
import serial.tools.list_ports
import sys

class SerialReader(QThread):
    """
    串口数据读取线程
    """
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, ser):
        super().__init__()
        self.ser = ser
        self.running = True
    
    def run(self):
        try:
            while self.running and self.ser.is_open:
                data = self.ser.readline()
                if data:
                    try:
                        text = data.decode('utf-8', errors='replace').strip()
                        self.data_received.emit(text)
                    except Exception as e:
                        self.error_occurred.emit(f"解码错误: {str(e)}")
        except Exception as e:
            self.error_occurred.emit(f"读取错误: {str(e)}")
    
    def stop(self):
        self.running = False

class UartPlugin(QWidget):
    """
    串口调试插件
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ser = None
        self.reader_thread = None
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI
        """
        main_layout = QVBoxLayout(self)
        
        # 串口配置区域
        config_group = QGroupBox("串口配置")
        config_layout = QFormLayout()
        
        # 串口选择
        self.port_label = QLabel("串口:")
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        self.port_combo.addItem("手动输入串口地址", "")
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_ports)
        
        # 手动输入串口地址
        self.manual_port_input = QLineEdit()
        self.manual_port_input.setPlaceholderText("输入自定义串口地址")
        self.manual_port_input.setEnabled(False)
        
        # 监听串口选择变化
        self.port_combo.currentIndexChanged.connect(self.on_port_selection_changed)
        
        port_layout = QVBoxLayout()
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(self.port_combo)
        combo_layout.addWidget(self.refresh_button)
        port_layout.addLayout(combo_layout)
        port_layout.addWidget(self.manual_port_input)
        
        config_layout.addRow(self.port_label, port_layout)
        
        # 波特率
        self.baud_label = QLabel("波特率:")
        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1200, 115200)
        self.baud_spin.setValue(115200)
        config_layout.addRow(self.baud_label, self.baud_spin)
        
        # 连接按钮
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.toggle_connection)
        config_layout.addRow(self.connect_button)
        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
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
        
        try:
            ports = serial.tools.list_ports.comports()
            for port, desc, hwid in sorted(ports):
                self.port_combo.addItem(f"{port} - {desc}", port)
            
            if not ports:
                self.port_combo.addItem("无可用串口", "")
        except Exception as e:
            self.log_message(f"扫描串口失败: {str(e)}")
    
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
        if self.ser and self.ser.is_open:
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
        
        baudrate = self.baud_spin.value()
        
        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            
            if self.ser.is_open:
                self.log_message(f"✅ 串口连接成功: {port} @ {baudrate}")
                self.connect_button.setText("断开")
                
                # 启动读取线程
                self.reader_thread = SerialReader(self.ser)
                self.reader_thread.data_received.connect(self.log_message)
                self.reader_thread.error_occurred.connect(self.log_message)
                self.reader_thread.start()
        except Exception as e:
            self.log_message(f"❌ 连接失败: {str(e)}")
    
    def disconnect_serial(self):
        """
        断开串口连接
        """
        if self.reader_thread:
            self.reader_thread.stop()
            self.reader_thread.wait()
            self.reader_thread = None
        
        if self.ser and self.ser.is_open:
            self.ser.close()
        
        self.ser = None
        self.connect_button.setText("连接")
        self.log_message("✅ 串口已断开")
    
    def send_data(self):
        """
        发送数据
        """
        data = self.send_input.text()
        if not data:
            return
        
        if not self.ser or not self.ser.is_open:
            QMessageBox.warning(self, "警告", "请先连接串口")
            return
        
        try:
            self.ser.write((data + '\n').encode('utf-8'))
            self.log_message(f">> {data}")
            self.send_input.clear()
        except Exception as e:
            self.log_message(f"发送失败: {str(e)}")
    
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
