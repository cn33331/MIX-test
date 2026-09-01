import sys
import threading
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                            QLabel, QLineEdit, QPushButton, QTextEdit, 
                            QTableWidget, QTableWidgetItem, QGroupBox, 
                            QDialog, QSpinBox, QGridLayout, QScrollArea, QComboBox,
                            QCompleter, QListWidget, QListWidgetItem, QMenu, QSplitter, QHeaderView, QSizePolicy,
                            QTreeWidget, QTreeWidgetItem, QInputDialog)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.uic import loadUi
import json
import os
import csv
import glob
import ast
import re

# 添加插件目录到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLUGIN_DIR)

# 导入本地的rpc_client
from rpc_client import RpcClient

# 通用 JSON 配置基类（复用其他插件的配置持久化框架）
from utils.json_config import BaseJsonConfig

# 添加mix目录到路径
mix_dir = os.path.join(PLUGIN_DIR, 'mix')
if mix_dir not in sys.path:
    sys.path.insert(0, mix_dir)

def get_resource_path(relative_path):
    """获取资源文件的绝对路径。

    用于在插件目录中查找资源文件，确保打包后仍能正确定位资源。

    Args:
        relative_path: 相对路径字符串，相对于插件目录

    Returns:
        资源文件的绝对路径字符串

    Warning:
        此函数假设插件目录在外部，不从MEIPASS加载
    """
    return os.path.join(PLUGIN_DIR, relative_path)

def _parse_arg(raw):
    """将 UI 输入的参数字符串解析为对应的 Python 值。

    使用 ast.literal_eval 尝试把用户输入的文本转换为真实的 Python 字面量
    （list / tuple / int / float / bool / dict / None / str 等），从而支持
    类似 ``[[2017,0],[2018,0]]`` 的列表参数原样以列表类型下发。
    若文本不是合法的 Python 字面量（如设备要求的 ``2017*0,2018*0`` 格式），
    则保持原字符串不变，交由设备端自行解析。

    Args:
        raw: 用户输入的单个参数文本。

    Returns:
        Any: 解析后的 Python 值（列表、数字等），无法解析时返回原字符串。
    """
    if raw is None:
        return None
    text = str(raw)
    stripped = text.strip()
    if not stripped:
        return text
    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        # 非合法字面量（如 "2017*0,2018*0"），保持原字符串
        return text

def _split_command_args(line):
    """按空格切分命令与参数，同时尊重方括号/圆括号/花括号/引号等成对结构。

    直接 ``split(' ')`` 会把含空格的 Python 字面量（如 ``[[1001, 0], [1002, 1]]``）
    拆成多个独立 token，导致一个列表参数被当作多个位置参数下发。
    本函数逐个字符扫描，遇到 ``[](){}`` 与引号时进入对应层级，在括号/引号内部
    的空格不会被切分，从而把整个字面量保持为单个 token。

    Args:
        line: 完整的命令+参数字符串。

    Returns:
        list: 切分后的 token 列表，第一个为命令，其余为参数。

    Examples:
        >>> _split_command_args('io_ctrl.set 1001*0,1002*1,1003*0')
        ['io_ctrl.set', '1001*0,1002*1,1003*0']
        >>> _split_command_args('io_ctrl.set [[1001, 0], [1002, 1]]')
        ['io_ctrl.set', '[[1001, 0], [1002, 1]]']
    """
    tokens = []
    current = []
    # 成对符号的深度统计；键值对/嵌套均统一处理
    stack = []  # 保存当前进入的开符号，用于匹配与判断是否在成对结构内部
    pairs = {'(': ')', '[': ']', '{': '}'}
    closers = {')', ']', '}'}

    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == ' ' and not stack:
            if current:
                tokens.append(''.join(current))
                current = []
            i += 1
            continue
        if ch in pairs:          # 进入成对结构
            stack.append(pairs[ch])
            current.append(ch)
            i += 1
            continue
        if ch in closers and stack and ch == stack[-1]:
            stack.pop()
            current.append(ch)
            i += 1
            continue
        if ch in ('"', "'"):
            # 字符串字面量：跳转到关闭引号（不处理转义，够用于参数场景）
            current.append(ch)
            quote = ch
            i += 1
            while i < n and line[i] != quote:
                current.append(line[i])
                i += 1
            if i < n:
                current.append(line[i])  # 关闭引号
                i += 1
            continue
        current.append(ch)
        i += 1

    if current:
        tokens.append(''.join(current))
    # 过滤掉空 token
    return [t for t in tokens if t != '']

class CommandsInfoConfig(BaseJsonConfig):
    """命令信息配置管理器 - 复用通用 JSON 配置基类。

    管理设备端枚举的命令信息 {service: {method: info}}，存放于宿主
    config_manager 配置目录下的 commands_info.json。该数据由设备动态
    返回、结构不固定，故不配置模板文件与兜底默认值，文件缺失时
    自动初始化为空字典。

    Attributes:
        config: 命令信息字典，get() 可直接按点号键访问。
        config_file: commands_info.json 的绝对路径。
    """

    def __init__(self) -> None:
        """初始化命令信息配置管理器。

        Warning:
            配置目录取自宿主 config_manager（~/.MIX-Tool），
            实例化时同步读取文件，属磁盘 I/O 操作。
        """
        from utils.config import config_manager
        config_file = os.path.join(config_manager.get_config_dir(), 'commands_info.json')
        super().__init__(config_file=config_file)

