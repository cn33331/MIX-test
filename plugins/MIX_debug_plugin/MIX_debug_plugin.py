import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                            QLabel, QLineEdit, QPushButton, QTextEdit, 
                            QTableWidget, QTableWidgetItem, QGroupBox, 
                            QDialog, QSpinBox, QGridLayout, QScrollArea, QComboBox,
                            QCompleter, QListWidget, QListWidgetItem, QMenu, QSplitter, QHeaderView, QSizePolicy)
from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.uic import loadUi
import json
import os
import csv
import glob

# 添加插件目录到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

# 导入本地的rpc_client
from rpc_client import RpcClient

# 添加mix目录到路径
mix_dir = os.path.join(PLUGIN_DIR, 'mix')
if mix_dir not in sys.path:
    sys.path.insert(0, mix_dir)

def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径（插件目录在外部，不从MEIPASS加载）
    """
    return os.path.join(PLUGIN_DIR, relative_path)

class MIXDebugPlugin(QMainWindow):
    """
    MIX调试插件主窗口
    """
    def __init__(self):
        super().__init__()
        self.version = 'v2.0'
        # 从插件目录加载UI文件
        ui_path = get_resource_path('MIX_debug_plugin.ui')
        loadUi(ui_path, self)
        self.setWindowTitle(f'MIX-debug {self.version} by:zjx')
        self.rpc_clients = {}
        self.last_sequence_file = None
        self.init_signals()
        self.load_channels_from_config()
        self.load_history_from_config()
        self.resizeEvent = self.on_resize
        self.sequence = False
    
    def get_widget(self):
        """
        返回插件的主窗口部件
        """
        return self
    
    def get_name(self):
        """
        返回插件名称
        """
        return f'MIX_debug {self.version}'
    
    def init_signals(self):
        """
        初始化信号连接
        """
        self.cmdInput.returnPressed.connect(self.copy_command_to_param)
        self.sendCmdButton.clicked.connect(self.send_command)
        self.historyList.itemDoubleClicked.connect(self.select_history_command)
        self.historyList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.historyList.customContextMenuRequested.connect(self.show_history_context_menu)
        self.sequenceList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sequenceList.customContextMenuRequested.connect(self.show_sequence_context_menu)
        self.executeSequenceButton.clicked.connect(self.execute_sequence)
        self.logText.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.logText.customContextMenuRequested.connect(self.show_log_context_menu)
        self.ipTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ipTable.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.ipTable.cellChanged.connect(self.on_cell_changed)
        
        self.cmd_model = QStringListModel()
        completer = QCompleter(self.cmd_model, self)
        completer.activated.connect(self.select_command)
        self.cmdInput.setCompleter(completer)
        
        self.ipTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ipTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.ipTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    
    def on_resize(self, event):
        """
        窗口大小变化时的处理
        """
        width = event.size().width()
        height = event.size().height()
        right_width = 450
        left_width = max(450, width - right_width)
        
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
        
        parts = command_with_params.split(' ')
        if len(parts) < 1:
            self.log_message('命令格式错误')
            return
        
        command = parts[0]
        args = []
        kwargs = {}
        
        for part in parts[1:]:
            if '=' in part:
                key, value = part.split('=', 1)
                kwargs[key] = value
            else:
                args.append(part)
        
        if '.' in command:
            service_name, method_name = command.split('.', 1)
        else:
            self.log_message('命令格式错误，应为 service.method')
            return
        
        self.send_command_to_all_channels(service_name, method_name, command_with_params, *args, **kwargs)
        self.add_to_history(command_with_params)
    
    def send_command_to_all_channels(self, service_name, method_name, command_with_params, *args, **kwargs):
        """
        向所有已连接通道发送指令
        """
        connected_channels = []
        for row in range(self.ipTable.rowCount()):
            status = self.ipTable.item(row, 3).text()
            if status == '已连接':
                channel_name = self.ipTable.item(row, 0).text()
                
                if row in self.rpc_clients:
                    client = self.rpc_clients[row]
                    try:
                        result = client.send_command(service_name, method_name, *args, **kwargs)
                        if isinstance(result, dict):
                            result_str = json.dumps(result, indent=2, ensure_ascii=False)
                        elif isinstance(result, (list, tuple)):
                            result_str = json.dumps(result, indent=2, ensure_ascii=False)
                        else:
                            result_str = str(result)
                        if self.sequence == True:
                            self.log_message(f'[{channel_name}] recv:{result_str}')
                            connected_channels.append(channel_name)
                        else:
                            self.log_message(f'[{channel_name}] send:{command_with_params} \n recv:{result_str}')
                            connected_channels.append(channel_name)
                    except Exception as e:
                        self.log_message(f'[{channel_name}] 发送命令失败: {command_with_params}，错误: {str(e)}')
                else:
                    self.log_message(f'[{channel_name}] RPC客户端未找到，请重新连接')
        
        if not connected_channels:
            self.log_message('没有已连接的通道')
    
    def log_message(self, message):
        self.logText.insertPlainText(message + '\n')
        self.logText.ensureCursorVisible()
        from utils.logger import init_logger
        logger = init_logger(name="MixToolLogger", log_file="mixTool.log")
        logger.info(message)
    
    def show_config_channel_dialog(self):
        """
        显示配置通道的弹出窗口
        """
        dialog = QDialog(self)
        dialog.setWindowTitle('配置通道')
        dialog.setGeometry(200, 200, 450, 250)
        
        layout = QGridLayout()
        
        layout.addWidget(QLabel('通道数量:'), 0, 0)
        count_spin = QSpinBox()
        count_spin.setRange(1, 24)
        count_spin.setValue(self.ipTable.rowCount())
        layout.addWidget(count_spin, 0, 1)
        
        layout.addWidget(QLabel('起始IP:'), 1, 0)
        ip_input = QLineEdit('192.168.99.33')
        layout.addWidget(ip_input, 1, 1)
        
        layout.addWidget(QLabel('起始端口:'), 2, 0)
        port_input = QLineEdit('7801')
        layout.addWidget(port_input, 2, 1)
        
        layout.addWidget(QLabel('端口递增步长:'), 3, 0)
        port_step = QLineEdit('0')
        port_step.setPlaceholderText('0表示不递增')
        layout.addWidget(port_step, 3, 1)
        
        button_layout = QHBoxLayout()
        ok_btn = QPushButton('确定')
        cancel_btn = QPushButton('取消')
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout, 4, 0, 1, 2)
        
        dialog.setLayout(layout)
        
        def get_ip(slot, startNum=33, setp=1,start_num_head="111.111.111."):
            sw1 = str(slot)[-1]
            sw2 = ('00' + str(slot))[-2]
            add_num = int(sw2) * 16 + int(sw1)
            add_num = add_num - 1
            add_num = int(add_num / int(setp))
            ip_address = int(startNum) + add_num
            ip_address = str(start_num_head) + str(ip_address)
            return ip_address
        
        def on_ok():
            count = count_spin.value()
            start_ip = ip_input.text()
            start_port = int(port_input.text())
            port_step_value = int(port_step.text()) if port_step.text() else 0
            
            start_ip_list = start_ip.split('.')
            start_num = int(start_ip_list[-1])
            start_num_head = ".".join(str(num) for num in start_ip_list[:3])
            while self.ipTable.rowCount() > 0:
                self.ipTable.removeRow(0)
            
            for i in range(count):
                slot_number = i + 1
                self.ipTable.insertRow(i)
                
                ip_address = get_ip(slot_number, start_num, 1, start_num_head+".")
                
                if port_step_value == 0:
                    port = start_port
                else:
                    port = start_port + (slot_number - 1) * port_step_value
                
                self.ipTable.setItem(i, 0, QTableWidgetItem(f'Slot{slot_number}'))
                self.ipTable.setItem(i, 1, QTableWidgetItem(ip_address))
                self.ipTable.setItem(i, 2, QTableWidgetItem(str(port)))
                self.ipTable.setItem(i, 3, QTableWidgetItem('未连接'))
                
                connect_btn = QPushButton('连接')
                connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
                self.ipTable.setCellWidget(i, 4, connect_btn)
            
            self.log_message(f'配置了 {count} 个通道')
            self.save_channels_to_config()
            dialog.accept()
        
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def save_commands_info(self, commands_info):
        """
        保存命令信息到json文件
        """
        from utils.config import config_manager
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
        from utils.config import config_manager
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
        commands_info = self.load_commands_info()
        
        commands = []
        for service, methods in commands_info.items():
            if isinstance(methods, dict):
                for method in methods:
                    commands.append(f"{service}.{method}")
        
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
            
            client = RpcClient(ip, port, log_callback=self.log_message)
            
            if client.connect():
                self.log_message(f'通道 {channel_name} 连接成功！')
                self.rpc_clients[row] = client
                self.ipTable.setItem(row, 3, QTableWidgetItem('已连接'))
                connect_btn.setText('断开')
                
                commands_info = client.get_all_commands()
                if commands_info:
                    self.save_commands_info(commands_info)
                    self.update_command_hints()
            else:
                self.log_message(f'通道 {channel_name} 连接失败！')
        else:
            self.log_message(f'正在断开通道: {channel_name}')
            
            if row in self.rpc_clients:
                del self.rpc_clients[row]
            self.log_message(f'通道 {channel_name} 断开成功！')
            
            self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
            connect_btn.setText('连接')
    
    def batch_connect(self):
        """
        批量连接选中的通道
        """
        selected_rows = set()
        for item in self.ipTable.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要连接的通道')
            return
        
        for row in selected_rows:
            connect_btn = self.ipTable.cellWidget(row, 4)
            if connect_btn.text() == '连接':
                self.connect_channel(row)
    
    def batch_disconnect(self):
        """
        批量断开选中的通道
        """
        selected_rows = set()
        for item in self.ipTable.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.log_message('请先选择要断开的通道')
            return
        
        for row in selected_rows:
            connect_btn = self.ipTable.cellWidget(row, 4)
            if connect_btn.text() == '断开':
                self.connect_channel(row)
    
    def load_channels_from_config(self):
        """
        从配置文件加载通道配置
        """
        from utils.config import config_manager
        
        self.ipTable.cellChanged.disconnect(self.on_cell_changed)
        
        while self.ipTable.rowCount() > 0:
            self.ipTable.removeRow(0)
        
        channels = config_manager.get_channels()
        for i, channel in enumerate(channels):
            self.ipTable.insertRow(i)
            self.ipTable.setItem(i, 0, QTableWidgetItem(channel['name']))
            self.ipTable.setItem(i, 1, QTableWidgetItem(channel['ip']))
            self.ipTable.setItem(i, 2, QTableWidgetItem(channel['port']))
            self.ipTable.setItem(i, 3, QTableWidgetItem('未连接'))
            
            connect_btn = QPushButton('连接')
            connect_btn.setMinimumWidth(40)
            connect_btn.clicked.connect(lambda _, r=i: self.connect_channel(r))
            self.ipTable.setCellWidget(i, 4, connect_btn)
        
        self.log_message(f'从配置文件加载了 {len(channels)} 个通道')
        
        self.ipTable.cellChanged.connect(self.on_cell_changed)
    
    def save_channels_to_config(self):
        """
        保存通道配置到配置文件
        """
        from utils.config import config_manager
        
        channels = []
        for i in range(self.ipTable.rowCount()):
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
            print(f"配置文件已保存到: {config_manager.config_file}")
        else:
            self.log_message('保存通道配置失败')
    
    def select_command(self, command):
        """
        选择命令
        """
        if hasattr(command, 'text'):
            command = command.text()
        
        self.cmdInput.setText(command)
        self.paramInput.setText(command)
        self.show_command_doc(command)
    
    def show_command_doc(self, command):
        """
        显示命令详细说明
        """
        commands_info = self.load_commands_info()
        
        if '.' in command:
            service_name, method_name = command.split('.', 1)
            
            if service_name in commands_info and method_name in commands_info[service_name]:
                command_info = commands_info[service_name][method_name]
                doc = command_info.get('doc', '无说明')
                params = command_info.get('params', [])
                
                params_list = []
                if isinstance(params, list):
                    for param in params:
                        if isinstance(param, dict) and '__MRPC_EXTENDED_1' in param:
                            param_data = param['__MRPC_EXTENDED_1']
                            param_name = param_data.get('name', '未命名')
                            if 'default' in param_data and param_data['default'] is not None:
                                params_list.append(f"{param_name} (默认: {param_data['default']})")
                            else:
                                params_list.append(param_name)
                        elif isinstance(param, str):
                            params_list.append(param)
                
                params_str = ', '.join(params_list) if params_list else '无参数'
                
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
        from utils.config import config_manager
        history = config_manager.get_history()
        for command in history:
            self.historyList.addItem(command)
    
    def add_to_history(self, command):
        """
        将命令添加到历史记录
        """
        from utils.config import config_manager
        
        for i in range(self.historyList.count()):
            if self.historyList.item(i).text() == command:
                self.historyList.takeItem(i)
                break
        
        self.historyList.insertItem(0, command)
        
        if self.historyList.count() > 50:
            self.historyList.takeItem(self.historyList.count() - 1)
        
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
        self.send_command()
    
    def show_history_context_menu(self, position):
        """
        显示历史命令的右键菜单
        """
        menu = QMenu()
        
        clear_all_action = menu.addAction("清空所有内容")
        
        item = self.historyList.itemAt(position)
        if item:
            menu.addSeparator()
            add_to_sequence_action = menu.addAction("添加到序列")
            delete_action = menu.addAction("删除")
        
        action = menu.exec(self.historyList.mapToGlobal(position))
        
        if action == clear_all_action:
            self.clear_history()
        elif item and action == delete_action:
            row = self.historyList.row(item)
            self.historyList.takeItem(row)
            from utils.config import config_manager
            history = []
            for i in range(self.historyList.count()):
                history.append(self.historyList.item(i).text())
            config_manager.save_history(history)
        elif item and action == add_to_sequence_action:
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
            self.clear_log()
    
    def clear_history(self):
        """
        清空所有历史指令
        """
        from utils.config import config_manager
        self.historyList.clear()
        config_manager.save_history([])
        self.log_message("已清空所有历史指令")
    
    def clear_log(self):
        """
        清空所有日志
        """
        self.logText.clear()
    
    def open_sequence_file(self):
        """
        打开序列组原始文件
        """
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        
        if self.last_sequence_file:
            try:
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
        
        add_delay_action = menu.addAction("添加延迟")
        add_pause_action = menu.addAction("添加暂停")
        menu.addSeparator()
        clear_sequence_action = menu.addAction("清空序列")
        save_sequence_action = menu.addAction("保存序列组")
        load_sequence_action = menu.addAction("加载序列组")
        open_sequence_file_action = menu.addAction("打开序列组原始文件")
        
        item = self.sequenceList.itemAt(position)
        if item:
            menu.addSeparator()
            modify_action = menu.addAction("修改")
            delete_action = menu.addAction("删除")
        
        action = menu.exec(self.sequenceList.mapToGlobal(position))
        
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
            self.modify_sequence_item(item)
        elif item and action == delete_action:
            row = self.sequenceList.row(item)
            self.sequenceList.takeItem(row)
            self.log_message("已从序列中删除指令")
    
    def show_channel_context_menu(self, pos):
        """
        显示通道列表右键菜单
        """
        menu = QMenu()
        
        add_row_action = menu.addAction("新增一行")
        add_row_action.triggered.connect(self.add_channel_row)
        
        config_action = menu.addAction("配置通道")
        config_action.triggered.connect(self.show_config_channel_dialog)
        
        connect_action = menu.addAction("批量连接")
        connect_action.triggered.connect(self.batch_connect)
        
        disconnect_action = menu.addAction("批量断开")
        disconnect_action.triggered.connect(self.batch_disconnect)
        
        menu.exec(self.ipTable.mapToGlobal(pos))
    
    def on_cell_changed(self, row, column):
        """
        单元格修改完成事件，自动保存到配置文件
        """
        self.save_channels_to_config()
        
        if column == 1 or column == 2:
            self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
    
    def add_channel_row(self):
        """
        新增一行通道配置
        """
        row = self.ipTable.rowCount()
        self.ipTable.insertRow(row)
        
        self.ipTable.setItem(row, 0, QTableWidgetItem(f'Slot{row+1}'))
        self.ipTable.setItem(row, 1, QTableWidgetItem(''))
        self.ipTable.setItem(row, 2, QTableWidgetItem('7801'))
        self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
        
        connect_btn = QPushButton('连接')
        connect_btn.setMinimumWidth(40)
        connect_btn.clicked.connect(lambda _, r=row: self.connect_channel(r))
        self.ipTable.setCellWidget(row, 4, connect_btn)
        
        self.save_channels_to_config()
        
        self.log_message(f'已新增通道: Slot{row+1}')
    
    def modify_sequence_item(self, item):
        """
        修改序列项
        """
        text = item.text()
        row = self.sequenceList.row(item)
        
        if text.startswith('[CMD]'):
            current_command = text[5:].strip()
            from PyQt6.QtWidgets import QInputDialog
            new_command, ok = QInputDialog.getText(self, '修改指令', '请输入新的指令和参数:', text=current_command)
            if ok:
                item.setText(f"[CMD] {new_command}")
                self.log_message(f"已修改序列中的指令: {new_command}")
        elif text.startswith('[DELAY]'):
            current_delay = text[7:].replace('ms', '').strip()
            from PyQt6.QtWidgets import QInputDialog
            new_delay, ok = QInputDialog.getInt(self, '修改延迟', '请输入新的延迟时间（毫秒）:', int(current_delay), 1, 30000)
            if ok:
                item.setText(f"[DELAY] {new_delay}ms")
                self.log_message(f"已修改序列中的延迟: {new_delay}ms")
        elif text.startswith('[PAUSE]'):
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
        from PyQt6.QtWidgets import QInputDialog
        delay, ok = QInputDialog.getInt(self, '添加延迟', '请输入延迟时间（毫秒）:', 1000, 1, 30000)
        if ok:
            item = QListWidgetItem(f"[DELAY] {delay}ms")
            item.setCheckState(Qt.CheckState.Checked)
            self.sequenceList.addItem(item)
            self.log_message(f"已添加延迟到序列: {delay}ms")
    
    def add_pause_to_sequence(self):
        """
        添加暂停到序列列表
        """
        from PyQt6.QtWidgets import QInputDialog
        message, ok = QInputDialog.getText(self, '添加暂停', '请输入暂停提示信息:', text='执行到此处，是否继续？')
        if ok:
            item = QListWidgetItem(f"[PAUSE] {message}")
            item.setCheckState(Qt.CheckState.Checked)
            self.sequenceList.addItem(item)
            self.log_message(f"已添加暂停到序列: {message}")
    
    def execute_sequence(self):
        """
        执行指令序列
        """
        if not self.rpc_clients:
            self.log_message('没有已连接的通道，请先连接通道')
            return
        
        if self.sequenceList.count() == 0:
            self.log_message('序列为空，请先添加指令或延迟')
            return
        
        self.log_message('开始执行指令序列...')
        
        for i in range(self.sequenceList.count()):
            item = self.sequenceList.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            
            text = item.text()
            
            if text.startswith('[CMD]'):
                command = text[5:].strip()
                self.log_message(f'[序列] 执行指令: {command}')
                
                parts = command.split(' ')
                if len(parts) < 1:
                    self.log_message('[序列] 命令格式错误')
                    continue
                
                cmd = parts[0]
                args = []
                kwargs = {}
                
                for part in parts[1:]:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        kwargs[key] = value
                    else:
                        if part != "" and part != " " :
                            args.append(part)
                
                if '.' in cmd:
                    service_name, method_name = cmd.split('.', 1)
                else:
                    self.log_message('[序列] 命令格式错误，应为 service.method')
                    continue
                self.sequence = True
                self.send_command_to_all_channels(service_name, method_name, command, *args, **kwargs)
                self.sequence = False
            elif text.startswith('[DELAY]'):
                delay_str = text[7:].replace('ms', '').strip()
                try:
                    delay = int(delay_str)
                    self.log_message(f'[序列] 执行延迟: {delay}ms')
                    from PyQt6.QtCore import QTimer, QEventLoop
                    timer = QTimer(self)
                    timer.setSingleShot(True)
                    timer.start(delay)
                    loop = QEventLoop()
                    timer.timeout.connect(loop.quit)
                    loop.exec()
                except ValueError:
                    self.log_message(f'[序列] 延迟时间格式错误: {delay_str}')
            elif text.startswith('[PAUSE]'):
                pause_message = text[7:].strip()
                self.log_message(f'[序列] 执行暂停: {pause_message}')
                
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(self, '序列暂停', 
                                           pause_message, 
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                           QMessageBox.StandardButton.No)
                
                if reply == QMessageBox.StandardButton.No:
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
        from utils.config import config_manager
        
        if self.sequenceList.count() == 0:
            self.log_message('序列为空，无法保存')
            return
        
        config_dir = config_manager.get_config_dir()
        
        from PyQt6.QtWidgets import QInputDialog
        filename, ok = QInputDialog.getText(self, '保存序列组', '请输入文件名（不含扩展名）:', text='sequence_group')
        if not ok or not filename:
            return
        
        if not filename.endswith('.csv'):
            filename += '.csv'
        
        filepath = os.path.join(config_dir, filename)
        
        try:
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
        from utils.config import config_manager
        
        config_dir = config_manager.get_config_dir()
        
        csv_files = glob.glob(os.path.join(config_dir, '*.csv'))
        
        if not csv_files:
            self.log_message('没有找到保存的序列组')
            return
        
        file_names = [os.path.splitext(os.path.basename(f))[0] for f in csv_files]
        
        from PyQt6.QtWidgets import QInputDialog
        group_name, ok = QInputDialog.getItem(self, '加载序列组', '选择要加载的序列组:', file_names, 0, False)
        if not ok or not group_name:
            return
        
        filepath = os.path.join(config_dir, group_name + '.csv')
        self.last_sequence_file = filepath
        
        try:
            self.sequenceList.clear()
            
            with open(filepath, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)
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
                        
                        if checked == '1':
                            item.setCheckState(Qt.CheckState.Checked)
                        else:
                            item.setCheckState(Qt.CheckState.Unchecked)
                        
                        self.sequenceList.addItem(item)
            
            self.sequenceGroup.setTitle(f'当前指令序列 - {group_name} - 右键点击管理序列')
            self.log_message(f'已加载序列组: {group_name}')
        except Exception as e:
            self.log_message(f'加载序列组失败: {str(e)}')