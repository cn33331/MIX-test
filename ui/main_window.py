import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                            QLabel, QLineEdit, QPushButton, QTextEdit, 
                            QTableWidget, QTableWidgetItem, QGroupBox, 
                            QDialog, QSpinBox, QGridLayout, QScrollArea, QComboBox,
                            QCompleter, QListWidget, QListWidgetItem, QMenu, QSplitter, QHeaderView, QSizePolicy)
from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.uic import loadUi
from utils.config import config_manager
import json
import os
import csv
import glob

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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.version = 'v1.6'
        # 从ui文件加载UI
        ui_path = get_resource_path('ui/main_window.ui')
        loadUi(ui_path, self)
        self.setWindowTitle(f'MIX-debug {self.version} by:zjx')
        self.rpc_clients = {}  # 保存已连接的RPC客户端
        self.last_sequence_file = None  # 保存最后加载的序列文件路径
        self.init_signals()
        self.load_channels_from_config()
        self.load_history_from_config()
        # 连接窗口大小变化信号
        self.resizeEvent = self.on_resize
    
    def init_signals(self):
        """
        初始化信号连接
        """
        # 命令输入信号
        self.cmdInput.returnPressed.connect(self.copy_command_to_param)
        
        # 发送指令按钮
        self.sendCmdButton.clicked.connect(self.send_command)
        
        # 历史记录信号
        self.historyList.itemDoubleClicked.connect(self.select_history_command)
        self.historyList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.historyList.customContextMenuRequested.connect(self.show_history_context_menu)
        
        # 序列列表信号
        self.sequenceList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sequenceList.customContextMenuRequested.connect(self.show_sequence_context_menu)
        
        # 执行序列按钮
        self.executeSequenceButton.clicked.connect(self.execute_sequence)
        
        # 日志显示信号
        self.logText.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.logText.customContextMenuRequested.connect(self.show_log_context_menu)
        
        # 通道列表信号
        self.ipTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ipTable.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.ipTable.cellChanged.connect(self.on_cell_changed)
        
        # 初始化命令自动完成
        self.cmd_model = QStringListModel()
        completer = QCompleter(self.cmd_model, self)
        completer.activated.connect(self.select_command)
        self.cmdInput.setCompleter(completer)
        
        # 设置表格列宽
        self.ipTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ipTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        # 设置表格大小策略
        self.ipTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    
    def on_resize(self, event):
        """
        窗口大小变化时的处理
        """
        # 获取当前窗口大小
        width = event.size().width()
        height = event.size().height()
        
        # 右侧固定宽度
        right_width = 450  # 设置右侧固定宽度为400像素
        left_width = max(450, width - right_width)  # 左侧宽度为窗口宽度减去右侧宽度，最小400像素
        
        # 设置分割器大小
        if hasattr(self, 'centralWidget') and self.centralWidget:
            for child in self.centralWidget.children():
                if isinstance(child, QSplitter):
                    child.setSizes([int(left_width), int(right_width)])
    
    def send_command(self):
        """
        发送指令到所有已连接通道
        """
        command_with_params = self.paramInput.text()
        
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
        for row in range(self.ipTable.rowCount()):
            status = self.ipTable.item(row, 3).text()
            if status == '已连接':
                channel_name = self.ipTable.item(row, 0).text()
                
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
        self.logText.append(message)
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
        count_spin.setValue(self.ipTable.rowCount())
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
            while self.ipTable.rowCount() > 0:
                self.ipTable.removeRow(0)
            
            # 添加新通道
            for i in range(count):
                slot_number = i + 1
                self.ipTable.insertRow(i)
                
                # 使用IP递增逻辑生成IP地址
                ip_address = get_ip(slot_number, start_num, 1, "mix8")
                
                # 计算端口号
                if port_step_value == 0:
                    port = start_port
                else:
                    port = start_port + (slot_number - 1) * port_step_value
                
                # 设置通道信息
                self.ipTable.setItem(i, 0, QTableWidgetItem(f'Slot{slot_number}'))
                self.ipTable.setItem(i, 1, QTableWidgetItem(ip_address))
                self.ipTable.setItem(i, 2, QTableWidgetItem(str(port)))
                self.ipTable.setItem(i, 3, QTableWidgetItem('未连接'))
                
                # 添加连接按钮
                connect_btn = QPushButton('连接')
                connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
                self.ipTable.setCellWidget(i, 4, connect_btn)
            
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
        
        # 更新自动完成
        self.cmd_model.setStringList(commands)
    
    def connect_channel(self, row):
        """
        连接通道
        """
        channel_name = self.ipTable.item(row, 0).text()
        ip = self.ipTable.item(row, 1).text()
        port = self.ipTable.item(row, 2).text()
        
        connect_btn = self.ipTable.cellWidget(row, 4)
        
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
                self.ipTable.setItem(row, 3, QTableWidgetItem('已连接'))
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
            self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
            connect_btn.setText('连接')
    

    
    def batch_connect(self):
        """
        批量连接选中的通道
        """
        # 获取选中的行
        selected_rows = set()
        for item in self.ipTable.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要连接的通道')
            return
        
        # 连接选中的通道
        for row in selected_rows:
            connect_btn = self.ipTable.cellWidget(row, 4)
            if connect_btn.text() == '连接':
                self.connect_channel(row)
    
    def batch_disconnect(self):
        """
        批量断开选中的通道
        """
        # 获取选中的行
        selected_rows = set()
        for item in self.ipTable.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要断开的通道')
            return
        
        # 断开选中的通道
        for row in selected_rows:
            connect_btn = self.ipTable.cellWidget(row, 4)
            if connect_btn.text() == '断开':
                self.connect_channel(row)
    
    def load_channels_from_config(self):
        """
        从配置文件加载通道配置
        """
        # 暂时断开cellChanged信号连接，避免加载时触发保存
        self.ipTable.cellChanged.disconnect(self.on_cell_changed)
        
        # 清除现有通道
        while self.ipTable.rowCount() > 0:
            self.ipTable.removeRow(0)
        
        # 从配置文件加载通道
        channels = config_manager.get_channels()
        for i, channel in enumerate(channels):
            self.ipTable.insertRow(i)
            self.ipTable.setItem(i, 0, QTableWidgetItem(channel['name']))
            self.ipTable.setItem(i, 1, QTableWidgetItem(channel['ip']))
            self.ipTable.setItem(i, 2, QTableWidgetItem(channel['port']))
            self.ipTable.setItem(i, 3, QTableWidgetItem('未连接'))
            
            # 添加连接按钮
            connect_btn = QPushButton('连接')
            connect_btn.setMinimumWidth(40)
            connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
            self.ipTable.setCellWidget(i, 4, connect_btn)
        
        self.log_message(f'从配置文件加载了 {len(channels)} 个通道')
        
        # 重新连接cellChanged信号
        self.ipTable.cellChanged.connect(self.on_cell_changed)
    
    def save_channels_to_config(self):
        """
        保存通道配置到配置文件
        """
        channels = []
        for i in range(self.ipTable.rowCount()):
            # 安全获取单元格值，处理NoneType情况
            name_item = self.ipTable.item(i, 0)
            ip_item = self.ipTable.item(i, 1)
            port_item = self.ipTable.item(i, 2)
            
            name = name_item.text() if name_item else f'Slot{i+1}'
            ip = ip_item.text() if ip_item else ''
            port = port_item.text() if port_item else '7801'
            
            channel = {
                'name': name,
                'ip': ip,
                'port': port
            }
            channels.append(channel)
        
        config = config_manager.config
        config['channels'] = channels
        if config_manager.save_config(config):
            # self.log_message('通道配置已保存到配置文件')
            # 打印配置文件路径，方便调试
            print(f"配置文件已保存到: {config_manager.config_file}")
        else:
            self.log_message('保存通道配置失败')
    
    def select_command(self, command):
        """
        选择命令
        """
        # 如果参数是QListWidgetItem，获取其文本
        if hasattr(command, 'text'):
            command = command.text()
        
        self.cmdInput.setText(command)
        # 自动复制到paramInput
        self.paramInput.setText(command)
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
                self.cmdInfoText.setPlainText(info_text)
            else:
                self.cmdInfoText.setPlainText('命令信息未找到')
        else:
            self.cmdInfoText.setPlainText('命令格式错误')
    
    def copy_command_to_param(self):
        """
        将命令从cmdInput复制到paramInput
        """
        command = self.cmdInput.text()
        if command:
            self.paramInput.setText(command)
    
    def load_history_from_config(self):
        """
        从配置文件加载历史指令
        """
        history = config_manager.get_history()
        for command in history:
            self.historyList.addItem(command)
    
    def add_to_history(self, command):
        """
        将命令添加到历史记录
        """
        # 检查命令是否已经存在于历史记录中
        for i in range(self.historyList.count()):
            if self.historyList.item(i).text() == command:
                # 如果命令已存在，将其移到列表顶部
                self.historyList.takeItem(i)
                break
        
        # 在列表顶部添加新命令
        self.historyList.insertItem(0, command)
        
        # 限制历史记录数量
        if self.historyList.count() > 50:
            self.historyList.takeItem(self.historyList.count() - 1)
        
        # 保存历史记录到配置文件
        history = []
        for i in range(self.historyList.count()):
            history.append(self.historyList.item(i).text())
        config_manager.save_history(history)
    
    def select_history_command(self, item):
        """
        选择历史命令并发送
        """
        command = item.text()
        self.paramInput.setText(command)
        # 直接发送命令
        self.send_command()
    
    def show_history_context_menu(self, position):
        """
        显示历史命令的右键菜单
        """
        menu = QMenu()
        
        # 清空所有内容
        clear_all_action = menu.addAction("清空所有内容")
        
        # 如果有选中项，添加其他选项
        item = self.historyList.itemAt(position)
        if item:
            menu.addSeparator()
            add_to_sequence_action = menu.addAction("添加到序列")
            delete_action = menu.addAction("删除")
        
        action = menu.exec(self.historyList.mapToGlobal(position))
        
        if action == clear_all_action:
            # 清空所有历史指令
            self.clear_history()
        elif item and action == delete_action:
            # 删除历史命令
            row = self.historyList.row(item)
            self.historyList.takeItem(row)
            # 更新配置文件
            history = []
            for i in range(self.historyList.count()):
                history.append(self.historyList.item(i).text())
            config_manager.save_history(history)
        elif item and action == add_to_sequence_action:
            # 添加到序列列表
            command = item.text()
            sequence_item = QListWidgetItem(f"[CMD] {command}")
            sequence_item.setCheckState(Qt.CheckState.Checked)
            self.sequenceList.addItem(sequence_item)
            self.log_message(f"已添加指令到序列: {command}")
    
    def show_log_context_menu(self, pos):
        """
        显示日志右键菜单
        """
        menu = QMenu()
        clear_all_action = menu.addAction("清空所有内容")
        
        action = menu.exec(self.logText.mapToGlobal(pos))
        
        if action == clear_all_action:
            # 清空所有日志
            self.clear_log()
    
    def clear_history(self):
        """
        清空所有历史指令
        """
        self.historyList.clear()
        config_manager.save_history([])
        self.log_message("已清空所有历史指令")
    
    def clear_log(self):
        """
        清空所有日志
        """
        self.logText.clear()
        # self.log_message("已清空所有日志")
    
    def open_sequence_file(self):
        """
        打开序列组原始文件
        """
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        
        if self.last_sequence_file:
            try:
                # 使用系统默认应用程序打开文件
                url = QUrl.fromLocalFile(self.last_sequence_file)
                QDesktopServices.openUrl(url)
                self.log_message(f"已打开序列组文件: {self.last_sequence_file}")
            except Exception as e:
                self.log_message(f"打开序列组文件失败: {str(e)}")
        else:
            self.log_message("请先加载一个序列组")
    
    def show_sequence_context_menu(self, position):
        """
        显示序列列表的右键菜单
        """
        menu = QMenu()
        
        # 添加功能选项
        add_delay_action = menu.addAction("添加延迟")
        add_pause_action = menu.addAction("添加暂停")
        menu.addSeparator()
        clear_sequence_action = menu.addAction("清空序列")
        save_sequence_action = menu.addAction("保存序列组")
        load_sequence_action = menu.addAction("加载序列组")
        open_sequence_file_action = menu.addAction("打开序列组原始文件")
        
        # 如果有选中项，添加修改和删除选项
        item = self.sequenceList.itemAt(position)
        if item:
            menu.addSeparator()
            modify_action = menu.addAction("修改")
            delete_action = menu.addAction("删除")
        
        action = menu.exec(self.sequenceList.mapToGlobal(position))
        
        # 处理菜单项
        if action == add_delay_action:
            self.add_delay_to_sequence()
        elif action == add_pause_action:
            self.add_pause_to_sequence()
        elif action == clear_sequence_action:
            self.clear_sequence()
        elif action == save_sequence_action:
            self.save_sequence_group()
        elif action == load_sequence_action:
            self.load_sequence_group()
        elif action == open_sequence_file_action:
            self.open_sequence_file()
        elif item and action == modify_action:
            # 修改序列项
            self.modify_sequence_item(item)
        elif item and action == delete_action:
            # 删除序列项
            row = self.sequenceList.row(item)
            self.sequenceList.takeItem(row)
            self.log_message("已从序列中删除指令")
    
    def show_channel_context_menu(self, pos):
        """
        显示通道列表右键菜单
        """
        menu = QMenu()
        
        # 新增一行
        add_row_action = menu.addAction("新增一行")
        add_row_action.triggered.connect(self.add_channel_row)
        
        # 配置通道
        config_action = menu.addAction("配置通道")
        config_action.triggered.connect(self.show_config_channel_dialog)
        
        # 批量连接
        connect_action = menu.addAction("批量连接")
        connect_action.triggered.connect(self.batch_connect)
        
        # 批量断开
        disconnect_action = menu.addAction("批量断开")
        disconnect_action.triggered.connect(self.batch_disconnect)
        
        menu.exec(self.ipTable.mapToGlobal(pos))
    
    def on_cell_changed(self, row, column):
        """
        单元格修改完成事件，自动保存到配置文件
        """
        # 保存通道配置到配置文件
        self.save_channels_to_config()
        
        # 如果修改的是IP地址或端口，更新状态为未连接
        if column == 1 or column == 2:  # IP地址或端口列
            self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
    
    def add_channel_row(self):
        """
        新增一行通道配置
        """
        row = self.ipTable.rowCount()
        self.ipTable.insertRow(row)
        
        # 设置默认值
        self.ipTable.setItem(row, 0, QTableWidgetItem(f'Slot{row+1}'))
        self.ipTable.setItem(row, 1, QTableWidgetItem(''))
        self.ipTable.setItem(row, 2, QTableWidgetItem('7801'))
        self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
        
        # 添加连接按钮
        connect_btn = QPushButton('连接')
        connect_btn.setMinimumWidth(40)
        connect_btn.clicked.connect(lambda _, r=row: self.connect_channel(r))
        self.ipTable.setCellWidget(row, 4, connect_btn)
        
        # 保存到配置文件
        self.save_channels_to_config()
        
        self.log_message(f'已新增通道: Slot{row+1}')
    
    def modify_sequence_item(self, item):
        """
        修改序列项
        """
        text = item.text()
        row = self.sequenceList.row(item)
        
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
            self.sequenceList.addItem(item)
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
            self.sequenceList.addItem(item)
            self.log_message(f"已添加暂停到序列: {message}")
    
    def execute_sequence(self):
        """
        执行指令序列
        """
        # 检查是否有通道连接
        if not self.rpc_clients:
            self.log_message('没有已连接的通道，请先连接通道')
            return
        
        if self.sequenceList.count() == 0:
            self.log_message('序列为空，请先添加指令或延迟')
            return
        
        self.log_message('开始执行指令序列...')
        
        # 遍历序列列表，执行每个勾选的指令或延迟
        for i in range(self.sequenceList.count()):
            item = self.sequenceList.item(i)
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
        self.sequenceList.clear()
        self.log_message('序列已清空')
    
    def save_sequence_group(self):
        """
        保存当前序列组到CSV文件
        """
        if self.sequenceList.count() == 0:
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
                for i in range(self.sequenceList.count()):
                    item = self.sequenceList.item(i)
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
        # 保存文件路径
        self.last_sequence_file = filepath
        
        try:
            # 清空当前序列列表
            self.sequenceList.clear()
            
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
                        
                        self.sequenceList.addItem(item)
            
            # 更新序列组标题
            self.sequenceGroup.setTitle(f'指令序列 - {group_name}')
            self.log_message(f'已加载序列组: {group_name}')
        except Exception as e:
            self.log_message(f'加载序列组失败: {str(e)}')