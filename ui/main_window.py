import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QTextEdit, 
                            QTableWidget, QTableWidgetItem, QGroupBox, 
                            QDialog, QSpinBox, QGridLayout, QScrollArea, QComboBox,
                            QCompleter, QListWidget, QListWidgetItem)
from PyQt6.QtCore import Qt, QStringListModel
from utils.config import config_manager

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MIX Test Control')
        self.setGeometry(100, 100, 800, 600)
        self.init_ui()
        self.load_channels_from_config()
        self.load_history_from_config()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局改为水平布局，分为左侧和右侧
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 左侧布局
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        
        # 日志显示区域（左侧上方）
        log_group = QGroupBox('日志显示')
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(10, 10, 10, 10)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(300)
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
        self.command_hint_list.setMinimumHeight(100)
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
        self.cmd_info_text.setMinimumHeight(100)
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
        
        # 右侧布局
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)
        
        # 历史指令区域（右侧上方）
        history_group = QGroupBox('历史指令')
        history_layout = QVBoxLayout()
        history_layout.setContentsMargins(10, 10, 10, 10)
        
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(200)
        self.history_list.itemClicked.connect(self.select_history_command)
        history_layout.addWidget(self.history_list)
        
        history_group.setLayout(history_layout)
        right_layout.addWidget(history_group)
        
        # 通道IP显示区域（右侧下方）
        ip_group = QGroupBox('通道IP配置')
        ip_layout = QVBoxLayout()
        ip_layout.setContentsMargins(10, 10, 10, 10)
        ip_layout.setSpacing(10)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # 配置通道按钮
        config_channel_btn = QPushButton('配置通道')
        config_channel_btn.setMinimumHeight(30)
        button_layout.addWidget(config_channel_btn)
        config_channel_btn.clicked.connect(self.show_config_channel_dialog)
        
        # 批量连接按钮
        batch_connect_btn = QPushButton('批量连接')
        batch_connect_btn.setMinimumHeight(30)
        button_layout.addWidget(batch_connect_btn)
        batch_connect_btn.clicked.connect(self.batch_connect)
        
        # 批量断开按钮
        batch_disconnect_btn = QPushButton('批量断开')
        batch_disconnect_btn.setMinimumHeight(30)
        button_layout.addWidget(batch_disconnect_btn)
        batch_disconnect_btn.clicked.connect(self.batch_disconnect)
        
        ip_layout.addLayout(button_layout)
        
        # 通道列表滚动区域
        scroll_area = QScrollArea()
        scroll_area.setMinimumHeight(300)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # 通道列表
        self.ip_table = QTableWidget(1, 5)
        self.ip_table.setHorizontalHeaderLabels(['通道', 'IP地址', '端口', '状态', '操作'])
        self.ip_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ip_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        
        # 设置列宽
        self.ip_table.setColumnWidth(0, 50)
        self.ip_table.setColumnWidth(1, 100)
        self.ip_table.setColumnWidth(2, 50)
        self.ip_table.setColumnWidth(3, 60)
        self.ip_table.setColumnWidth(4, 80)
        
        # 初始化默认通道
        self.ip_table.setItem(0, 0, QTableWidgetItem('Slot1'))
        self.ip_table.setItem(0, 1, QTableWidgetItem('192.168.99.36'))
        self.ip_table.setItem(0, 2, QTableWidgetItem('7801'))
        self.ip_table.setItem(0, 3, QTableWidgetItem('未连接'))
        
        # 添加连接按钮
        connect_btn = QPushButton('连接')
        connect_btn.setMinimumWidth(80)
        connect_btn.clicked.connect(lambda: self.connect_channel(0))
        self.ip_table.setCellWidget(0, 4, connect_btn)
        
        scroll_layout.addWidget(self.ip_table)
        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        ip_layout.addWidget(scroll_area)
        
        ip_group.setLayout(ip_layout)
        right_layout.addWidget(ip_group)
        
        # 将左右布局添加到主布局
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)
    
    def send_command(self):
        """
        发送指令到所有已连接通道
        """
        command_with_params = self.param_input.text()
        
        if not command_with_params:
            self.log_message('请输入命令和参数')
            return
        
        # 遍历所有通道，发送指令到已连接的通道
        connected_channels = []
        for row in range(self.ip_table.rowCount()):
            status = self.ip_table.item(row, 3).text()
            if status == '已连接':
                channel_name = self.ip_table.item(row, 0).text()
                connected_channels.append(channel_name)
                self.log_message(f'向通道 {channel_name} 发送命令: {command_with_params}')
        
        if connected_channels:
            self.log_message(f'已向 {len(connected_channels)} 个已连接通道发送命令')
        else:
            self.log_message('没有已连接的通道')
        
        # 将命令添加到历史记录
        self.add_to_history(command_with_params)
    
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
            
            # 模拟连接成功
            self.log_message(f'通道 {channel_name} 连接成功！')
            
            # 更新状态和按钮
            self.ip_table.setItem(row, 3, QTableWidgetItem('已连接'))
            connect_btn.setText('断开')
        else:
            self.log_message(f'正在断开通道: {channel_name}')
            
            # 模拟断开成功
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
        
        # 模拟命令列表
        commands = [
            'relay.reset',
            'lucifer.led_control',
            'eeprom.read_string_eeprom',
            'eeprom.write_string_eeprom',
            'sib_board.reset_gpio',
            'sib_board.get_gpio',
            'sib_board.lock_xadc_measure',
            'sib_board.read_string_eeprom'
        ]
        
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
        # 模拟命令文档
        command_docs = {
            'relay.reset': {
                'doc': '重置继电器',
                'params': '无参数'
            },
            'lucifer.led_control': {
                'doc': '控制LED灯',
                'params': 'device: str, color: str'
            },
            'eeprom.read_string_eeprom': {
                'doc': '读取EEPROM字符串',
                'params': 'address: int, length: int'
            },
            'eeprom.write_string_eeprom': {
                'doc': '写入EEPROM字符串',
                'params': 'address: int, data: str'
            },
            'sib_board.reset_gpio': {
                'doc': '重置GPIO',
                'params': '无参数'
            },
            'sib_board.get_gpio': {
                'doc': '获取GPIO值',
                'params': 'gpio_name: str'
            },
            'sib_board.lock_xadc_measure': {
                'doc': '锁定XADC测量',
                'params': 'channel: int, sample: int, count: int'
            },
            'sib_board.read_string_eeprom': {
                'doc': '读取EEPROM字符串',
                'params': 'address: int, length: int'
            }
        }
        
        if command in command_docs:
            doc = command_docs[command]['doc']
            params = command_docs[command]['params']
            
            # 在主界面的命令信息区域显示
            info_text = f"命令: {command}\n\n说明: {doc}\n\n参数: {params}"
            self.cmd_info_text.setPlainText(info_text)
        else:
            self.cmd_info_text.setPlainText('命令信息未找到')
    
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