#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TCP调试插件 - 支持服务器和客户端同时运行
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTextEdit, QGroupBox, QComboBox, QMessageBox, 
    QPlainTextEdit, QFormLayout, QSplitter
)
from PyQt6.QtCore import Qt, QObject, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
import sys
import os
import socket
import threading

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径（插件目录在外部，不从MEIPASS加载）
    """
    return os.path.join(PLUGIN_DIR, relative_path)

class TCPServerWorker(QObject):
    """
    TCP服务器工作线程
    """
    message_received = pyqtSignal(str)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(bool)
    
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        self.connected_clients = []
    
    def start(self):
        """
        启动服务器
        """
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            self.running = True
            
            self.message_received.emit(f"服务器已启动，监听 {self.host}:{self.port}")
            self.status_changed.emit(True)
            
            # 启动监听线程
            self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
            self.accept_thread.start()
        except Exception as e:
            self.error_occurred.emit(f"启动服务器失败: {str(e)}")
            self.status_changed.emit(False)
    
    def _accept_clients(self):
        """
        接受客户端连接
        """
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                self.connected_clients.append((client_socket, addr))
                self.client_connected.emit(f"客户端已连接: {addr[0]}:{addr[1]}")
                
                # 为每个客户端启动一个处理线程
                client_thread = threading.Thread(
                    target=self._handle_client, 
                    args=(client_socket, addr), 
                    daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.error_occurred.emit(f"接受客户端连接失败: {str(e)}")
    
    def _handle_client(self, client_socket, addr):
        """
        处理客户端通信
        """
        client_socket.settimeout(1.0)
        while self.running:
            try:
                data = client_socket.recv(1024)
                if not data:
                    break
                message = data.decode('utf-8', errors='replace').strip()
                self.message_received.emit(f"<< {addr[0]}: {message}")
            except socket.timeout:
                continue
            except Exception as e:
                self.error_occurred.emit(f"接收数据失败 ({addr[0]}): {str(e)}")
                break
        
        # 客户端断开连接
        client_socket.close()
        self.connected_clients = [(s, a) for s, a in self.connected_clients if a != addr]
        self.client_disconnected.emit(f"客户端已断开: {addr[0]}:{addr[1]}")
    
    def send_to_all(self, message):
        """
        向所有连接的客户端发送消息
        """
        if not self.connected_clients:
            self.error_occurred.emit("没有连接的客户端")
            return False
        
        success_count = 0
        for client_socket, addr in self.connected_clients[:]:
            try:
                client_socket.sendall((message + '\n').encode('utf-8'))
                success_count += 1
            except Exception as e:
                self.error_occurred.emit(f"发送失败 ({addr[0]}): {str(e)}")
        
        if success_count > 0:
            self.message_received.emit(f">> 已发送到 {success_count} 个客户端: {message}")
            return True
        return False
    
    def stop(self):
        """
        停止服务器
        """
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        self.message_received.emit("服务器已停止")
        self.status_changed.emit(False)

class TCPClientWorker(QObject):
    """
    TCP客户端工作线程
    """
    message_received = pyqtSignal(str)
    connected = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.client_socket = None
        self.running = False
    
    def connect_to_server(self):
        """
        连接到服务器
        """
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(5.0)
            self.client_socket.connect((self.host, self.port))
            self.client_socket.settimeout(1.0)
            self.running = True
            
            self.message_received.emit(f"已连接到服务器 {self.host}:{self.port}")
            self.connected.emit(True)
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self._receive_messages, daemon=True)
            self.receive_thread.start()
        except Exception as e:
            self.error_occurred.emit(f"连接失败: {str(e)}")
            self.connected.emit(False)
    
    def _receive_messages(self):
        """
        接收服务器消息
        """
        while self.running:
            try:
                data = self.client_socket.recv(1024)
                if not data:
                    self.message_received.emit("服务器已断开连接")
                    self.connected.emit(False)
                    break
                message = data.decode('utf-8', errors='replace').strip()
                self.message_received.emit(f"<< {message}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.error_occurred.emit(f"接收数据失败: {str(e)}")
                    self.connected.emit(False)
                break
    
    def send_message(self, message):
        """
        发送消息到服务器
        """
        if not self.client_socket or not self.running:
            self.error_occurred.emit("未连接到服务器")
            return False
        
        try:
            self.client_socket.sendall((message + '\n').encode('utf-8'))
            self.message_received.emit(f">> {message}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"发送失败: {str(e)}")
            return False
    
    def disconnect(self):
        """
        断开连接
        """
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
        self.message_received.emit("已断开连接")
        self.connected.emit(False)

class TCPDebugPlugin(QWidget):
    """
    TCP调试插件主窗口 - 支持服务器和客户端同时运行
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.version = 'v1.1'
        self.setWindowTitle(f'TCP-debug {self.version} by:zjx')
        
        self.server_worker = None
        self.client_worker = None
        
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI - 左右布局，左边服务器，右边客户端
        """
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：服务器区域
        server_group = QGroupBox("TCP 服务器")
        server_layout = QVBoxLayout(server_group)
        
        # 服务器配置
        server_config = QFormLayout()
        self.server_host_edit = QLineEdit("127.0.0.1")
        self.server_port_edit = QLineEdit("8888")
        self.server_status_label = QLabel("状态: 未运行")
        self.server_status_label.setStyleSheet("color: red")
        server_config.addRow("主机:", self.server_host_edit)
        server_config.addRow("端口:", self.server_port_edit)
        server_config.addRow(self.server_status_label)
        
        server_layout.addLayout(server_config)
        
        # 服务器按钮
        server_button_layout = QHBoxLayout()
        self.server_start_button = QPushButton("启动")
        self.server_stop_button = QPushButton("停止")
        self.server_clear_button = QPushButton("清空")
        self.server_start_button.clicked.connect(self.on_server_start)
        self.server_stop_button.clicked.connect(self.on_server_stop)
        self.server_clear_button.clicked.connect(self.clear_server_log)
        server_button_layout.addWidget(self.server_start_button)
        server_button_layout.addWidget(self.server_stop_button)
        server_button_layout.addWidget(self.server_clear_button)
        
        server_layout.addLayout(server_button_layout)
        
        # 服务器发送
        server_send_layout = QHBoxLayout()
        self.server_send_edit = QLineEdit()
        self.server_send_button = QPushButton("发送")
        self.server_send_edit.returnPressed.connect(self.on_server_send)
        self.server_send_button.clicked.connect(self.on_server_send)
        server_send_layout.addWidget(self.server_send_edit)
        server_send_layout.addWidget(self.server_send_button)
        
        server_layout.addLayout(server_send_layout)
        
        # 服务器日志
        self.server_log_text = QPlainTextEdit()
        self.server_log_text.setReadOnly(True)
        self.server_log_text.setFont(QFont("Courier New", 10))
        server_layout.addWidget(self.server_log_text)
        
        main_splitter.addWidget(server_group)
        
        # 右侧：客户端区域
        client_group = QGroupBox("TCP 客户端")
        client_layout = QVBoxLayout(client_group)
        
        # 客户端配置
        client_config = QFormLayout()
        self.client_host_edit = QLineEdit("127.0.0.1")
        self.client_port_edit = QLineEdit("8888")
        self.client_status_label = QLabel("状态: 未连接")
        self.client_status_label.setStyleSheet("color: red")
        client_config.addRow("主机:", self.client_host_edit)
        client_config.addRow("端口:", self.client_port_edit)
        client_config.addRow(self.client_status_label)
        
        client_layout.addLayout(client_config)
        
        # 客户端按钮
        client_button_layout = QHBoxLayout()
        self.client_connect_button = QPushButton("连接")
        self.client_disconnect_button = QPushButton("断开")
        self.client_clear_button = QPushButton("清空")
        self.client_connect_button.clicked.connect(self.on_client_connect)
        self.client_disconnect_button.clicked.connect(self.on_client_disconnect)
        self.client_clear_button.clicked.connect(self.clear_client_log)
        client_button_layout.addWidget(self.client_connect_button)
        client_button_layout.addWidget(self.client_disconnect_button)
        client_button_layout.addWidget(self.client_clear_button)
        
        client_layout.addLayout(client_button_layout)
        
        # 客户端发送
        client_send_layout = QHBoxLayout()
        self.client_send_edit = QLineEdit()
        self.client_send_button = QPushButton("发送")
        self.client_send_edit.returnPressed.connect(self.on_client_send)
        self.client_send_button.clicked.connect(self.on_client_send)
        client_send_layout.addWidget(self.client_send_edit)
        client_send_layout.addWidget(self.client_send_button)
        
        client_layout.addLayout(client_send_layout)
        
        # 客户端日志
        self.client_log_text = QPlainTextEdit()
        self.client_log_text.setReadOnly(True)
        self.client_log_text.setFont(QFont("Courier New", 10))
        client_layout.addWidget(self.client_log_text)
        
        main_splitter.addWidget(client_group)
        
        # 设置splitter比例
        main_splitter.setSizes([500, 500])
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(main_splitter)
    
    def log_server_message(self, message):
        """
        添加服务器日志消息
        """
        self.server_log_text.appendPlainText(message)
        cursor = self.server_log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.server_log_text.setTextCursor(cursor)
    
    def log_client_message(self, message):
        """
        添加客户端日志消息
        """
        self.client_log_text.appendPlainText(message)
        cursor = self.client_log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.client_log_text.setTextCursor(cursor)
    
    def clear_server_log(self):
        """
        清空服务器日志
        """
        self.server_log_text.clear()
    
    def clear_client_log(self):
        """
        清空客户端日志
        """
        self.client_log_text.clear()
    
    def on_server_start(self):
        """
        启动服务器
        """
        host = self.server_host_edit.text().strip()
        try:
            port = int(self.server_port_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "警告", "端口必须是数字")
            return
        
        self.server_worker = TCPServerWorker(host, port)
        self.server_worker.message_received.connect(self.log_server_message)
        self.server_worker.client_connected.connect(self.log_server_message)
        self.server_worker.client_disconnected.connect(self.log_server_message)
        self.server_worker.error_occurred.connect(self.log_server_message)
        self.server_worker.status_changed.connect(self.on_server_status_changed)
        self.server_worker.start()
    
    def on_server_status_changed(self, running):
        """
        服务器状态变化处理
        """
        if running:
            self.server_status_label.setText("状态: 运行中")
            self.server_status_label.setStyleSheet("color: green")
        else:
            self.server_status_label.setText("状态: 未运行")
            self.server_status_label.setStyleSheet("color: red")
    
    def on_server_stop(self):
        """
        停止服务器
        """
        if self.server_worker:
            self.server_worker.stop()
            self.server_worker = None
    
    def on_server_send(self):
        """
        服务器发送消息
        """
        message = self.server_send_edit.text().strip()
        if not message:
            return
        
        if self.server_worker:
            self.server_worker.send_to_all(message)
        else:
            self.log_server_message("错误: 服务器未启动")
        
        self.server_send_edit.clear()
    
    def on_client_connect(self):
        """
        客户端连接
        """
        host = self.client_host_edit.text().strip()
        try:
            port = int(self.client_port_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "警告", "端口必须是数字")
            return
        
        self.client_worker = TCPClientWorker(host, port)
        self.client_worker.message_received.connect(self.log_client_message)
        self.client_worker.connected.connect(self.on_client_status_changed)
        self.client_worker.error_occurred.connect(self.log_client_message)
        self.client_worker.connect_to_server()
    
    def on_client_status_changed(self, connected):
        """
        客户端连接状态处理
        """
        if connected:
            self.client_status_label.setText("状态: 已连接")
            self.client_status_label.setStyleSheet("color: green")
        else:
            self.client_status_label.setText("状态: 未连接")
            self.client_status_label.setStyleSheet("color: red")
    
    def on_client_disconnect(self):
        """
        客户端断开连接
        """
        if self.client_worker:
            self.client_worker.disconnect()
            self.client_worker = None
    
    def on_client_send(self):
        """
        客户端发送消息
        """
        message = self.client_send_edit.text().strip()
        if not message:
            return
        
        if self.client_worker:
            self.client_worker.send_message(message)
        else:
            self.log_client_message("错误: 未连接到服务器")
        
        self.client_send_edit.clear()
    
    def get_widget(self):
        """
        返回插件的主窗口部件
        """
        return self
    
    def get_name(self):
        """
        返回插件名称
        """
        return f'TCP-debug {self.version}'
    
    def closeEvent(self, event):
        """
        关闭事件处理
        """
        self.on_server_stop()
        self.on_client_disconnect()
        event.accept()