#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rsync文件同步插件 - 文件同步和获取工具

功能:
1. 扫描网络中可SSH连接的设备，使用uname显示远程系统信息
2. 点击VNC按钮远程连接对应IP
3. 配置界面: 配置IP、用户名、密码，选择设备
4. 多设备文件同步推送（rsync push）
5. 多设备指令发送（SSH命令执行）
6. 获取远程指定路径文件列表并拉取到本地（单设备操作）
"""

import sys
import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, QGroupBox,
    QMessageBox, QSplitter, QTabWidget, QCheckBox, QHeaderView, QSizePolicy,
    QPlainTextEdit, QFileDialog, QComboBox, QListWidget, QListWidgetItem,
    QMenu, QProgressBar, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

# 添加插件目录到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_manager import SSHManager, parse_ip_range, check_expect
from rsync_manager import RsyncManager
from vnc_manager import VNCManager
from config_dialog import RsyncConfig, ConfigDialog

# 紧凑布局常量（适配低分辨率工控机）
UI_SPACING = 2
UI_MARGIN = 2
UI_FONT_SIZE = 9
UI_BTN_HEIGHT = 22

try:
    from utils.logger import init_logger
    logger = init_logger(name="RsyncPlugin", log_file="rsync_plugin.log")
except Exception:
    import logging
    logger = logging.getLogger("RsyncPlugin")
    logger.addHandler(logging.NullHandler())

# QSS 样式表管理（加载 + 文件变更热重载，通用可复用模块）
try:
    from utils.stylesheet_manager import StyleSheetManager
except Exception:
    # 兜底：若模块导入失败则退化为 None，插件其他功能不受影响
    StyleSheetManager = None


def get_resource_path(relative_path):
    """获取资源文件的绝对路径。

    Args:
        relative_path: 相对于插件目录的路径

    Returns:
        str: 绝对路径
    """
    return os.path.join(PLUGIN_DIR, relative_path)


class ScanWorker(QObject):
    """网络扫描工作线程对象。

    在后台线程中扫描IP列表，通过信号通知进度和结果。

    Signals:
        progress: 扫描进度信号 (ip, is_online, uname, scanned, total)
        finished: 扫描完成信号 (results)
        log: 日志信号 (message)
    """
    progress = pyqtSignal(str, bool, str, int, int)
    finished = pyqtSignal(list)
    log = pyqtSignal(str)

    def __init__(self, ssh_manager, ip_list):
        """初始化扫描工作线程。

        Args:
            ssh_manager: SSHManager实例
            ip_list: 要扫描的IP列表
        """
        super().__init__()
        self.ssh_manager = ssh_manager
        self.ip_list = ip_list

    def run(self):
        """执行扫描。"""
        self.log.emit(f'开始扫描 {len(self.ip_list)} 个IP地址...')

        def progress_cb(ip, available, uname_info, scanned, total):
            self.progress.emit(ip, available, uname_info, scanned, total)

        results = self.ssh_manager.scan_network(self.ip_list, max_workers=20, progress_callback=progress_cb)
        self.finished.emit(results)
        self.log.emit(f'扫描完成，发现 {len(results)} 台可用设备')


class SyncWorker(QObject):
    """文件同步工作线程对象。

    在后台线程中执行rsync推送操作。

    Signals:
        log: 日志信号 (message)
        finished: 完成信号 (results_dict)
    """
    log = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, rsync_manager, ip_list, local_path, remote_path, delete):
        """初始化同步工作线程。

        Args:
            rsync_manager: RsyncManager实例
            ip_list: 目标IP列表
            local_path: 本地源路径
            remote_path: 远程目标路径
            delete: 是否删除目标中源端没有的文件
        """
        super().__init__()
        self.rsync_manager = rsync_manager
        self.ip_list = ip_list
        self.local_path = local_path
        self.remote_path = remote_path
        self.delete = delete

    def run(self):
        """执行同步推送。"""
        self.log.emit(f'开始同步到 {len(self.ip_list)} 台设备...')

        def output_cb(ip, line):
            self.log.emit(f'[{ip}] {line}')

        results = self.rsync_manager.push_to_multiple(
            self.ip_list, self.local_path, self.remote_path,
            delete=self.delete, output_callback=output_cb, max_workers=5
        )

        success_count = sum(1 for code, _ in results.values() if code == 0)
        self.log.emit(f'同步完成: 成功 {success_count}/{len(self.ip_list)} 台设备')
        self.finished.emit(results)


class CommandWorker(QObject):
    """命令发送工作线程对象。

    在后台线程中向多台设备发送SSH命令。

    Signals:
        log: 日志信号 (message)
        finished: 完成信号
    """
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, ssh_manager, ip_list, command):
        """初始化命令发送工作线程。

        Args:
            ssh_manager: SSHManager实例
            ip_list: 目标IP列表
            command: 要执行的命令字符串
        """
        super().__init__()
        self.ssh_manager = ssh_manager
        self.ip_list = ip_list
        self.command = command

    def run(self):
        """执行命令发送。"""
        self.log.emit(f'向 {len(self.ip_list)} 台设备发送命令: {self.command}')

        def send_one(ip):
            code, stdout, stderr = self.ssh_manager.execute_command(ip, self.command, timeout=30)
            if code == 0:
                self.log.emit(f'[{ip}] 返回码: {code}\n{stdout}')
            else:
                self.log.emit(f'[{ip}] 失败 (返回码: {code}): {stderr or stdout}')

        threads = []
        for ip in self.ip_list:
            t = threading.Thread(target=send_one, args=(ip,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        self.log.emit('命令发送完成')
        self.finished.emit()


class PullWorker(QObject):
    """文件拉取工作线程对象。

    在后台线程中从单台设备拉取文件。

    Signals:
        log: 日志信号 (message)
        files_listed: 文件列表信号 (files_list)
        finished: 完成信号 (success)
    """
    log = pyqtSignal(str)
    files_listed = pyqtSignal(list)
    finished = pyqtSignal(bool)

    def __init__(self, rsync_manager, ssh_manager, ip, remote_path, local_path, delete, mode='list'):
        """初始化文件拉取工作线程。

        Args:
            rsync_manager: RsyncManager实例
            ssh_manager: SSHManager实例
            ip: 远程设备IP
            remote_path: 远程路径
            local_path: 本地路径
            delete: 是否删除本地中远程没有的文件
            mode: 'list' 列出文件, 'pull' 拉取文件
        """
        super().__init__()
        self.rsync_manager = rsync_manager
        self.ssh_manager = ssh_manager
        self.ip = ip
        self.remote_path = remote_path
        self.local_path = local_path
        self.delete = delete
        self.mode = mode

    def run(self):
        """执行文件列表获取或拉取。"""
        if self.mode == 'list':
            self.log.emit(f'正在获取 {self.ip}:{self.remote_path} 的文件列表...')
            files = self.ssh_manager.list_remote_files(self.ip, self.remote_path)
            self.log.emit(f'获取到 {len(files)} 个文件/目录')
            self.files_listed.emit(files)
        elif self.mode == 'pull':
            self.log.emit(f'正在从 {self.ip}:{self.remote_path} 拉取文件到 {self.local_path}...')

            def output_cb(line):
                self.log.emit(f'[{self.ip}] {line}')

            code, output = self.rsync_manager.pull_from_device(
                self.ip, self.remote_path, self.local_path,
                delete=self.delete, output_callback=output_cb
            )
            if code == 0:
                self.log.emit(f'拉取完成: {self.ip}')
                self.finished.emit(True)
            else:
                self.log.emit(f'拉取失败: {self.ip} (返回码: {code})')
                self.finished.emit(False)


class DeployWorker(QObject):
    """部署工作线程对象。

    先执行rsync同步，同步成功后再对成功设备依次执行指令序列。
    参考 JSYNC-PUSH 脚本的工作流：同步文件 → 执行部署指令（killall/open/cp/ln等）。

    Signals:
        log: 日志信号 (message)
        finished: 完成信号 (sync_results_dict)
    """
    log = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, rsync_manager, ssh_manager, ip_list,
                 local_path, remote_path, delete, commands):
        """初始化部署工作线程。

        Args:
            rsync_manager: RsyncManager实例
            ssh_manager: SSHManager实例
            ip_list: 目标IP列表
            local_path: 本地源路径
            remote_path: 远程目标路径
            delete: 是否删除目标中源端没有的文件
            commands: 同步后执行的指令列表（每条一个元素，空列表表示仅同步）
        """
        super().__init__()
        self.rsync_manager = rsync_manager
        self.ssh_manager = ssh_manager
        self.ip_list = ip_list
        self.local_path = local_path
        self.remote_path = remote_path
        self.delete = delete
        self.commands = commands

    def run(self):
        """执行部署工作流：阶段1同步 → 阶段2指令序列。"""
        # 阶段1: rsync 同步
        self.log.emit(f'=== 阶段1: 文件同步 ({len(self.ip_list)} 台设备) ===')

        def output_cb(ip, line):
            self.log.emit(f'[同步 {ip}] {line}')

        sync_results = self.rsync_manager.push_to_multiple(
            self.ip_list, self.local_path, self.remote_path,
            delete=self.delete, output_callback=output_cb, max_workers=5
        )
        success_ips = [ip for ip, (code, _) in sync_results.items() if code == 0]
        self.log.emit(f'同步完成: 成功 {len(success_ips)}/{len(self.ip_list)} 台')

        # 阶段2: 对同步成功的设备执行指令序列
        if not self.commands:
            self.log.emit('无同步后指令，部署完成')
        elif not success_ips:
            self.log.emit('无设备同步成功，跳过指令执行')
        else:
            self.log.emit(f'=== 阶段2: 执行指令序列 ({len(self.commands)} 条 → {len(success_ips)} 台) ===')
            results_lock = threading.Lock()
            cmd_results = {}

            def exec_one(ip):
                """对单台设备依次执行所有指令，某条失败则停止该设备后续指令。"""
                all_ok = True
                for idx, cmd in enumerate(self.commands, 1):
                    code, stdout, stderr = self.ssh_manager.execute_command(ip, cmd, timeout=60)
                    if code == 0:
                        self.log.emit(f'[{ip}] ({idx}/{len(self.commands)}) OK: {cmd}')
                        if stdout:
                            self.log.emit(f'[{ip}] {stdout}')
                    else:
                        self.log.emit(f'[{ip}] ({idx}/{len(self.commands)}) 失败({code}): {cmd}')
                        if stderr:
                            self.log.emit(f'[{ip}] {stderr}')
                        all_ok = False
                        break
                with results_lock:
                    cmd_results[ip] = all_ok

            threads = []
            for ip in success_ips:
                t = threading.Thread(target=exec_one, args=(ip,), daemon=True)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

            cmd_success = sum(1 for ok in cmd_results.values() if ok)
            self.log.emit(f'指令执行完成: 成功 {cmd_success}/{len(success_ips)} 台')

        self.finished.emit(sync_results)


class RsyncPlugin(QWidget):
    """Rsync文件同步插件主窗口。

    提供设备扫描、文件同步、指令发送、文件拉取、VNC连接等功能。

    Attributes:
        version: 插件版本号
        config: RsyncConfig配置实例
        ssh_manager: SSH管理器
        rsync_manager: Rsync管理器
        vnc_manager: VNC管理器
        style_manager: StyleSheetManager样式表热重载管理器
    """

    def __init__(self, parent=None):
        """初始化Rsync插件主窗口。"""
        super().__init__(parent)
        self.version = 'v1.0'
        self.setWindowTitle(f'Rsync-Sync {self.version} by:zjx')

        # 初始化配置和管理器
        self.config = RsyncConfig()
        self._update_managers()

        # 样式表管理器（失败不影响其他功能）
        self.style_manager = None
        if StyleSheetManager is not None:
            try:
                self.style_manager = StyleSheetManager(self)
            except Exception:
                self.style_manager = None

        self.scan_worker = None
        self.sync_worker = None
        self.command_worker = None
        self.pull_worker = None
        self.deploy_worker = None
        self.log_mutex = threading.Lock()

        self._init_ui()
        self._check_dependencies()

    def _update_managers(self):
        """根据配置更新管理器实例。"""
        username = self.config.get('username', 'gdlocal')
        password = self.config.get('password', 'gdlocal')
        port = self.config.get('port', 22)
        self.ssh_manager = SSHManager(username, password, port)
        self.rsync_manager = RsyncManager(username, password, port)
        self.vnc_manager = VNCManager()

    def _check_dependencies(self):
        """检查依赖项（expect，系统自带）。"""
        if check_expect():
            self.log_message('认证方式: expect')
        else:
            self.log_message('错误: expect未安装，SSH/Rsync功能将无法使用')
            self.log_message('请确认系统已安装 expect（macOS/Linux 通常自带）')

    def _bind_deploy_button_style(self, qss_path: str) -> None:
        """绑定部署按钮样式到外部 .qss 文件，启动加载 + 文件变更自动热重载。

        通过 StyleSheetManager（utils.stylesheet_manager）通用模块加载；
        若模块不可用或文件不存在，则回退为硬编码默认样式（保持功能正常）。

        Args:
            qss_path: .qss 文件的绝对路径（通常在插件目录下 styles/ 子目录）。
        """
        # 模块不可用时回退硬编码样式
        if self.style_manager is None:
            self.deploy_btn.setStyleSheet(
                'QPushButton{background-color:#9C27B0;color:white;'
                'font-weight:bold;border-radius:3px;}'
                'QPushButton:hover{background-color:#7B1FA2;}'
                'QPushButton:disabled{background-color:#aaa;}'
            )
            return

        def _on_reload(path: str, widget) -> None:
            """样式首次加载/热重载后的日志回调。"""
            from pathlib import Path
            self.log_message(f'部署按钮样式已加载: {Path(path).name}')

        ok = self.style_manager.bind_style(
            self.deploy_btn,
            qss_path,
            auto_watch=True,
            on_reload=_on_reload,
        )
        if not ok:
            # .qss 文件不存在或不可读，打印提示并回退默认样式
            self.log_message(
                f'警告: 部署按钮样式文件不存在 ({qss_path})，使用内置默认样式'
            )
            self.deploy_btn.setStyleSheet(
                'QPushButton{background-color:#9C27B0;color:white;'
                'font-weight:bold;border-radius:3px;}'
                'QPushButton:hover{background-color:#7B1FA2;}'
                'QPushButton:disabled{background-color:#aaa;}'
            )

    def _init_ui(self):
        """初始化紧凑界面（适配低分辨率工控机）。

        布局策略：垂直单列，工具栏→进度条→模式切换→设备表→操作面板→日志。
        取消左右分割，操作面板使用 QStackedWidget 切换，日志可折叠。
        """
        # 应用紧凑字体到本插件
        self.setFont(QFont(self.font().family(), UI_FONT_SIZE))

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(UI_SPACING)
        main_layout.setContentsMargins(UI_MARGIN, UI_MARGIN, UI_MARGIN, UI_MARGIN)

        # ===== 1. 顶部工具栏（单行紧凑）=====
        toolbar = QHBoxLayout()
        toolbar.setSpacing(UI_SPACING)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(QLabel('扫描:'))
        self.scan_range_edit = QLineEdit(self.config.get('scan_range', '10.8.30.14-23'))
        self.scan_range_edit.setPlaceholderText('10.8.30.14-23 或 10.8.30.0/24')
        toolbar.addWidget(self.scan_range_edit, 1)

        self.scan_btn = self._make_btn('扫描')
        self.scan_btn.clicked.connect(self.on_scan)
        toolbar.addWidget(self.scan_btn)

        self.stop_scan_btn = self._make_btn('停止')
        self.stop_scan_btn.setEnabled(False)
        toolbar.addWidget(self.stop_scan_btn)

        self.config_btn = self._make_btn('配置')
        self.config_btn.clicked.connect(self.on_config)
        toolbar.addWidget(self.config_btn)

        # 日志折叠按钮
        self.toggle_log_btn = self._make_btn('▾日志')
        self.toggle_log_btn.setCheckable(True)
        self.toggle_log_btn.setChecked(True)
        self.toggle_log_btn.clicked.connect(self._toggle_log)
        toolbar.addWidget(self.toggle_log_btn)

        main_layout.addLayout(toolbar)

        # ===== 2. 进度条（细条）=====
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # ===== 3. 操作模式切换行 =====
        mode_row = QHBoxLayout()
        mode_row.setSpacing(UI_SPACING)
        mode_row.setContentsMargins(0, 0, 0, 0)

        # 模式按钮（checkable，互斥）
        self.mode_btn_group = []
        for idx, text in enumerate([('推送', 0), ('拉取', 1), ('指令', 2), ('部署', 3)]):
            btn = self._make_btn(text[0])
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=idx: self._on_mode_changed(i))
            self.mode_btn_group.append(btn)
            mode_row.addWidget(btn)
        self.mode_btn_group[0].setChecked(True)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        mode_row.addWidget(sep)

        select_all_btn = self._make_btn('全选')
        select_all_btn.clicked.connect(self.select_all_devices)
        mode_row.addWidget(select_all_btn)

        deselect_all_btn = self._make_btn('取消全选')
        deselect_all_btn.clicked.connect(self.deselect_all_devices)
        mode_row.addWidget(deselect_all_btn)

        mode_row.addStretch()

        self.selected_count_label = QLabel('已选 0 台')
        self.selected_count_label.setStyleSheet('color: #666; padding-right: 4px;')
        mode_row.addWidget(self.selected_count_label)

        main_layout.addLayout(mode_row)

        # ===== 4. 设备表（4列：选择/IP/主机名/VNC）=====
        self.device_table = QTableWidget(0, 4)
        self.device_table.setHorizontalHeaderLabels(['选', 'IP地址', '主机名', 'VNC'])
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setShowGrid(False)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # 列宽策略：选择/VNC 紧凑，IP 适配内容，主机名 拉伸
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        # 紧凑行高
        self.device_table.verticalHeader().setDefaultSectionSize(22)
        main_layout.addWidget(self.device_table, 1)

        # ===== 5. 操作面板（QStackedWidget）=====
        self.ops_stack = QStackedWidget()
        self.ops_stack.setCurrentIndex(0)

        # --- 推送面板（单行）---
        push_page = QWidget()
        push_layout = QHBoxLayout(push_page)
        push_layout.setSpacing(UI_SPACING)
        push_layout.setContentsMargins(0, 0, 0, 0)
        push_layout.addWidget(QLabel('本地:'))
        self.sync_local_edit = QLineEdit(self.config.get('push_local_path', ''))
        self.sync_local_edit.setPlaceholderText('本地源路径')
        push_layout.addWidget(self.sync_local_edit, 2)
        sync_local_btn = self._make_btn('…')
        sync_local_btn.setMaximumWidth(24)
        sync_local_btn.clicked.connect(lambda: self._browse_dir(self.sync_local_edit))
        push_layout.addWidget(sync_local_btn)

        push_layout.addWidget(QLabel('远程:'))
        self.sync_remote_edit = QLineEdit(self.config.get('push_remote_path', '/vault/ZJX_backup'))
        self.sync_remote_edit.setPlaceholderText('远程目标路径')
        push_layout.addWidget(self.sync_remote_edit, 2)

        self.sync_delete_cb = QCheckBox('删除')
        self.sync_delete_cb.setToolTip('--delete: 删除目标中源端没有的文件')
        push_layout.addWidget(self.sync_delete_cb)

        self.sync_btn = self._make_btn('推送到已选')
        self.sync_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white;
                font-weight: bold; border-radius: 3px; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #aaa; }
        """)
        self.sync_btn.clicked.connect(self.on_sync_push)
        push_layout.addWidget(self.sync_btn)

        self.ops_stack.addWidget(push_page)

        # --- 拉取面板（两行：表单 + 文件列表）---
        pull_page = QWidget()
        pull_layout = QVBoxLayout(pull_page)
        pull_layout.setSpacing(UI_SPACING)
        pull_layout.setContentsMargins(0, 0, 0, 0)

        # 第一行：路径与按钮
        pull_row1 = QHBoxLayout()
        pull_row1.setSpacing(UI_SPACING)
        pull_row1.setContentsMargins(0, 0, 0, 0)
        pull_row1.addWidget(QLabel('设备:'))
        self.pull_ip_combo = QComboBox()
        self.pull_ip_combo.setPlaceholderText('选择IP')
        self.pull_ip_combo.setMinimumWidth(110)
        pull_row1.addWidget(self.pull_ip_combo)

        pull_row1.addWidget(QLabel('远程:'))
        self.pull_remote_edit = QLineEdit(self.config.get('pull_remote_path', ''))
        self.pull_remote_edit.setPlaceholderText('远程路径')
        pull_row1.addWidget(self.pull_remote_edit, 2)

        self.list_files_btn = self._make_btn('列出')
        self.list_files_btn.clicked.connect(self.on_list_files)
        pull_row1.addWidget(self.list_files_btn)
        pull_layout.addLayout(pull_row1)

        # 第二行：本地路径 + 拉取按钮
        pull_row2 = QHBoxLayout()
        pull_row2.setSpacing(UI_SPACING)
        pull_row2.setContentsMargins(0, 0, 0, 0)
        pull_row2.addWidget(QLabel('本地:'))
        self.pull_local_edit = QLineEdit(self.config.get('pull_local_path', ''))
        self.pull_local_edit.setPlaceholderText('本地保存路径')
        pull_row2.addWidget(self.pull_local_edit, 2)
        pull_local_btn = self._make_btn('…')
        pull_local_btn.setMaximumWidth(24)
        pull_local_btn.clicked.connect(lambda: self._browse_dir(self.pull_local_edit))
        pull_row2.addWidget(pull_local_btn)

        self.pull_delete_cb = QCheckBox('删除')
        self.pull_delete_cb.setToolTip('--delete')
        pull_row2.addWidget(self.pull_delete_cb)

        self.pull_btn = self._make_btn('拉取到本地')
        self.pull_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white;
                font-weight: bold; border-radius: 3px; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #aaa; }
        """)
        self.pull_btn.clicked.connect(self.on_pull_files)
        pull_row2.addWidget(self.pull_btn)
        pull_layout.addLayout(pull_row2)

        # 第三行：远程文件列表（紧凑高度）
        self.file_list_widget = QListWidget()
        self.file_list_widget.setMaximumHeight(80)
        self.file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        pull_layout.addWidget(self.file_list_widget)

        self.ops_stack.addWidget(pull_page)

        # --- 指令面板（命令行 + 历史列表）---
        cmd_page = QWidget()
        cmd_layout = QVBoxLayout(cmd_page)
        cmd_layout.setSpacing(UI_SPACING)
        cmd_layout.setContentsMargins(0, 0, 0, 0)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(UI_SPACING)
        cmd_row.setContentsMargins(0, 0, 0, 0)
        cmd_row.addWidget(QLabel('命令:'))
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText('uname -a / hostname / ls /tmp')
        cmd_row.addWidget(self.cmd_edit, 2)

        self.cmd_btn = self._make_btn('发送到已选')
        self.cmd_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white;
                font-weight: bold; border-radius: 3px; }
            QPushButton:hover { background-color: #F57C00; }
            QPushButton:disabled { background-color: #aaa; }
        """)
        self.cmd_btn.clicked.connect(self.on_send_command)
        cmd_row.addWidget(self.cmd_btn)
        cmd_layout.addLayout(cmd_row)

        # 历史命令（紧凑高度）
        self.cmd_history_list = QListWidget()
        self.cmd_history_list.setMaximumHeight(80)
        self.cmd_history_list.itemDoubleClicked.connect(self._use_history_command)
        self.cmd_history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cmd_history_list.customContextMenuRequested.connect(self._show_cmd_history_menu)
        cmd_layout.addWidget(self.cmd_history_list)

        self.ops_stack.addWidget(cmd_page)

        # --- 部署面板（rsync同步 → 执行指令序列，参考 JSYNC-PUSH 工作流）---
        deploy_page = QWidget()
        deploy_layout = QVBoxLayout(deploy_page)
        deploy_layout.setSpacing(UI_SPACING)
        deploy_layout.setContentsMargins(0, 0, 0, 0)

        # 第一行：本地/远程路径 + 删除选项（与推送面板一致）
        deploy_row1 = QHBoxLayout()
        deploy_row1.setSpacing(UI_SPACING)
        deploy_row1.setContentsMargins(0, 0, 0, 0)
        deploy_row1.addWidget(QLabel('本地:'))
        self.deploy_local_edit = QLineEdit(self.config.get('deploy_local_path', ''))
        self.deploy_local_edit.setPlaceholderText('本地源路径')
        deploy_row1.addWidget(self.deploy_local_edit, 2)
        deploy_local_btn = self._make_btn('…')
        deploy_local_btn.setMaximumWidth(24)
        deploy_local_btn.clicked.connect(lambda: self._browse_dir(self.deploy_local_edit))
        deploy_row1.addWidget(deploy_local_btn)

        deploy_row1.addWidget(QLabel('远程:'))
        self.deploy_remote_edit = QLineEdit(self.config.get('deploy_remote_path', '/vault/ZJX_backup'))
        self.deploy_remote_edit.setPlaceholderText('远程目标路径')
        deploy_row1.addWidget(self.deploy_remote_edit, 2)

        self.deploy_delete_cb = QCheckBox('删除')
        self.deploy_delete_cb.setToolTip('--delete: 删除目标中源端没有的文件')
        deploy_row1.addWidget(self.deploy_delete_cb)
        deploy_layout.addLayout(deploy_row1)

        # 第二行：同步后指令序列标签
        deploy_label_row = QHBoxLayout()
        deploy_label_row.setSpacing(UI_SPACING)
        deploy_label_row.setContentsMargins(0, 0, 0, 0)
        deploy_label_row.addWidget(QLabel('同步后指令（每行一条，留空则仅同步）:'))
        deploy_label_row.addStretch()
        deploy_layout.addLayout(deploy_label_row)

        # 第三行：多行指令输入框
        self.deploy_cmds_edit = QPlainTextEdit()
        self.deploy_cmds_edit.setPlaceholderText(
            'killall shTool\n'
            'open /vault/ZJX_backup/shTool.app/Contents/Resources/Tool/auto\n'
            'cp -r /vault/ZJX_backup/MIX-Tool/ /Users/gdlocal/.MIX-Tool/\n'
            'ln -s /vault/ZJX_backup/shTool/AtlasDataProcessorPlus.app ~/Desktop'
        )
        # 恢复已保存的指令
        saved_cmds = self.config.get('deploy_commands', '')
        if saved_cmds:
            self.deploy_cmds_edit.setPlainText(saved_cmds)
        self.deploy_cmds_edit.setFixedHeight(90)
        deploy_layout.addWidget(self.deploy_cmds_edit)

        # 第四行：部署按钮（样式从外部 .qss 加载，支持热重载）
        deploy_btn_row = QHBoxLayout()
        deploy_btn_row.setSpacing(UI_SPACING)
        deploy_btn_row.setContentsMargins(0, 0, 0, 0)
        deploy_btn_row.addStretch()
        self.deploy_btn = self._make_btn('部署到已选')
        # 从同级 styles/deploy_btn.qss 加载样式并启用热重载
        qss_path = os.path.join(PLUGIN_DIR, 'styles', 'deploy_btn.qss')
        self._bind_deploy_button_style(qss_path)
        self.deploy_btn.clicked.connect(self.on_deploy)
        deploy_btn_row.addWidget(self.deploy_btn)
        deploy_layout.addLayout(deploy_btn_row)

        self.ops_stack.addWidget(deploy_page)

        main_layout.addWidget(self.ops_stack)

        # ===== 6. 日志区（可折叠）=====
        self.log_container = QFrame()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setSpacing(UI_SPACING)
        log_layout.setContentsMargins(0, 0, 0, 0)

        log_header = QHBoxLayout()
        log_header.setSpacing(UI_SPACING)
        log_header.setContentsMargins(0, 0, 0, 0)
        log_header.addWidget(QLabel('日志'))
        log_header.addStretch()
        clear_log_btn = self._make_btn('清空')
        clear_log_btn.clicked.connect(self.clear_log)
        log_header.addWidget(clear_log_btn)
        log_layout.addLayout(log_header)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier New", UI_FONT_SIZE))
        self.log_text.setFixedHeight(80)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(self.log_container)

    @staticmethod
    def _make_btn(text):
        """创建紧凑按钮。

        Args:
            text: 按钮文本

        Returns:
            QPushButton: 固定高度的紧凑按钮
        """
        btn = QPushButton(text)
        btn.setFixedHeight(UI_BTN_HEIGHT)
        return btn

    def _on_mode_changed(self, index):
        """切换操作模式（推送/拉取/指令/部署）。

        Args:
            index: 模式索引 0=推送 1=拉取 2=指令 3=部署
        """
        # 互斥选中
        for i, btn in enumerate(self.mode_btn_group):
            btn.setChecked(i == index)
        self.ops_stack.setCurrentIndex(index)

    def _toggle_log(self):
        """折叠/展开日志区域。"""
        self.log_container.setVisible(self.toggle_log_btn.isChecked())
        # 更新按钮文字指示状态
        self.toggle_log_btn.setText('▾日志' if self.toggle_log_btn.isChecked() else '▸日志')

    def _update_selected_count(self):
        """更新已选设备数量显示。"""
        count = len(self.get_selected_ips())
        self.selected_count_label.setText(f'已选 {count} 台')

    def log_message(self, message):
        """记录日志消息到界面。

        线程安全，使用互斥锁保护。

        Args:
            message: 日志消息字符串
        """
        with self.log_mutex:
            self.log_text.appendPlainText(message)
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_text.setTextCursor(cursor)
        logger.info(message)

    def clear_log(self):
        """清空日志显示。"""
        self.log_text.clear()

    def _browse_dir(self, edit_widget):
        """打开目录选择对话框。

        Args:
            edit_widget: 要填充路径的QLineEdit控件
        """
        dir_path = QFileDialog.getExistingDirectory(self, '选择目录')
        if dir_path:
            edit_widget.setText(dir_path)

    def on_config(self):
        """打开配置对话框。"""
        dialog = ConfigDialog(self.config, self)
        if dialog.exec():
            self._update_managers()
            self.scan_range_edit.setText(self.config.get('scan_range', ''))
            self.sync_local_edit.setText(self.config.get('push_local_path', ''))
            self.sync_remote_edit.setText(self.config.get('push_remote_path', ''))
            self.pull_remote_edit.setText(self.config.get('pull_remote_path', ''))
            self.pull_local_edit.setText(self.config.get('pull_local_path', ''))
            self.log_message('配置已更新')

    def on_scan(self):
        """执行设备扫描。"""
        scan_range = self.scan_range_edit.text().strip()
        if not scan_range:
            QMessageBox.warning(self, '警告', '请输入扫描范围')
            return

        ip_list = parse_ip_range(scan_range)
        if not ip_list:
            QMessageBox.warning(self, '警告', '无法解析IP范围，请检查格式')
            return

        # 清空设备表
        self.device_table.setRowCount(0)
        self.pull_ip_combo.clear()
        self._update_selected_count()

        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(ip_list))
        self.scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)

        # 创建扫描工作线程
        self._scan_thread = threading.Thread()
        self.scan_worker = ScanWorker(self.ssh_manager, ip_list)
        self.scan_worker_thread = threading.Thread(target=self.scan_worker.run, daemon=True)

        # 连接信号
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.log.connect(self.log_message)

        self.scan_worker_thread.start()

    def on_scan_progress(self, ip, is_online, uname, scanned, total):
        """扫描进度回调。

        Args:
            ip: 当前扫描的IP
            is_online: 是否在线可用
            uname: 远程系统信息
            scanned: 已扫描数量
            total: 总数量
        """
        self.progress_bar.setValue(scanned)
        if is_online:
            self._add_device_row(ip, uname)
            self.log_message(f'  [在线] {ip} - {uname}')

    def on_scan_finished(self, results):
        """扫描完成回调。

        Args:
            results: 扫描结果列表
        """
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.log_message(f'扫描完成，共发现 {len(results)} 台可用设备')

        # 更新拉取设备下拉框
        self.pull_ip_combo.clear()
        for dev in results:
            self.pull_ip_combo.addItem(dev['ip'])

        # 保存设备列表到配置
        devices = [{'ip': dev['ip'], 'uname': dev['uname']} for dev in results]
        self.config.set_devices(devices)

    def _add_device_row(self, ip, uname):
        """向设备表添加一行设备记录。

        Args:
            ip: 设备IP地址
            uname: 系统信息
        """
        row = self.device_table.rowCount()
        self.device_table.insertRow(row)

        # 选择复选框（居中、无 margin）
        cb = QCheckBox()
        cb.setChecked(True)
        cb.stateChanged.connect(lambda _: self._update_selected_count())
        cb_widget = QWidget()
        cb_layout = QHBoxLayout(cb_widget)
        cb_layout.addWidget(cb)
        cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        self.device_table.setCellWidget(row, 0, cb_widget)

        # IP地址
        ip_item = QTableWidgetItem(ip)
        ip_item.setToolTip(ip)
        self.device_table.setItem(row, 1, ip_item)

        # 主机名（仅显示 hostname，完整 uname 放 tooltip）
        hostname = self._extract_hostname(uname)
        host_item = QTableWidgetItem(hostname)
        host_item.setToolTip(uname)
        self.device_table.setItem(row, 2, host_item)

        # VNC按钮（紧凑）
        vnc_btn = QPushButton('VNC')
        vnc_btn.setFixedHeight(UI_BTN_HEIGHT)
        vnc_btn.clicked.connect(lambda checked, target_ip=ip: self.on_open_vnc(target_ip))
        self.device_table.setCellWidget(row, 3, vnc_btn)

        # 新增行后刷新已选计数
        self._update_selected_count()

    @staticmethod
    def _extract_hostname(uname_str):
        """从uname -a输出中提取主机名（第2个字段）。

        uname -a 格式: "Darwin JQ02-3F-RD01 20.6.0 Darwin Kernel ..."
        提取第2字段作为主机名显示，避免列宽被完整输出撑爆。

        Args:
            uname_str: uname -a 输出字符串

        Returns:
            str: 主机名，解析失败时返回原字符串
        """
        if not uname_str:
            return ''
        parts = uname_str.split()
        if len(parts) >= 2:
            return parts[1]
        return uname_str

    def on_open_vnc(self, ip):
        """打开VNC连接到指定IP。

        Args:
            ip: 目标IP地址
        """
        self.log_message(f'正在打开VNC连接: {ip}')
        if self.vnc_manager.open_vnc_by_ip(ip):
            self.log_message(f'VNC连接已启动: {ip}')
        else:
            self.log_message(f'VNC连接失败: {ip}')

    def select_all_devices(self):
        """全选设备。"""
        for row in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(True)
        self._update_selected_count()

    def deselect_all_devices(self):
        """取消全选设备。"""
        for row in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(False)
        self._update_selected_count()

    def get_selected_ips(self):
        """获取已选中的设备IP列表。

        Returns:
            list: 已选中的IP地址列表
        """
        selected = []
        for row in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    ip_item = self.device_table.item(row, 1)
                    if ip_item:
                        selected.append(ip_item.text())
        return selected

    def on_sync_push(self):
        """执行文件同步推送。"""
        ip_list = self.get_selected_ips()
        if not ip_list:
            QMessageBox.warning(self, '警告', '请先选择至少一台设备')
            return

        local_path = self.sync_local_edit.text().strip()
        remote_path = self.sync_remote_edit.text().strip()
        if not local_path or not remote_path:
            QMessageBox.warning(self, '警告', '请填写本地路径和远程路径')
            return

        if not os.path.exists(local_path):
            QMessageBox.warning(self, '警告', f'本地路径不存在: {local_path}')
            return

        delete = self.sync_delete_cb.isChecked()
        self.sync_btn.setEnabled(False)

        # 创建同步工作线程
        self.sync_worker = SyncWorker(self.rsync_manager, ip_list, local_path, remote_path, delete)
        self.sync_worker.log.connect(self.log_message)

        def on_finished(results):
            self.sync_btn.setEnabled(True)
            success = sum(1 for code, _ in results.values() if code == 0)
            self.log_message(f'同步结果: 成功 {success}/{len(results)}')

        self.sync_worker.finished.connect(on_finished)

        self.sync_worker_thread = threading.Thread(target=self.sync_worker.run, daemon=True)
        self.sync_worker_thread.start()

    def on_list_files(self):
        """列出远程设备指定路径下的文件。"""
        ip = self.pull_ip_combo.currentText().strip()
        if not ip:
            QMessageBox.warning(self, '警告', '请先选择设备')
            return

        remote_path = self.pull_remote_edit.text().strip()
        if not remote_path:
            QMessageBox.warning(self, '警告', '请填写远程路径')
            return

        self.list_files_btn.setEnabled(False)
        self.file_list_widget.clear()

        self.pull_worker = PullWorker(
            self.rsync_manager, self.ssh_manager,
            ip, remote_path, '', False, mode='list'
        )
        self.pull_worker.log.connect(self.log_message)

        def on_files_listed(files):
            self.list_files_btn.setEnabled(True)
            for f in files:
                icon = '[DIR]  ' if f['type'] == 'dir' else '[FILE] '
                item_text = f"{icon}{f['name']}  ({f['size']}B, {f['modify']})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, f)
                self.file_list_widget.addItem(item)

        self.pull_worker.files_listed.connect(on_files_listed)

        self.pull_worker_thread = threading.Thread(target=self.pull_worker.run, daemon=True)
        self.pull_worker_thread.start()

    def on_pull_files(self):
        """从远程设备拉取文件到本地。"""
        ip = self.pull_ip_combo.currentText().strip()
        if not ip:
            QMessageBox.warning(self, '警告', '请先选择设备')
            return

        remote_path = self.pull_remote_edit.text().strip()
        local_path = self.pull_local_edit.text().strip()
        if not remote_path or not local_path:
            QMessageBox.warning(self, '警告', '请填写远程路径和本地路径')
            return

        delete = self.pull_delete_cb.isChecked()
        self.pull_btn.setEnabled(False)

        self.pull_worker = PullWorker(
            self.rsync_manager, self.ssh_manager,
            ip, remote_path, local_path, delete, mode='pull'
        )
        self.pull_worker.log.connect(self.log_message)

        def on_finished(success):
            self.pull_btn.setEnabled(True)
            if success:
                self.log_message(f'文件拉取成功: {ip}')

        self.pull_worker.finished.connect(on_finished)

        self.pull_worker_thread = threading.Thread(target=self.pull_worker.run, daemon=True)
        self.pull_worker_thread.start()

    def on_send_command(self):
        """向已选设备发送命令。"""
        ip_list = self.get_selected_ips()
        if not ip_list:
            QMessageBox.warning(self, '警告', '请先选择至少一台设备')
            return

        command = self.cmd_edit.text().strip()
        if not command:
            QMessageBox.warning(self, '警告', '请输入要执行的命令')
            return

        # 添加到历史
        self._add_command_history(command)

        self.cmd_btn.setEnabled(False)

        self.command_worker = CommandWorker(self.ssh_manager, ip_list, command)
        self.command_worker.log.connect(self.log_message)

        def on_finished():
            self.cmd_btn.setEnabled(True)

        self.command_worker.finished.connect(on_finished)

        self.command_worker_thread = threading.Thread(target=self.command_worker.run, daemon=True)
        self.command_worker_thread.start()

    def on_deploy(self):
        """执行部署工作流：rsync同步 → 执行指令序列。

        参考 JSYNC-PUSH 脚本：先同步文件到所有已选设备，
        同步成功后再依次执行指令序列（killall/open/cp/ln等部署指令）。
        """
        ip_list = self.get_selected_ips()
        if not ip_list:
            QMessageBox.warning(self, '警告', '请先选择至少一台设备')
            return

        local_path = self.deploy_local_edit.text().strip()
        remote_path = self.deploy_remote_edit.text().strip()
        if not local_path or not remote_path:
            QMessageBox.warning(self, '警告', '请填写本地路径和远程路径')
            return

        if not os.path.exists(local_path):
            QMessageBox.warning(self, '警告', f'本地路径不存在: {local_path}')
            return

        # 解析指令序列（按行分割，去除空行和注释行）
        cmds_text = self.deploy_cmds_edit.toPlainText()
        commands = [
            line.strip() for line in cmds_text.split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]

        delete = self.deploy_delete_cb.isChecked()
        self.deploy_btn.setEnabled(False)

        self.deploy_worker = DeployWorker(
            self.rsync_manager, self.ssh_manager,
            ip_list, local_path, remote_path, delete, commands
        )
        self.deploy_worker.log.connect(self.log_message)

        def on_finished(results):
            self.deploy_btn.setEnabled(True)
            success = sum(1 for code, _ in results.values() if code == 0)
            self.log_message(f'部署完成: 同步成功 {success}/{len(results)} 台')

        self.deploy_worker.finished.connect(on_finished)

        self.deploy_worker_thread = threading.Thread(target=self.deploy_worker.run, daemon=True)
        self.deploy_worker_thread.start()

    def _add_command_history(self, command):
        """添加命令到历史列表。

        Args:
            command: 命令字符串
        """
        # 避免重复
        for i in range(self.cmd_history_list.count()):
            if self.cmd_history_list.item(i).text() == command:
                self.cmd_history_list.takeItem(i)
                break
        self.cmd_history_list.insertItem(0, command)
        # 最多保留30条
        while self.cmd_history_list.count() > 30:
            self.cmd_history_list.takeItem(self.cmd_history_list.count() - 1)

    def _use_history_command(self, item):
        """双击历史命令填充到输入框。

        Args:
            item: QListWidgetItem
        """
        self.cmd_edit.setText(item.text())
        self.cmd_edit.setFocus()

    def _show_cmd_history_menu(self, pos):
        """显示命令历史右键菜单。

        Args:
            pos: 右键位置
        """
        menu = QMenu()
        clear_action = menu.addAction("清空历史")

        item = self.cmd_history_list.itemAt(pos)
        if item:
            menu.addSeparator()
            delete_action = menu.addAction("删除")

        action = menu.exec(self.cmd_history_list.mapToGlobal(pos))

        if action == clear_action:
            self.cmd_history_list.clear()
        elif item and action == delete_action:
            self.cmd_history_list.takeItem(self.cmd_history_list.row(item))

    def get_widget(self):
        """返回插件的主窗口部件。"""
        return self

    def get_name(self):
        """返回插件名称。"""
        return f'Rsync-Sync {self.version}'

    def closeEvent(self, event):
        """关闭事件处理。"""
        # 保存当前界面路径到配置
        self.config.set('push_local_path', self.sync_local_edit.text().strip())
        self.config.set('push_remote_path', self.sync_remote_edit.text().strip())
        self.config.set('pull_remote_path', self.pull_remote_edit.text().strip())
        self.config.set('pull_local_path', self.pull_local_edit.text().strip())
        # 保存部署配置
        self.config.set('deploy_local_path', self.deploy_local_edit.text().strip())
        self.config.set('deploy_remote_path', self.deploy_remote_edit.text().strip())
        self.config.set('deploy_commands', self.deploy_cmds_edit.toPlainText())
        self.config.set('scan_range', self.scan_range_edit.text().strip())
        self.config.save()
        event.accept()