class MIXDebugPlugin(QMainWindow):
    """MIX调试插件主窗口类。

    提供多通道RPC通信、命令管理、序列执行等功能的工业级调试工具。
    支持MIX_2.0协议，提供命令自动补全、历史记录、日志显示等特性。
    """

    def __init__(self):
        """初始化MIX调试插件主窗口。

        加载UI文件、初始化信号连接、加载配置和历史记录。
        """
        super().__init__()
        self.log_mutex = threading.Lock()
        self.version = 'v4'
        ui_path = get_resource_path('MIX_debug_plugin.ui')
        loadUi(ui_path, self)
        self.setWindowTitle(f'MIX-debug {self.version} by:zjx')
        self.rpc_clients = {}
        self.last_sequence_file = None
        self.channel_logs = {}
        self._cascading_sequence = False  # 组勾选级联子指令时置位，抑制重复自动保存
        self.init_signals()
        self.load_channels_from_config()
        self.load_history_from_config()
        self.resizeEvent = self.on_resize
        self.sequence = False
        self.logTabWidget.setTabText(0, '总日志')
        self.autoload_sequence_groups()
    
    def get_widget(self):
        """返回插件的主窗口部件。

        Returns:
            QMainWindow: 插件的主窗口实例
        """
        return self
    
    def get_name(self):
        """返回插件名称。

        Returns:
            str: 插件名称，包含版本号
        """
        return f'MIX_debug {self.version}'
    
    def init_signals(self):
        """初始化所有信号与槽的连接。

        配置命令输入、按钮点击、列表选择、右键菜单等事件的处理函数。
        同时设置表格列的自动调整模式和命令自动补全功能。
        """
        self.cmdInput.returnPressed.connect(self.copy_command_to_param)
        self.sendCmdButton.clicked.connect(self.send_command)
        self.historyList.itemDoubleClicked.connect(self.select_history_command)
        self.historyList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.historyList.customContextMenuRequested.connect(self.show_history_context_menu)
        self.sequenceList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sequenceList.customContextMenuRequested.connect(self.show_sequence_context_menu)
        self.sequenceList.itemChanged.connect(self.on_sequence_item_changed)
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
        """窗口大小变化时调整左右面板的尺寸比例。

        确保右侧面板保持450px宽度，左侧面板占据剩余空间。

        Args:
            event: QResizeEvent事件对象，包含新的窗口尺寸信息
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
        """发送指令到所有已连接通道。

        解析用户输入的命令和参数，支持位置参数和关键字参数两种格式。
        命令格式为: service.method arg1 arg2 key=value

        Raises:
            ValueError: 命令格式错误时记录日志但不抛出异常
        """
        command_with_params = self.paramInput.text()
        
        if not command_with_params:
            self.log_message('请输入命令和参数')
            return
        
        parts = _split_command_args(command_with_params)
        if len(parts) < 1:
            self.log_message('命令格式错误')
            return
        
        command = parts[0]
        args = []
        kwargs = {}
        
        for part in parts[1:]:
            if '=' in part:
                key, value = part.split('=', 1)
                kwargs[key] = _parse_arg(value)
            else:
                args.append(_parse_arg(part))
        
        if '.' in command:
            service_name, method_name = command.split('.', 1)
        else:
            self.log_message('命令格式错误，应为 service.method')
            return
        
        try:
            rpc_timeout = int(self.timeoutInput.text().strip())
        except (ValueError, AttributeError):
            rpc_timeout = 30
        
        self.send_command_to_all_channels(service_name, method_name, command_with_params, rpc_timeout, *args, **kwargs)
        self.add_to_history(command_with_params)
    
    def _send_command_to_channel(self, row, service_name, method_name, command_with_params, rpc_timeout, args, kwargs, connected_channels):
        """向单个通道发送RPC命令（线程函数）。

        Args:
            row: 通道行号
            service_name: 服务名称字符串
            method_name: 方法名称字符串
            command_with_params: 完整的命令字符串（含参数）
            rpc_timeout: 超时时间（秒）
            args: 位置参数元组
            kwargs: 关键字参数字典
            connected_channels: 已连接通道名称列表（线程安全）

        Returns:
            None: 无返回值，结果通过日志显示
        """
        status = self.ipTable.item(row, 3).text()
        if status != '已连接':
            return
        
        channel_name = self.ipTable.item(row, 0).text()
        
        if row in self.rpc_clients:
            client = self.rpc_clients[row]
            try:
                result = client.send_command(service_name, method_name, *args, rpc_timeout=rpc_timeout, **kwargs)
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
    
    def send_command_to_all_channels(self, service_name, method_name, command_with_params, rpc_timeout, *args, **kwargs):
        """向所有已连接的通道发送RPC命令（多线程）。

        遍历所有通道，使用多线程并行向状态为'已连接'的通道发送命令，
        所有通道同时发送，提高整体响应速度。使用互斥锁保证日志输出不会错行。

        Args:
            service_name: 服务名称字符串
            method_name: 方法名称字符串
            command_with_params: 完整的命令字符串（含参数）
            rpc_timeout: 超时时间（秒）
            *args: 位置参数列表
            **kwargs: 关键字参数字典

        Returns:
            None: 无返回值，结果通过日志显示

        Warning:
            序列执行模式下(self.sequence=True)只记录响应，不记录发送内容
            使用多线程并行发送，日志顺序可能与通道顺序不一致，但不会错行
        """
        connected_channels = []
        threads = []
        
        for row in range(self.ipTable.rowCount()):
            status = self.ipTable.item(row, 3).text()
            if status == '已连接':
                thread = threading.Thread(
                    target=self._send_command_to_channel,
                    args=(row, service_name, method_name, command_with_params, rpc_timeout, args, kwargs, connected_channels),
                    daemon=True
                )
                threads.append(thread)
                thread.start()
        
        for thread in threads:
            thread.join()
        
        if not connected_channels:
            self.log_message('没有已连接的通道')
    
    def log_message(self, message):
        """记录日志消息到界面和文件。

        在日志文本框中显示消息，并同时写入日志文件。
        使用互斥锁保证多线程环境下日志输出的原子性，避免错行。

        Args:
            message: 日志消息字符串

        Example:
            >>> self.log_message('通道连接成功')

        Warning:
            此方法线程安全，使用互斥锁保护日志输出
        """
        with self.log_mutex:
            self.logText.insertPlainText(message + '\n')
            self.logText.ensureCursorVisible()
            from utils.logger import init_logger
            logger = init_logger(name="MixToolLogger", log_file="mixTool.log")
            logger.info(message)
            
            for channel_name, log_widget in self.channel_logs.items():
                if f'[{channel_name}]' in message:
                    log_widget.insertPlainText(message + '\n')
                    log_widget.ensureCursorVisible()
    
    def update_channel_log_tabs(self):
        """更新通道日志标签页。

        根据IP通道表格中的通道数量，动态创建/删除日志标签页。
        第一个标签页始终是'总日志'，其他标签页与通道一一对应。
        """
        current_channels = {}
        for row in range(self.ipTable.rowCount()):
            channel_name = self.ipTable.item(row, 0).text()
            current_channels[channel_name] = row
        
        tabs_to_remove = []
        for i in range(1, self.logTabWidget.count()):
            tab_name = self.logTabWidget.tabText(i)
            if tab_name not in current_channels:
                tabs_to_remove.append(i)
        
        for i in reversed(tabs_to_remove):
            widget = self.logTabWidget.widget(i)
            self.logTabWidget.removeTab(i)
            widget.deleteLater()
        
        for channel_name in current_channels:
            if channel_name not in self.channel_logs:
                log_widget = QTextEdit()
                log_widget.setReadOnly(True)
                log_widget.setStyleSheet(
                    'QTextEdit { font-family: "SF Mono", Monaco, Menlo, monospace; '
                    'font-size: 12px; background: #1e1e1e; color: #d4d4d4; border: none; }'
                )
                # 每个通道日志支持右键清空自身
                log_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                log_widget.customContextMenuRequested.connect(self.show_log_context_menu)
                self.logTabWidget.addTab(log_widget, channel_name)
                self.channel_logs[channel_name] = log_widget
        
        for i in range(1, self.logTabWidget.count()):
            tab_name = self.logTabWidget.tabText(i)
            if tab_name in self.channel_logs:
                widget = self.logTabWidget.widget(i)
                if widget != self.channel_logs[tab_name]:
                    old_widget = self.logTabWidget.widget(i)
                    self.logTabWidget.removeTab(i)
                    old_widget.deleteLater()
                    self.logTabWidget.insertTab(i, self.channel_logs[tab_name], tab_name)
    
    def show_config_channel_dialog(self):
        """显示通道配置对话框。

        提供批量配置通道数量、起始IP、起始端口和端口递增步长的功能。
        支持IP地址按Slot编号自动计算。
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
        
        def get_ip(slot, startNum=33, setp=1, start_num_head="111.111.111."):
            """计算Slot对应的IP地址。

            根据Slot编号和起始IP计算实际IP地址，支持端口递增。

            Args:
                slot: Slot编号
                startNum: 起始IP最后一段数字，默认33
                setp: 步长，默认1
                start_num_head: IP地址前三段，默认"111.111.111."

            Returns:
                str: 完整的IP地址字符串
            """
            sw1 = str(slot)[-1]
            sw2 = ('00' + str(slot))[-2]
            add_num = int(sw2) * 16 + int(sw1)
            add_num = add_num - 1
            add_num = int(add_num / int(setp))
            ip_address = int(startNum) + add_num
            ip_address = str(start_num_head) + str(ip_address)
            return ip_address
        
        def on_ok():
            """配置确认处理函数。

            根据用户输入批量创建通道配置，并保存到配置文件。
            """
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
            self.update_channel_log_tabs()
            dialog.accept()
        
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def save_commands_info(self, commands_info):
        """保存命令信息到JSON文件。

        将从设备获取的所有命令信息持久化存储，供命令自动补全使用。
        复用 CommandsInfoConfig（BaseJsonConfig 框架）整体覆盖写入，
        目录不存在时自动创建。

        Args:
            commands_info: 命令信息字典，结构为 {service: {method: info}}

        Returns:
            None: 无返回值，成功或失败通过日志通知
        """
        cfg = CommandsInfoConfig()
        cfg.config = commands_info
        if cfg.save():
            self.log_message(f"命令信息已保存到 {cfg.config_file}")
        else:
            self.log_message("保存命令信息失败")

    def load_commands_info(self):
        """从JSON文件加载命令信息。

        复用 CommandsInfoConfig（BaseJsonConfig 框架），实例化时即完成
        文件读取与默认值合并，无需手动解析。

        Returns:
            dict: 命令信息字典，结构为 {service: {method: info}}，文件不存在时返回空字典
        """
        return CommandsInfoConfig().config
    
    def update_command_hints(self):
        """更新命令自动补全提示列表。

        从配置文件加载命令信息，生成 service.method 格式的命令列表，
        用于命令输入框的自动补全功能。
        """
        commands_info = self.load_commands_info()
        
        commands = []
        for service, methods in commands_info.items():
            if isinstance(methods, dict):
                for method in methods:
                    commands.append(f"{service}.{method}")
        
        self.cmd_model.setStringList(commands)
    
    def connect_channel(self, row):
        """连接或断开指定行的通道。

        根据当前连接状态执行连接或断开操作。连接成功后自动获取命令列表。

        Args:
            row: 通道在表格中的行号，范围为0到行数-1

        Returns:
            None: 无返回值，结果通过日志和界面状态显示

        Example:
            >>> self.connect_channel(0)  # 连接第一行通道
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
        """批量连接选中的通道。

        遍历表格中所有被选中的单元格，提取行号后批量执行连接操作。

        Returns:
            None: 无返回值，未选中通道时通过日志提示
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
        """批量断开选中的通道。

        遍历表格中所有被选中的单元格，提取行号后批量执行断开操作。

        Returns:
            None: 无返回值，未选中通道时通过日志提示
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
        """从配置文件加载通道配置。

        清空现有通道列表，从配置管理器读取保存的通道信息并重建表格。
        加载期间暂时断开单元格修改信号以避免重复保存。
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
        self.update_channel_log_tabs()
    
    def save_channels_to_config(self):
        """保存通道配置到配置文件。

        遍历表格中所有行，收集通道名称、IP地址和端口信息，保存到配置文件。

        Returns:
            None: 无返回值，成功或失败通过日志通知
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
        """选择命令并填充到输入框。

        将选中的命令同时设置到命令输入框和参数输入框，并显示命令详情。

        Args:
            command: 命令字符串或QListWidgetItem对象

        Example:
            >>> self.select_command('system.version')
        """
        if hasattr(command, 'text'):
            command = command.text()
        
        self.cmdInput.setText(command)
        self.paramInput.setText(command)
        self.show_command_doc(command)
    
    def show_command_doc(self, command):
        """显示命令的详细说明文档。

        从命令信息中提取命令说明和参数列表，格式化后显示在信息面板中。

        Args:
            command: 命令字符串，格式为 service.method

        Returns:
            None: 无返回值，结果显示在cmdInfoText控件中
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
        """将命令从cmdInput复制到paramInput。

        当用户在命令输入框中按回车键时触发，方便用户在参数输入框中继续编辑。
        """
        command = self.cmdInput.text()
        if command:
            self.paramInput.setText(command)
    
    def load_history_from_config(self):
        """从配置文件加载历史指令。

        读取保存的历史命令列表，逐个添加到历史记录列表控件中。
        """
        from utils.config import config_manager
        history = config_manager.get_history()
        for command in history:
            self.historyList.addItem(command)
    
    def add_to_history(self, command):
        """将命令添加到历史记录。

        避免重复添加相同命令，保持历史记录最多50条，并保存到配置文件。

        Args:
            command: 要添加的命令字符串

        Warning:
            历史记录最大容量为50条，超出后自动删除最旧的记录
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
        """选择历史命令并立即发送。

        双击历史命令时触发，自动填充到参数输入框并执行发送。

        Args:
            item: QListWidgetItem对象，代表选中的历史命令
        """
        command = item.text()
        self.paramInput.setText(command)
        self.send_command()
    
    def show_history_context_menu(self, position):
        """显示历史命令列表的右键菜单。

        提供清空所有、添加到序列、删除等操作选项。

        Args:
            position: 右键点击的位置（相对于控件）
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
            group = self._ensure_default_group()
            self._add_child_to_group(group, f"[CMD] {command}")
            self.log_message(f"已添加指令到序列: {command}")
            self.sequenceList.setCurrentItem(group)
    
    def show_log_context_menu(self, pos):
        """显示日志区域的右键菜单。

        支持清空当前标签页日志或所有日志。可从总日志或任意通道日志触发。

        Args:
            pos: 右键点击的位置（相对于触发控件）。
        """
        sender = self.sender()
        source = sender if sender is not None else self.logText

        menu = QMenu()
        clear_current_action = menu.addAction("清空当前日志")
        clear_all_action = menu.addAction("清空所有日志")

        action = menu.exec(source.mapToGlobal(pos))

        if action == clear_current_action:
            self.clear_log(source)
        elif action == clear_all_action:
            self.clear_log(None)
    
    def clear_history(self):
        """清空所有历史指令。

        清空界面上的历史记录列表，并同步清空配置文件中的记录。
        """
        from utils.config import config_manager
        self.historyList.clear()
        config_manager.save_history([])
        self.log_message("已清空所有历史指令")
    
    def clear_log(self, target=None):
        """清空日志内容。

        仅清空界面显示，不影响日志文件。

        Args:
            target: 指定要清空的日志控件（QTextEdit）。
                为 None 时清空总日志以及所有通道日志；为具体控件时只清空该控件。
        """
        if isinstance(target, QTextEdit):
            target.clear()
            return
        self.logText.clear()
        for channel_name, log_widget in self.channel_logs.items():
            log_widget.clear()
    
    def open_sequence_file(self):
        """打开序列组原始文件。

        使用系统默认程序打开最近加载的序列组CSV文件。

        Returns:
            None: 无返回值，未加载序列组时通过日志提示
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
        """显示序列树（序列组）的右键菜单。

        根据点击位置决定操作对象：
        - 点击序列组：提供重命名、新建组、启用/停用组、勾选/取消全部、保存/清空该组等。
        - 点击组内指令：提供修改、删除、上下移动等。
        - 空白处：通用操作（新建组、添加延迟/暂停、加载/保存序列组等）。

        Args:
            position: 右键点击的位置（相对于控件）。
        """
        menu = QMenu()

        item = self.sequenceList.itemAt(position)
        # 顶层项视为序列组
        is_group = item is not None and self.sequenceList.indexOfTopLevelItem(item) >= 0

        add_delay_action = menu.addAction("添加延迟")
        add_pause_action = menu.addAction("添加暂停")
        menu.addSeparator()

        new_group_action = menu.addAction("新建序列组")
        save_sequence_action = menu.addAction("保存序列组")
        save_all_action = menu.addAction("保存所有序列组")
        load_sequence_action = menu.addAction("加载序列组")
        menu.addSeparator()
        clear_all_action = menu.addAction("清空所有序列")
        open_sequence_file_action = menu.addAction("打开序列组原始文件")

        # 先统一置为 None，保证后续分发不会引用未定义变量（防止点击组/空白时报错）
        rename_group_action = check_all_action = uncheck_all_action = delete_group_action = \
            modify_action = delete_action = move_up_action = move_down_action = None

        if is_group:
            menu.addSeparator()
            rename_group_action = menu.addAction("重命名序列组")
            check_all_action = menu.addAction("勾选全部")
            uncheck_all_action = menu.addAction("取消勾选全部")
            delete_group_action = menu.addAction("删除序列组")
        elif item is not None:
            menu.addSeparator()
            modify_action = menu.addAction("修改")
            delete_action = menu.addAction("删除")
            move_up_action = menu.addAction("上移")
            move_down_action = menu.addAction("下移")

        action = menu.exec(self.sequenceList.mapToGlobal(position))

        if action is None:
            return

        if action == add_delay_action:
            self.add_delay_to_sequence()
        elif action == add_pause_action:
            self.add_pause_to_sequence()
        elif action == new_group_action:
            self.new_sequence_group()
        elif action == save_sequence_action:
            self.save_sequence_group()
        elif action == save_all_action:
            self.save_all_sequence_groups()
        elif action == load_sequence_action:
            self.load_sequence_group()
        elif action == clear_all_action:
            self.clear_sequence()
        elif action == open_sequence_file_action:
            self.open_sequence_file()
        elif is_group and action == rename_group_action:
            self.rename_sequence_group(item)
        elif is_group and action == check_all_action:
            self.set_group_checked(item, True)
        elif is_group and action == uncheck_all_action:
            self.set_group_checked(item, False)
        elif is_group and action == delete_group_action:
            self.delete_sequence_group(item)
        elif item is not None and action is not None and action == modify_action:
            self.modify_sequence_item(item)
        elif item is not None and action is not None and action == delete_action:
            self.delete_sequence_item(item)
        elif item is not None and action is not None and action == move_up_action:
            self.move_sequence_item(item, up=True)
        elif item is not None and action is not None and action == move_down_action:
            self.move_sequence_item(item, up=False)
    
    def show_channel_context_menu(self, pos):
        """显示通道列表的右键菜单。

        提供新增一行、配置通道、批量连接、批量断开等操作。

        Args:
            pos: 右键点击的位置（相对于控件）
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
        """单元格修改完成事件处理。

        当表格单元格内容修改时自动保存配置，并在IP或端口修改时重置连接状态。

        Args:
            row: 修改的行号
            column: 修改的列号（1=IP地址，2=端口）
        """
        self.save_channels_to_config()
        
        if column == 1 or column == 2:
            self.ipTable.setItem(row, 3, QTableWidgetItem('未连接'))
    
    def add_channel_row(self):
        """新增一行通道配置。

        在表格末尾添加一行新的通道配置，自动生成Slot名称和默认端口。
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
    
    # ------------------------------------------------------------------ #
    # 序列组（QTreeWidget）辅助方法
    # ------------------------------------------------------------------ #

    def _apply_group_style(self, group):
        """给序列组节点应用加粗样式，与普通指令节点区分。

        Args:
            group: 顶层序列组节点。
        """
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        group.setForeground(0, QColor('#6f42c1'))

    def on_sequence_item_changed(self, item, column):
        """序列节点勾选状态变化时的处理。

        顶层序列组节点的勾选框被切换时，级联同步其下所有指令的勾选状态（整组启停），
        并自动保存该组。子指令勾选互不影响。自动保存期间级联置位以抑制重复写入。

        Args:
            item: 发生变化的节点。
            column: 变化所在的列索引。
        """
        if column != 0:
            return
        if item.parent() is not None:
            # 子节点（指令）自身勾选变化：若不在级联过程中则自动保存所属组
            if not self._cascading_sequence:
                self._auto_save_group(item.parent())
            return
        # 顶层节点即序列组：级联其子指令
        self._cascading_sequence = True
        try:
            state = item.checkState(0)
            for ci in range(item.childCount()):
                child = item.child(ci)
                if child.checkState(0) != state:
                    child.setCheckState(0, state)
        finally:
            self._cascading_sequence = False
        self._auto_save_group(item)

    def _resolve_target_group(self, item=None):
        """解析“添加操作”的目标序列组。

        优先级：
        1. 若 action item 指向某个组则用该组；指向组内指令则用其所属组；
        2. 否则用当前选中的顶层组（或当前选中的指令所属组）：
        3. 否则返回第一个顶层组；没有任何组时返回 None。

        Args:
            item: 可选的点击项（组或指令）。

        Returns:
            QTreeWidgetItem: 目标序列组顶层节点，无组时返回 None。
        """
        candidate = None
        if item is not None:
            if self.sequenceList.indexOfTopLevelItem(item) >= 0:
                candidate = item
            elif item.parent() is not None:
                candidate = item.parent()
        if candidate is None:
            current = self.sequenceList.currentItem()
            if current is not None:
                if self.sequenceList.indexOfTopLevelItem(current) >= 0:
                    candidate = current
                elif current.parent() is not None:
                    candidate = current.parent()
        if candidate is None and self.sequenceList.topLevelItemCount() > 0:
            candidate = self.sequenceList.topLevelItem(0)
        return candidate

    def _target_group_or_create(self, item=None):
        """返回“添加操作”的目标组；没有任何组时自动新建一个序列组。

        Args:
            item: 可选的点击项。

        Returns:
            QTreeWidgetItem: 目标序列组顶层节点；新建被取消时返回 None。
        """
        group = self._resolve_target_group(item)
        if group is not None:
            return group
        return self.new_sequence_group()

    def _auto_save_group(self, group):
        """修改序列组后自动保存到磁盘。

        仅在有子指令时保存；空组不落盘，避免产生空文件。级联期间自动跳过。

        Args:
            group: 顶层序列组节点；None 时忽略。
        """
        if group is None:
            return
        if self._cascading_sequence:
            return
        # 无子指令的空组不保存
        if group.childCount() == 0:
            return
        self._save_one_group(group)

    def new_sequence_group(self, name=None):
        """新建一个空的序列组。

        Args:
            name: 组名，为 None 时弹出输入对话框。

        Returns:
            QTreeWidgetItem: 新建的序列组顶层项，取消时为 None。
        """
        from PyQt6.QtWidgets import QInputDialog
        if name is None:
            existing = [self._group_name(i) for i in range(self.sequenceList.topLevelItemCount())]
            name, ok = QInputDialog.getText(self, '新建序列组', '请输入序列组名称:',
                                            text=f'序列组 {self.sequenceList.topLevelItemCount() + 1}')
            if not ok or not name.strip():
                return None
            name = name.strip()
            if name in existing:
                self.log_message(f'序列组名称已存在: {name}')
                return None
        group = QTreeWidgetItem([name])
        group.setFlags(group.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        group.setCheckState(0, Qt.CheckState.Checked)
        group.setExpanded(True)
        self.sequenceList.addTopLevelItem(group)
        self._apply_group_style(group)
        self.log_message(f'已新建序列组: {name}')
        return group

    def _group_name(self, index):
        """取顶层序列组的名称。

        Args:
            index: 顶层节点下标。

        Returns:
            str: 组名。
        """
        return self.sequenceList.topLevelItem(index).text(0)

    def rename_sequence_group(self, group):
        """重命名序列组。

        Args:
            group: 顶层序列组节点。
        """
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, '重命名序列组', '请输入新的序列组名称:', text=group.text(0))
        if ok and name.strip():
            group.setText(0, name.strip())
            self.log_message(f'已重命名序列组为: {name.strip()}')

    def delete_sequence_group(self, group):
        """删除序列组。

        Args:
            group: 顶层序列组节点。
        """
        name = group.text(0)
        self.sequenceList.takeTopLevelItem(self.sequenceList.indexOfTopLevelItem(group))
        self.log_message(f'已删除序列组: {name}')

    def set_group_checked(self, group, checked):
        """勾选或取消勾选序列组下的全部指令。

        Args:
            group: 顶层序列组节点。
            checked: True 全部勾选，False 全部取消。
        """
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        group.setCheckState(0, state)
        self.log_message(f'{("勾选" if checked else "取消勾选")}序列组全部指令: {group.text(0)}')

    def delete_sequence_item(self, item):
        """删除序列组内的某个指令节点。

        Args:
            item: 组内指令节点。
        """
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
            self.log_message('已从序列中删除指令')
        else:
            self.delete_sequence_group(item)

    def move_sequence_item(self, item, up=True):
        """在序列组内上移/下移某个指令。

        Args:
            item: 组内指令节点。
            up: True 上移，False 下移。
        """
        parent = item.parent()
        if parent is None:
            return
        index = parent.indexOfChild(item)
        if up:
            if index <= 0:
                return
            target = index - 1
        else:
            if index >= parent.childCount() - 1:
                return
            target = index + 1
        parent.takeChild(index)
        parent.insertChild(target, item)
        self.sequenceList.setCurrentItem(item)
        self.log_message('已调整指令顺序')

    def modify_sequence_item(self, item):
        """修改序列组内的某个指令。

        根据项的类型（命令、延迟、暂停）显示不同的编辑对话框。

        Args:
            item: 组内指令节点（QTreeWidgetItem）。

        Returns:
            None: 用户取消编辑时不修改。
        """
        text = item.text(0)

        if text.startswith('[CMD]'):
            current_command = text[5:].strip()
            from PyQt6.QtWidgets import QInputDialog
            new_command, ok = QInputDialog.getText(self, '修改指令', '请输入新的指令和参数:', text=current_command)
            if ok:
                item.setText(0, f"[CMD] {new_command}")
                self.log_message(f"已修改序列中的指令: {new_command}")
        elif text.startswith('[DELAY]'):
            current_delay = text[7:].replace('ms', '').strip()
            from PyQt6.QtWidgets import QInputDialog
            new_delay, ok = QInputDialog.getInt(self, '修改延迟', '请输入新的延迟时间（毫秒）:', int(current_delay), 1, 30000)
            if ok:
                item.setText(0, f"[DELAY] {new_delay}ms")
                self.log_message(f"已修改序列中的延迟: {new_delay}ms")
        elif text.startswith('[PAUSE]'):
            current_message = text[7:].strip()
            from PyQt6.QtWidgets import QInputDialog
            new_message, ok = QInputDialog.getText(self, '修改暂停', '请输入新的暂停提示信息:', text=current_message)
            if ok:
                item.setText(0, f"[PAUSE] {new_message}")
                self.log_message(f"已修改序列中的暂停: {new_message}")

    def _add_child_to_group(self, group, text, checked=True):
        """向指定序列组追加一个指令节点。

        Args:
            group: 顶层序列组节点。
            text: 节点显示文本，如 [CMD] xxx。
            checked: 是否默认勾选。

        Returns:
            QTreeWidgetItem: 新建的指令节点。
        """
        child = QTreeWidgetItem([text])
        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        group.addChild(child)
        group.setExpanded(True)
        return child

    def add_delay_to_sequence(self):
        """添加延迟到当前序列组。

        弹出对话框让用户输入延迟时间（毫秒），范围1-30000ms。
        """
        from PyQt6.QtWidgets import QInputDialog
        delay, ok = QInputDialog.getInt(self, '添加延迟', '请输入延迟时间（毫秒）:', 1000, 1, 30000)
        if ok:
            group = self._ensure_default_group()
            self._add_child_to_group(group, f"[DELAY] {delay}ms")
            self.log_message(f"已添加延迟到序列: {delay}ms")

    def add_pause_to_sequence(self):
        """添加暂停到当前序列组。

        弹出对话框让用户输入暂停提示信息，执行到此时会等待用户确认。
        """
        from PyQt6.QtWidgets import QInputDialog
        message, ok = QInputDialog.getText(self, '添加暂停', '请输入暂停提示信息:', text='执行到此处，是否继续？')
        if ok:
            group = self._ensure_default_group()
            self._add_child_to_group(group, f"[PAUSE] {message}")
            self.log_message(f"已添加暂停到序列: {message}")
    
    def execute_sequence(self):
        """执行指令序列。

        依次遍历每个序列组中所有已勾选的指令（仅执行组已勾选的），
        支持命令、延迟和暂停三种类型。延迟使用QTimer实现非阻塞等待，
        暂停会弹出确认对话框。

        Warning:
            执行期间会阻塞UI线程，不建议在序列中添加过长的延迟
        """
        if not self.rpc_clients:
            self.log_message('没有已连接的通道，请先连接通道')
            return

        total = 0
        for gi in range(self.sequenceList.topLevelItemCount()):
            group = self.sequenceList.topLevelItem(gi)
            if group.checkState(0) == Qt.CheckState.Unchecked:
                continue
            total += group.childCount()

        if total == 0:
            self.log_message('序列为空，请先添加指令或延迟')
            return

        self.log_message('开始执行指令序列...')

        try:
            rpc_timeout = int(self.timeoutInput.text().strip())
        except (ValueError, AttributeError):
            rpc_timeout = 30

        for gi in range(self.sequenceList.topLevelItemCount()):
            group = self.sequenceList.topLevelItem(gi)
            if group.checkState(0) == Qt.CheckState.Unchecked:
                # 组被取消勾选，跳过整组
                continue
            for ci in range(group.childCount()):
                item = group.child(ci)
                if item.checkState(0) != Qt.CheckState.Checked:
                    continue

                text = item.text(0)

                if text.startswith('[CMD]'):
                    command = text[5:].strip()
                    self.log_message(f'[序列] 执行指令: {command}')

                    parts = _split_command_args(command)
                    if len(parts) < 1:
                        self.log_message('[序列] 命令格式错误')
                        continue

                    cmd = parts[0]
                    args = []
                    kwargs = {}

                    for part in parts[1:]:
                        if '=' in part:
                            key, value = part.split('=', 1)
                            kwargs[key] = _parse_arg(value)
                        else:
                            if part != "" and part != " ":
                                args.append(_parse_arg(part))

                    if '.' in cmd:
                        service_name, method_name = cmd.split('.', 1)
                    else:
                        self.log_message('[序列] 命令格式错误，应为 service.method')
                        continue
                    self.sequence = True
                    self.send_command_to_all_channels(service_name, method_name, command, rpc_timeout, *args, **kwargs)
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
        """清空所有序列组。

        移除序列树中的所有项，并重建默认序列组。
        """
        self.sequenceList.clear()
        self._ensure_default_group()
        self.log_message('已清空所有序列组')
    
    def save_sequence_group(self):
        """保存当前序列组（选中或默认组）到CSV文件。

        将单个序列组中的所有项（命令、延迟、暂停）保存到配置目录下的CSV文件。

        Returns:
            None: 无返回值，序列为空或用户取消时不保存
        """
        from utils.config import config_manager
        if self.sequenceList.topLevelItemCount() == 0:
            self.log_message('没有可保存的序列组')
            return

        group = self._current_group()
        self._save_one_group(group)

    def save_all_sequence_groups(self):
        """将所有序列组分别保存为CSV文件。

        每个序列组对应一个文件，文件名为序列组名称。
        """
        if self.sequenceList.topLevelItemCount() == 0:
            self.log_message('没有可保存的序列组')
            return
        for gi in range(self.sequenceList.topLevelItemCount()):
            group = self.sequenceList.topLevelItem(gi)
            self._save_one_group(group)
        self.log_message('已保存所有序列组')

    def _save_one_group(self, group):
        """把单个序列组写到配置目录下的 CSV 文件（文件名为组名）。

        Args:
            group: 顶层序列组节点。
        """
        from utils.config import config_manager

        if group.childCount() == 0:
            self.log_message(f'序列组为空，无法保存: {group.text(0)}')
            return

        name = group.text(0)
        # 组名中可能含路径分隔符等非法字符，做安全化处理，保证跨平台可用
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', name)
        config_dir = config_manager.get_config_dir()
        filename = safe_name if safe_name.endswith('.csv') else safe_name + '.csv'
        filepath = os.path.join(config_dir, filename)

        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['type', 'content', 'checked'])
                for ci in range(group.childCount()):
                    item = group.child(ci)
                    text = item.text(0)
                    checked = '1' if item.checkState(0) == Qt.CheckState.Checked else '0'
                    if text.startswith('[CMD]'):
                        writer.writerow(['CMD', text[5:].strip(), checked])
                    elif text.startswith('[DELAY]'):
                        writer.writerow(['DELAY', text[7:].replace('ms', '').strip(), checked])
                    elif text.startswith('[PAUSE]'):
                        writer.writerow(['PAUSE', text[7:].strip(), checked])

            self.log_message(f'序列组已保存到: {filepath}')
        except Exception as e:
            self.log_message(f'保存序列组失败: {str(e)}')

    def _build_group_from_file(self, filepath):
        """从 CSV 文件构建一个序列组节点（不解入树）。

        Args:
            filepath: CSV 文件绝对路径。

        Returns:
            QTreeWidgetItem: 已填充子节点的序列组，读取失败返回 None。
        """
        group_name = os.path.splitext(os.path.basename(filepath))[0]
        group = QTreeWidgetItem([group_name])
        group.setFlags(group.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        group.setCheckState(0, Qt.CheckState.Checked)
        group.setExpanded(False)  # 默认折叠

        with open(filepath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if len(row) >= 3:
                    item_type, content, checked = row[0], row[1], row[2]
                    if item_type == 'CMD':
                        child = QTreeWidgetItem([f"[CMD] {content}"])
                    elif item_type == 'DELAY':
                        child = QTreeWidgetItem([f"[DELAY] {content}ms"])
                    elif item_type == 'PAUSE':
                        child = QTreeWidgetItem([f"[PAUSE] {content}"])
                    else:
                        continue

                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.CheckState.Checked if checked == '1' else Qt.CheckState.Unchecked)
                    group.addChild(child)

        return group

    def _sequence_group_exists(self, group_name):
        """判断序列树中是否已存在同名序列组。

        Args:
            group_name: 组名。

        Returns:
            bool: 存在返回 True。
        """
        for gi in range(self.sequenceList.topLevelItemCount()):
            if self._group_name(gi) == group_name:
                return True
        return False

    def _add_group_from_file(self, filepath):
        """从 CSV 文件构建并加入序列树（同名则跳过）。

        Args:
            filepath: CSV 文件绝对路径。

        Returns:
            QTreeWidgetItem: 成功加入的序列组节点；未加入返回 None。
        """
        group_name = os.path.splitext(os.path.basename(filepath))[0]
        if self._sequence_group_exists(group_name):
            self.log_message(f'序列组已存在: {group_name}')
            return None
        try:
            group = self._build_group_from_file(filepath)
            self._apply_group_style(group)
            self.sequenceList.addTopLevelItem(group)
            self.sequenceList.setCurrentItem(group)
            self.log_message(f'已加载序列组: {group_name}')
            return group
        except Exception as e:
            self.log_message(f'加载序列组失败: {str(e)}')
            return None

    def load_sequence_group(self):
        """加载已保存的序列组。

        从配置目录中查找CSV文件，让用户选择后以新的序列组追加到序列树中，
        不会替换已有序列。若组名已存在则跳过。

        Returns:
            None: 无返回值，未找到文件或用户取消时不加载
        """
        from utils.config import config_manager

        config_dir = config_manager.get_config_dir()

        csv_files = sorted(glob.glob(os.path.join(config_dir, '*.csv')))

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
        self._add_group_from_file(filepath)

    def autoload_sequence_groups(self):
        """平台启动时自动加载所有已保存的序列组。

        扫描配置目录下的序列组 CSV 文件，把每个尚未加载的序列组以默认折叠的
        方式加入序列树，方便用户启动后直接选择/执行。

        Returns:
            int: 本次自动加载的序列组数量。
        """
        from utils.config import config_manager

        config_dir = config_manager.get_config_dir()
        csv_files = sorted(glob.glob(os.path.join(config_dir, '*.csv')))

        count = 0
        for f in csv_files:
            if self._add_group_from_file(f) is not None:
                count += 1
        if count > 0:
            self.log_message(f'启动自动加载序列组: {count} 个')
        return count