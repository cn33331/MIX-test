import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                            QLabel, QLineEdit, QPushButton, QTextEdit, 
                            QTableWidget, QTableWidgetItem, QGroupBox, 
                            QDialog, QSpinBox, QGridLayout, QScrollArea, QComboBox,
                            QCompleter, QListWidget, QListWidgetItem, QMenu, QSplitter, QHeaderView, QSizePolicy)
from PyQt6.QtCore import Qt, QStringListModel
from utils.config import config_manager
import json
import os
import csv
import glob

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.version = 'v1.5'
        self.setWindowTitle(f'MIX Test Control {self.version}')
        # 设置最小窗口大小，适应低分辨率设备
        self.setMinimumSize(800, 600)
        # 初始窗口大小，适应高分辨率设备
        self.setGeometry(100, 100, 1024, 768)
        self.rpc_clients = {}  # 保存已连接的RPC客户端
        self.init_ui()
        self.load_channels_from_config()
        self.load_history_from_config()
        # 连接窗口大小变化信号
        self.resizeEvent = self.on_resize
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 使用QSplitter创建可调整大小的布局
        main_splitter = QSplitter(Qt.Orientation.Horizontal, central_widget)
        main_splitter.setContentsMargins(10, 10, 10, 10)
        
        # 左侧区域
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)
        
        # 日志显示区域（左侧上方）
        log_group = QGroupBox('日志显示')
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(10, 10, 10, 10)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)  # 减少最小高度，适应低分辨率
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        left_layout.addWidget(log_group)
        
        # 命令选择区域（左侧下方）
        cmd_select_group = QGroupBox('命令选择')
        cmd_select_layout = QVBoxLayout()
        cmd_select_layout.setContentsMargins(10, 10, 10, 10)
        cmd_select_layout.setSpacing(10)
        
        # 指令输入
        input_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText('输入命令或从下方选择')
        self.cmd_input.setMinimumHeight(30)
        self.cmd_input.textChanged.connect(self.show_command_hints)
        self.cmd_input.returnPressed.connect(self.copy_command_to_param)
        input_layout.addWidget(QLabel('命令:'))
        input_layout.addWidget(self.cmd_input, 1)
        
        # 命令提示列表
        self.command_hint_list = QListWidget()
        self.command_hint_list.setMinimumHeight(80)  # 减少最小高度
        self.command_hint_list.itemClicked.connect(self.select_command)
        self.command_hint_list.hide()
        
        cmd_select_layout.addLayout(input_layout)
        cmd_select_layout.addWidget(self.command_hint_list)
        
        cmd_select_group.setLayout(cmd_select_layout)
        left_layout.addWidget(cmd_select_group)
        
        # 命令信息显示区域
        cmd_info_group = QGroupBox('命令信息')
        cmd_info_layout = QVBoxLayout()
        cmd_info_layout.setContentsMargins(10, 10, 10, 10)
        
        self.cmd_info_text = QTextEdit()
        self.cmd_info_text.setReadOnly(True)
        self.cmd_info_text.setMinimumHeight(80)  # 减少最小高度
        self.cmd_info_text.setPlainText('请选择一个命令以查看详细信息')
        
        cmd_info_layout.addWidget(self.cmd_info_text)
        cmd_info_group.setLayout(cmd_info_layout)
        left_layout.addWidget(cmd_info_group)
        
        # 参数输入区域
        param_group = QGroupBox('参数输入')
        param_layout = QHBoxLayout()
        param_layout.setContentsMargins(10, 10, 10, 10)
        param_layout.setSpacing(10)
        
        self.param_input = QLineEdit()
        self.param_input.setPlaceholderText('输入指令参数')
        self.param_input.setMinimumHeight(30)
        param_layout.addWidget(QLabel('参数:'))
        param_layout.addWidget(self.param_input, 1)
        
        param_group.setLayout(param_layout)
        left_layout.addWidget(param_group)
        
        # 指令发送区域
        cmd_group = QGroupBox('指令发送')
        cmd_layout = QHBoxLayout()
        cmd_layout.setContentsMargins(10, 10, 10, 10)
        
        self.send_cmd_button = QPushButton('发送指令')
        self.send_cmd_button.setMinimumHeight(30)
        self.send_cmd_button.clicked.connect(self.send_command)
        cmd_layout.addWidget(self.send_cmd_button)
        
        cmd_group.setLayout(cmd_layout)
        left_layout.addWidget(cmd_group)
        
        main_splitter.addWidget(left_widget)
        
        # 右侧区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(10)
        
        # 历史指令区域（右侧上方）
        history_group = QGroupBox('历史指令')
        history_layout = QVBoxLayout()
        history_layout.setContentsMargins(10, 10, 10, 10)
        
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(100)  # 减少最小高度
        self.history_list.itemDoubleClicked.connect(self.select_history_command)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        history_layout.addWidget(self.history_list)
        
        history_group.setLayout(history_layout)
        right_layout.addWidget(history_group)
        
        # 指令序列区域（右侧下方）
        self.sequence_group = QGroupBox('指令序列')
        sequence_layout = QVBoxLayout()
        sequence_layout.setContentsMargins(10, 10, 10, 10)
        sequence_layout.setSpacing(10)
        
        # 序列列表
        self.sequence_list = QListWidget()
        self.sequence_list.setMinimumHeight(100)  # 减少最小高度
        self.sequence_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sequence_list.customContextMenuRequested.connect(self.show_sequence_context_menu)
        sequence_layout.addWidget(self.sequence_list)
        
        # 序列操作按钮 - 使用网格布局，适应不同宽度
        sequence_buttons_widget = QWidget()
        sequence_buttons_layout = QGridLayout(sequence_buttons_widget)
        sequence_buttons_layout.setSpacing(5)
        
        add_cmd_btn = QPushButton('添加指令')
        add_cmd_btn.setMinimumHeight(30)
        add_cmd_btn.clicked.connect(self.add_command_to_sequence)
        sequence_buttons_layout.addWidget(add_cmd_btn, 0, 0)
        
        add_delay_btn = QPushButton('添加延迟')
        add_delay_btn.setMinimumHeight(30)
        add_delay_btn.clicked.connect(self.add_delay_to_sequence)
        sequence_buttons_layout.addWidget(add_delay_btn, 0, 1)
        
        add_pause_btn = QPushButton('添加暂停')
        add_pause_btn.setMinimumHeight(30)
        add_pause_btn.clicked.connect(self.add_pause_to_sequence)
        sequence_buttons_layout.addWidget(add_pause_btn, 1, 0)
        
        execute_sequence_btn = QPushButton('执行序列')
        execute_sequence_btn.setMinimumHeight(30)
        execute_sequence_btn.clicked.connect(self.execute_sequence)
        sequence_buttons_layout.addWidget(execute_sequence_btn, 1, 1)
        
        clear_sequence_btn = QPushButton('清空序列')
        clear_sequence_btn.setMinimumHeight(30)
        clear_sequence_btn.clicked.connect(self.clear_sequence)
        sequence_buttons_layout.addWidget(clear_sequence_btn, 2, 0, 1, 2)  # 跨两列
        
        sequence_layout.addWidget(sequence_buttons_widget)
        
        # 保存和加载按钮
        save_load_layout = QHBoxLayout()
        save_load_layout.setSpacing(10)
        
        save_sequence_btn = QPushButton('保存序列组')
        save_sequence_btn.setMinimumHeight(30)
        save_sequence_btn.clicked.connect(self.save_sequence_group)
        save_load_layout.addWidget(save_sequence_btn)
        
        load_sequence_btn = QPushButton('加载序列组')
        load_sequence_btn.setMinimumHeight(30)
        load_sequence_btn.clicked.connect(self.load_sequence_group)
        save_load_layout.addWidget(load_sequence_btn)
        
        sequence_layout.addLayout(save_load_layout)
        self.sequence_group.setLayout(sequence_layout)
        right_layout.addWidget(self.sequence_group)
        
        # 通道IP显示区域（右侧下方）
        ip_group = QGroupBox('通道IP配置')
        ip_layout = QVBoxLayout()
        ip_layout.setContentsMargins(10, 10, 10, 10)
        ip_layout.setSpacing(10)
        
        # 按钮布局 - 使用网格布局，适应不同宽度
        button_widget = QWidget()
        button_layout = QGridLayout(button_widget)
        button_layout.setSpacing(5)
        
        # 配置通道按钮
        config_channel_btn = QPushButton('配置通道')
        config_channel_btn.setMinimumHeight(30)
        button_layout.addWidget(config_channel_btn, 0, 0)
        config_channel_btn.clicked.connect(self.show_config_channel_dialog)
        
        # 批量连接按钮
        batch_connect_btn = QPushButton('批量连接')
        batch_connect_btn.setMinimumHeight(30)
        button_layout.addWidget(batch_connect_btn, 0, 1)
        batch_connect_btn.clicked.connect(self.batch_connect)
        
        # 批量断开按钮
        batch_disconnect_btn = QPushButton('批量断开')
        batch_disconnect_btn.setMinimumHeight(30)
        button_layout.addWidget(batch_disconnect_btn, 1, 0, 1, 2)  # 跨两列
        batch_disconnect_btn.clicked.connect(self.batch_disconnect)
        
        ip_layout.addWidget(button_widget)
        
        # 通道列表滚动区域
        scroll_area = QScrollArea()
        scroll_area.setMinimumHeight(200)  # 减少最小高度
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # 通道列表
        self.ip_table = QTableWidget(1, 5)
        self.ip_table.setHorizontalHeaderLabels(['通道', 'IP地址', '端口', '状态', '操作'])
        self.ip_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ip_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.ip_table.setMinimumWidth(300)  # 设置最小宽度

        # 设置大小策略，让表格能够铺满
        self.ip_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 设置列宽，使用比例而不是固定值
        self.ip_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.ip_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ip_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.ip_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.ip_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.ip_table.setColumnWidth(4, 80)

        # 确保滚动区域可调整大小
        scroll_area.setWidgetResizable(True)
        
        # 初始化默认通道
        self.ip_table.setItem(0, 0, QTableWidgetItem('Slot1'))
        
        scroll_layout.addWidget(self.ip_table)
        scroll_area.setWidget(scroll_widget)
        ip_layout.addWidget(scroll_area)
        
        ip_group.setLayout(ip_layout)
        right_layout.addWidget(ip_group)
        
        main_splitter.addWidget(right_widget)
        
        # 设置默认分割比例
        main_splitter.setSizes([400, 600])  # 适应1024宽度
        
        # 设置主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(main_splitter)
    
    def on_resize(self, event):
        """
        窗口大小变化时的处理
        """
        # 获取当前窗口大小
        width = event.size().width()
        height = event.size().height()
        
        # 根据窗口宽度调整分割比例
        if width < 900:
            # 低分辨率设备，增加右侧宽度比例
            if hasattr(self, 'centralWidget') and self.centralWidget():
                for child in self.centralWidget().children():
                    if isinstance(child, QSplitter):
                        child.setSizes([int(width * 0.35), int(width * 0.65)])
        else:
            # 高分辨率设备，恢复默认比例
            if hasattr(self, 'centralWidget') and self.centralWidget():
                for child in self.centralWidget().children():
                    if isinstance(child, QSplitter):
                        child.setSizes([int(width * 0.4), int(width * 0.6)])
    
    def send_command(self):
        """
        发送指令到所有已连接通道
        """
        command_with_params = self.param_input.text()
        
        if not command_with_params:
            self.log_message('请输入命令和参数')
            return
        
        # 解析命令和参数
        parts = command_with_params.split(' ')
        if len(parts) < 1:
            self.log_message('命令格式错误')
            return
        
        command = parts[0]
        args = []
        kwargs = {}
        
        # 解析参数，支持位置参数和关键字参数
        for part in parts[1:]:
            if '=' in part:
                # 关键字参数，格式为 key=value
                key, value = part.split('=', 1)
                kwargs[key] = value
            else:
                # 位置参数
                args.append(part)
        
        # 解析服务名和方法名
        if '.' in command:
            service_name, method_name = command.split('.', 1)
        else:
            self.log_message('命令格式错误，应为 service.method')
            return
        
        # 向所有已连接通道发送指令
        self.send_command_to_all_channels(service_name, method_name, command_with_params, *args, **kwargs)
        
        # 将命令添加到历史记录
        self.add_to_history(command_with_params)
    
    def send_command_to_all_channels(self, service_name, method_name, command_with_params, *args, **kwargs):
        """
        向所有已连接通道发送指令
        """
        # 遍历所有通道，发送指令到已连接的通道
        connected_channels = []
        for row in range(self.ip_table.rowCount()):
            status = self.ip_table.item(row, 3).text()
            if status == '已连接':
                channel_name = self.ip_table.item(row, 0).text()
                
                # 使用已保存的RPC客户端
                if row in self.rpc_clients:
                    client = self.rpc_clients[row]
                    try:
                        # 发送命令，支持位置参数和关键字参数
                        result = client.send_command(service_name, method_name, *args, **kwargs)
                        self.log_message(f'[{channel_name}] send:{command_with_params} \n recv:{result}')
                        connected_channels.append(channel_name)
                    except Exception as e:
                        self.log_message(f'[{channel_name}] 发送命令失败: {command_with_params}，错误: {str(e)}')
                else:
                    self.log_message(f'[{channel_name}] RPC客户端未找到，请重新连接')
        
        if connected_channels:
            # self.log_message(f'已向 {len(connected_channels)} 个已连接通道发送命令: {connected_channels}')
            # self.log_message(f'send:{connected_channels}')
            pass
        else:
            self.log_message('没有已连接的通道')
    
    def log_message(self, message):
        self.log_text.append(message)
        # 同时使用logger记录到文件
        from utils.logger import logger
        logger.info(message)
    
    def show_config_channel_dialog(self):
        """
        显示配置通道的弹出窗口
        """
        dialog = QDialog(self)
        dialog.setWindowTitle('配置通道')
        dialog.setGeometry(200, 200, 450, 250)
        
        layout = QGridLayout()
        
        # 通道数量
        layout.addWidget(QLabel('通道数量:'), 0, 0)
        count_spin = QSpinBox()
        count_spin.setRange(1, 24)
        count_spin.setValue(self.ip_table.rowCount())
        layout.addWidget(count_spin, 0, 1)
        
        # 起始IP
        layout.addWidget(QLabel('起始IP:'), 1, 0)
        ip_input = QLineEdit('192.168.99.33')
        layout.addWidget(ip_input, 1, 1)
        
        # 起始端口
        layout.addWidget(QLabel('起始端口:'), 2, 0)
        port_input = QLineEdit('7801')
        layout.addWidget(port_input, 2, 1)
        
        # 端口递增步长
        layout.addWidget(QLabel('端口递增步长:'), 3, 0)
        port_step = QLineEdit('0')
        port_step.setPlaceholderText('0表示不递增')
        layout.addWidget(port_step, 3, 1)
        
        # 按钮
        button_layout = QHBoxLayout()
        ok_btn = QPushButton('确定')
        cancel_btn = QPushButton('取消')
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout, 4, 0, 1, 2)
        
        dialog.setLayout(layout)
        
        def get_ip(slot, startNum=33, setp=1, mixVer="mix8"):
            """
            根据槽位号生成IP地址
            """
            sw1 = str(slot)[-1]
            sw2 = ('00' + str(slot))[-2]
            add_num = int(sw2) * 16 + int(sw1)
            add_num = add_num - 1
            add_num = int(add_num / int(setp))
            ip_address = int(startNum) + add_num
            if mixVer == "mix8":
                ip_address = "192.168.99." + str(ip_address)
            else:
                ip_address = "169.254.1." + str(ip_address)
            return ip_address
        
        def on_ok():
            count = count_spin.value()
            start_ip = ip_input.text()
            start_port = int(port_input.text())
            port_step_value = int(port_step.text()) if port_step.text() else 0
            
            # 提取起始IP的最后一段作为startNum
            start_num = int(start_ip.split('.')[-1])
            
            # 清除现有通道
            while self.ip_table.rowCount() > 0:
                self.ip_table.removeRow(0)
            
            # 添加新通道
            for i in range(count):
                slot_number = i + 1
                self.ip_table.insertRow(i)
                
                # 使用IP递增逻辑生成IP地址
                ip_address = get_ip(slot_number, start_num, 1, "mix8")
                
                # 计算端口号
                if port_step_value == 0:
                    port = start_port
                else:
                    port = start_port + (slot_number - 1) * port_step_value
                
                # 设置通道信息
                self.ip_table.setItem(i, 0, QTableWidgetItem(f'Slot{slot_number}'))
                self.ip_table.setItem(i, 1, QTableWidgetItem(ip_address))
                self.ip_table.setItem(i, 2, QTableWidgetItem(str(port)))
                self.ip_table.setItem(i, 3, QTableWidgetItem('未连接'))
                
                # 添加连接按钮
                connect_btn = QPushButton('连接')
                connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
                self.ip_table.setCellWidget(i, 4, connect_btn)
            
            self.log_message(f'配置了 {count} 个通道')
            # 保存通道配置到配置文件
            self.save_channels_to_config()
            dialog.accept()
        
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def save_commands_info(self, commands_info):
        """
        保存命令信息到json文件
        """
        # 获取配置目录
        config_dir = config_manager.get_config_dir()
        commands_file = os.path.join(config_dir, 'commands_info.json')
        
        try:
            with open(commands_file, 'w', encoding='utf-8') as f:
                json.dump(commands_info, f, ensure_ascii=False, indent=2)
            self.log_message(f"命令信息已保存到 {commands_file}")
        except Exception as e:
            self.log_message(f"保存命令信息失败: {str(e)}")
    
    def load_commands_info(self):
        """
        从json文件加载命令信息
        """
        # 获取配置目录
        config_dir = config_manager.get_config_dir()
        commands_file = os.path.join(config_dir, 'commands_info.json')
        
        try:
            if os.path.exists(commands_file):
                with open(commands_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.log_message(f"加载命令信息失败: {str(e)}")
        return {}
    
    def update_command_hints(self):
        """
        更新命令提示
        """
        # 加载命令信息
        commands_info = self.load_commands_info()
        
        # 构建命令列表
        commands = []
        for service, methods in commands_info.items():
            for method in methods:
                commands.append(f"{service}.{method}")
        
        # 保存命令列表供show_command_hints使用
        self.commands_list = commands
    
    def connect_channel(self, row):
        """
        连接通道
        """
        channel_name = self.ip_table.item(row, 0).text()
        ip = self.ip_table.item(row, 1).text()
        port = self.ip_table.item(row, 2).text()
        
        connect_btn = self.ip_table.cellWidget(row, 4)
        
        if connect_btn.text() == '连接':
            self.log_message(f'正在连接通道: {channel_name} ({ip}:{port})')
            
            # 尝试实际连接到MIX8设备
            from core.rpc_client import RpcClient
            client = RpcClient(ip, port, log_callback=self.log_message)
            
            # 调用connect方法进行连接
            if client.connect():
                self.log_message(f'通道 {channel_name} 连接成功！')
                # 保存RPC客户端到字典
                self.rpc_clients[row] = client
                # 更新状态和按钮
                self.ip_table.setItem(row, 3, QTableWidgetItem('已连接'))
                connect_btn.setText('断开')
                
                # 获取所有命令信息并保存
                commands_info = client.get_all_commands()
                if commands_info:
                    self.save_commands_info(commands_info)
                    # 刷新命令提示
                    self.update_command_hints()
            else:
                self.log_message(f'通道 {channel_name} 连接失败！')
                # 保持状态和按钮不变
        else:
            self.log_message(f'正在断开通道: {channel_name}')
            
            # 断开连接
            if row in self.rpc_clients:
                del self.rpc_clients[row]
            self.log_message(f'通道 {channel_name} 断开成功！')
            
            # 更新状态和按钮
            self.ip_table.setItem(row, 3, QTableWidgetItem('未连接'))
            connect_btn.setText('连接')
    

    
    def batch_connect(self):
        """
        批量连接选中的通道
        """
        # 获取选中的行
        selected_rows = set()
        for item in self.ip_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要连接的通道')
            return
        
        # 连接选中的通道
        for row in selected_rows:
            connect_btn = self.ip_table.cellWidget(row, 4)
            if connect_btn.text() == '连接':
                self.connect_channel(row)
    
    def batch_disconnect(self):
        """
        批量断开选中的通道
        """
        # 获取选中的行
        selected_rows = set()
        for item in self.ip_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要断开的通道')
            return
        
        # 断开选中的通道
        for row in selected_rows:
            connect_btn = self.ip_table.cellWidget(row, 4)
            if connect_btn.text() == '断开':
                self.connect_channel(row)
    
    def load_channels_from_config(self):
        """
        从配置文件加载通道配置
        """
        # 清除现有通道
        while self.ip_table.rowCount() > 0:
            self.ip_table.removeRow(0)
        
        # 从配置文件加载通道
        channels = config_manager.get_channels()
        for i, channel in enumerate(channels):
            self.ip_table.insertRow(i)
            self.ip_table.setItem(i, 0, QTableWidgetItem(channel['name']))
            self.ip_table.setItem(i, 1, QTableWidgetItem(channel['ip']))
            self.ip_table.setItem(i, 2, QTableWidgetItem(channel['port']))
            self.ip_table.setItem(i, 3, QTableWidgetItem('未连接'))
            
            # 添加连接按钮
            connect_btn = QPushButton('连接')
            connect_btn.setMinimumWidth(80)
            connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
            self.ip_table.setCellWidget(i, 4, connect_btn)
        
        self.log_message(f'从配置文件加载了 {len(channels)} 个通道')
    
    def save_channels_to_config(self):
        """
        保存通道配置到配置文件
        """
        channels = []
        for i in range(self.ip_table.rowCount()):
            channel = {
                'name': self.ip_table.item(i, 0).text(),
                'ip': self.ip_table.item(i, 1).text(),
                'port': self.ip_table.item(i, 2).text()
            }
            channels.append(channel)
        
        config = config_manager.config
        config['channels'] = channels
        if config_manager.save_config(config):
            self.log_message('通道配置已保存到配置文件')
        else:
            self.log_message('保存通道配置失败')
    
    def show_command_hints(self):
        """
        显示命令提示
        """
        text = self.cmd_input.text()
        if not text:
            self.command_hint_list.hide()
            return
        
        # 使用已加载的命令列表
        commands = getattr(self, 'commands_list', [])
        
        # 过滤匹配的命令
        matched_commands = [cmd for cmd in commands if text.lower() in cmd.lower()]
        
        if matched_commands:
            self.command_hint_list.clear()
            for cmd in matched_commands:
                item = QListWidgetItem(cmd)
                self.command_hint_list.addItem(item)
            self.command_hint_list.show()
        else:
            self.command_hint_list.hide()
    
    def select_command(self, item):
        """
        选择命令
        """
        command = item.text()
        self.cmd_input.setText(command)
        # 自动复制到param_input
        self.param_input.setText(command)
        self.command_hint_list.hide()
        # 显示命令详细说明
        self.show_command_doc(command)
    
    def show_command_doc(self, command):
        """
        显示命令详细说明
        """
        # 从json文件加载命令信息
        commands_info = self.load_commands_info()
        
        # 解析命令，获取服务名和方法名
        if '.' in command:
            service_name, method_name = command.split('.', 1)
            
            # 查找命令信息
            if service_name in commands_info and method_name in commands_info[service_name]:
                command_info = commands_info[service_name][method_name]
                doc = command_info.get('doc', '无说明')
                params = command_info.get('params', [])
                
                # 格式化参数
                if isinstance(params, list):
                    params_str = ', '.join(params) if params else '无参数'
                else:
                    params_str = str(params)
                
                # 在主界面的命令信息区域显示
                info_text = f"命令: {command}\n\n说明: {doc}\n\n参数: {params_str}"
                self.cmd_info_text.setPlainText(info_text)
            else:
                self.cmd_info_text.setPlainText('命令信息未找到')
        else:
            self.cmd_info_text.setPlainText('命令格式错误')
    
    def copy_command_to_param(self):
        """
        将命令从cmd_input复制到param_input
        """
        command = self.cmd_input.text()
        if command:
            self.param_input.setText(command)
    
    def load_history_from_config(self):
        """
        从配置文件加载历史指令
        """
        history = config_manager.get_history()
        for command in history:
            self.history_list.addItem(command)
    
    def add_to_history(self, command):
        """
        将命令添加到历史记录
        """
        # 检查命令是否已经存在于历史记录中
        for i in range(self.history_list.count()):
            if self.history_list.item(i).text() == command:
                # 如果命令已存在，将其移到列表顶部
                self.history_list.takeItem(i)
                break
        
        # 在列表顶部添加新命令
        self.history_list.insertItem(0, command)
        
        # 限制历史记录数量
        if self.history_list.count() > 50:
            self.history_list.takeItem(self.history_list.count() - 1)
        
        # 保存历史记录到配置文件
        history = []
        for i in range(self.history_list.count()):
            history.append(self.history_list.item(i).text())
        config_manager.save_history(history)
    
    def select_history_command(self, item):
        """
        选择历史命令并发送
        """
        command = item.text()
        self.param_input.setText(command)
        # 直接发送命令
        self.send_command()
    
    def show_history_context_menu(self, position):
        """
        显示历史命令的右键菜单
        """
        item = self.history_list.itemAt(position)
        if item:
            menu = QMenu()
            add_to_sequence_action = menu.addAction("添加到序列")
            delete_action = menu.addAction("删除")
            action = menu.exec(self.history_list.mapToGlobal(position))
            if action == delete_action:
                # 删除历史命令
                row = self.history_list.row(item)
                self.history_list.takeItem(row)
                # 更新配置文件
                history = []
                for i in range(self.history_list.count()):
                    history.append(self.history_list.item(i).text())
                config_manager.save_history(history)
            elif action == add_to_sequence_action:
                # 添加到序列列表
                command = item.text()
                sequence_item = QListWidgetItem(f"[CMD] {command}")
                sequence_item.setCheckState(Qt.CheckState.Checked)
                self.sequence_list.addItem(sequence_item)
                self.log_message(f"已添加指令到序列: {command}")
    
    def show_sequence_context_menu(self, position):
        """
        显示序列列表的右键菜单
        """
        item = self.sequence_list.itemAt(position)
        if item:
            menu = QMenu()
            modify_action = menu.addAction("修改")
            delete_action = menu.addAction("删除")
            action = menu.exec(self.sequence_list.mapToGlobal(position))
            if action == modify_action:
                # 修改序列项
                self.modify_sequence_item(item)
            elif action == delete_action:
                # 删除序列项
                row = self.sequence_list.row(item)
                self.sequence_list.takeItem(row)
                self.log_message("已从序列中删除指令")
    
    def modify_sequence_item(self, item):
        """
        修改序列项
        """
        text = item.text()
        row = self.sequence_list.row(item)
        
        if text.startswith('[CMD]'):
            # 修改指令
            current_command = text[5:].strip()
            from PyQt6.QtWidgets import QInputDialog
            new_command, ok = QInputDialog.getText(self, '修改指令', '请输入新的指令和参数:', text=current_command)
            if ok:
                item.setText(f"[CMD] {new_command}")
                self.log_message(f"已修改序列中的指令: {new_command}")
        elif text.startswith('[DELAY]'):
            # 修改延迟
            current_delay = text[7:].replace('ms', '').strip()
            from PyQt6.QtWidgets import QInputDialog
            new_delay, ok = QInputDialog.getInt(self, '修改延迟', '请输入新的延迟时间（毫秒）:', int(current_delay), 1, 30000)
            if ok:
                item.setText(f"[DELAY] {new_delay}ms")
                self.log_message(f"已修改序列中的延迟: {new_delay}ms")
        elif text.startswith('[PAUSE]'):
            # 修改暂停
            current_message = text[7:].strip()
            from PyQt6.QtWidgets import QInputDialog
            new_message, ok = QInputDialog.getText(self, '修改暂停', '请输入新的暂停提示信息:', text=current_message)
            if ok:
                item.setText(f"[PAUSE] {new_message}")
                self.log_message(f"已修改序列中的暂停: {new_message}")
    
    def add_command_to_sequence(self):
        """
        添加指令到序列列表
        """
        command = self.param_input.text()
        if command:
            # 添加指令到序列列表
            item = QListWidgetItem(f"[CMD] {command}")
            item.setCheckState(Qt.CheckState.Checked)
            self.sequence_list.addItem(item)
            self.log_message(f"已添加指令到序列: {command}")
        else:
            self.log_message('请先输入指令和参数')
    
    def add_delay_to_sequence(self):
        """
        添加延迟到序列列表
        """
        # 弹出输入延迟时间的对话框
        from PyQt6.QtWidgets import QInputDialog
        delay, ok = QInputDialog.getInt(self, '添加延迟', '请输入延迟时间（毫秒）:', 1000, 1, 30000)
        if ok:
            # 添加延迟到序列列表
            item = QListWidgetItem(f"[DELAY] {delay}ms")
            item.setCheckState(Qt.CheckState.Checked)
            self.sequence_list.addItem(item)
            self.log_message(f"已添加延迟到序列: {delay}ms")
    
    def add_pause_to_sequence(self):
        """
        添加暂停到序列列表
        """
        # 弹出输入暂停提示信息的对话框
        from PyQt6.QtWidgets import QInputDialog
        message, ok = QInputDialog.getText(self, '添加暂停', '请输入暂停提示信息:', text='执行到此处，是否继续？')
        if ok:
            # 添加暂停到序列列表
            item = QListWidgetItem(f"[PAUSE] {message}")
            item.setCheckState(Qt.CheckState.Checked)
            self.sequence_list.addItem(item)
            self.log_message(f"已添加暂停到序列: {message}")
    
    def execute_sequence(self):
        """
        执行指令序列
        """
        # 检查是否有通道连接
        if not self.rpc_clients:
            self.log_message('没有已连接的通道，请先连接通道')
            return
        
        if self.sequence_list.count() == 0:
            self.log_message('序列为空，请先添加指令或延迟')
            return
        
        self.log_message('开始执行指令序列...')
        
        # 遍历序列列表，执行每个勾选的指令或延迟
        for i in range(self.sequence_list.count()):
            item = self.sequence_list.item(i)
            # 检查是否勾选
            if item.checkState() != Qt.CheckState.Checked:
                continue
            
            text = item.text()
            
            if text.startswith('[CMD]'):
                # 执行指令
                command = text[5:].strip()
                self.log_message(f'[序列] 执行指令: {command}')
                
                # 解析命令和参数
                parts = command.split(' ')
                if len(parts) < 1:
                    self.log_message('[序列] 命令格式错误')
                    continue
                
                cmd = parts[0]
                args = []
                kwargs = {}
                
                # 解析参数，支持位置参数和关键字参数
                for part in parts[1:]:
                    if '=' in part:
                        # 关键字参数，格式为 key=value
                        key, value = part.split('=', 1)
                        kwargs[key] = value
                    else:
                        # 位置参数
                        args.append(part)
                
                # 解析服务名和方法名
                if '.' in cmd:
                    service_name, method_name = cmd.split('.', 1)
                else:
                    self.log_message('[序列] 命令格式错误，应为 service.method')
                    continue
                
                # 向所有已连接通道发送指令
                self.send_command_to_all_channels(service_name, method_name, command, *args, **kwargs)
            elif text.startswith('[DELAY]'):
                # 执行延迟
                delay_str = text[7:].replace('ms', '').strip()
                try:
                    delay = int(delay_str)
                    self.log_message(f'[序列] 执行延迟: {delay}ms')
                    # 使用QTimer进行延迟
                    from PyQt6.QtCore import QTimer
                    # 创建一个临时的QTimer
                    timer = QTimer(self)
                    # 单次触发
                    timer.setSingleShot(True)
                    # 启动定时器
                    timer.start(delay)
                    # 等待定时器完成
                    from PyQt6.QtCore import QEventLoop
                    loop = QEventLoop()
                    timer.timeout.connect(loop.quit)
                    loop.exec()
                except ValueError:
                    self.log_message(f'[序列] 延迟时间格式错误: {delay_str}')
            elif text.startswith('[PAUSE]'):
                # 执行暂停
                pause_message = text[7:].strip()
                self.log_message(f'[序列] 执行暂停: {pause_message}')
                
                # 弹出对话框，提示用户是否继续
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(self, '序列暂停', 
                                           pause_message, 
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                           QMessageBox.StandardButton.No)
                
                if reply == QMessageBox.StandardButton.No:
                    # 用户选择停止，退出循环
                    self.log_message('[序列] 用户选择停止执行')
                    return
        
        self.log_message('指令序列执行完成')
    
    def clear_sequence(self):
        """
        清空序列
        """
        self.sequence_list.clear()
        self.log_message('序列已清空')
    
    def save_sequence_group(self):
        """
        保存当前序列组到CSV文件
        """
        if self.sequence_list.count() == 0:
            self.log_message('序列为空，无法保存')
            return
        
        # 获取配置目录
        config_dir = config_manager.get_config_dir()
        
        # 弹出输入文件名对话框
        from PyQt6.QtWidgets import QInputDialog
        filename, ok = QInputDialog.getText(self, '保存序列组', '请输入文件名（不含扩展名）:', text='sequence_group')
        if not ok or not filename:
            return
        
        # 确保文件名以.csv结尾
        if not filename.endswith('.csv'):
            filename += '.csv'
        
        # 构建完整路径
        filepath = os.path.join(config_dir, filename)
        
        try:
            # 保存序列到CSV文件
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['type', 'content', 'checked'])
                for i in range(self.sequence_list.count()):
                    item = self.sequence_list.item(i)
                    text = item.text()
                    checked = '1' if item.checkState() == Qt.CheckState.Checked else '0'
                    if text.startswith('[CMD]'):
                        writer.writerow(['CMD', text[5:].strip(), checked])
                    elif text.startswith('[DELAY]'):
                        writer.writerow(['DELAY', text[7:].replace('ms', '').strip(), checked])
                    elif text.startswith('[PAUSE]'):
                        writer.writerow(['PAUSE', text[7:].strip(), checked])
            
            self.log_message(f'序列组已保存到: {filepath}')
        except Exception as e:
            self.log_message(f'保存序列组失败: {str(e)}')
    
    def load_sequence_group(self):
        """
        加载已保存的序列组
        """
        # 获取配置目录
        config_dir = config_manager.get_config_dir()
        
        # 获取所有CSV文件
        import glob
        csv_files = glob.glob(os.path.join(config_dir, '*.csv'))
        
        if not csv_files:
            self.log_message('没有找到保存的序列组')
            return
        
        # 提取文件名（不含路径和扩展名）
        file_names = [os.path.splitext(os.path.basename(f))[0] for f in csv_files]
        
        # 弹出选择对话框
        from PyQt6.QtWidgets import QInputDialog
        group_name, ok = QInputDialog.getItem(self, '加载序列组', '选择要加载的序列组:', file_names, 0, False)
        if not ok or not group_name:
            return
        
        # 构建完整路径
        filepath = os.path.join(config_dir, group_name + '.csv')
        
        try:
            # 清空当前序列列表
            self.sequence_list.clear()
            
            # 从CSV文件加载序列
            with open(filepath, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)  # 跳过表头
                for row in reader:
                    if len(row) >= 3:
                        item_type, content, checked = row[0], row[1], row[2]
                        if item_type == 'CMD':
                            item = QListWidgetItem(f"[CMD] {content}")
                        elif item_type == 'DELAY':
                            item = QListWidgetItem(f"[DELAY] {content}ms")
                        elif item_type == 'PAUSE':
                            item = QListWidgetItem(f"[PAUSE] {content}")
                        else:
                            continue
                        
                        # 设置勾选状态
                        if checked == '1':
                            item.setCheckState(Qt.CheckState.Checked)
                        else:
                            item.setCheckState(Qt.CheckState.Unchecked)
                        
                        self.sequence_list.addItem(item)
            
            # 更新序列组标题
            self.sequence_group.setTitle(f'指令序列 - {group_name}')
            self.log_message(f'已加载序列组: {group_name}')
        except Exception as e:
            self.log_message(f'加载序列组失败: {str(e)}')