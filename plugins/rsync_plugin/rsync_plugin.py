#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rsync文件同步插件 - 文件同步和获取工具

功能:
1. 扫描网络中可SSH连接的设备，使用uname显示远程系统信息
2. 点击VNC按钮远程连接对应IP
3. 配置界面: 配置IP、用户名、密码，选择设备
4. 多设备文件同步推送（rsync push）
5. 单设备指令发送（SSH交互式会话，保持指令连续性，与文件管理器共用同一连接）
6. 获取远程指定路径文件列表并拉取到本地（单设备操作）
"""

import re
import os
import sys
import json
import threading
from typing import Optional, Tuple, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, QGroupBox,
    QMessageBox, QSplitter, QTabWidget, QCheckBox, QHeaderView, QSizePolicy,
    QPlainTextEdit, QFileDialog, QComboBox, QListWidget, QListWidgetItem,
    QMenu, QProgressBar, QStackedWidget, QFrame, QRadioButton, QButtonGroup,
    QScrollArea
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QFontDatabase

# 添加插件目录到路径
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_manager import SSHManager, parse_ip_range, check_expect
from rsync_manager import RsyncManager
from vnc_manager import VNCManager
from config_dialog import RsyncConfig

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
    """指令发送工作线程 — 使用 InteractiveShell 保持指令连续性。

    每台设备创建一个交互式 SSH shell 会话（PTY），所有命令通过同一会话发送，
    因此 cd / export / source 等的效果会保留到后续命令。

    Signals:
        log: 日志信号 (message)
        finished: 完成信号
    """
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, ssh_manager, ip, command, shell_getter=None):
        """初始化命令发送工作线程。

        Args:
            ssh_manager: SSHManager实例（用于获取凭据）
            ip: 目标IP（单台）
            command: 要执行的命令字符串
            shell_getter: 获取已缓存的 InteractiveShell 的回调 (ip) -> InteractiveShell | None
                          如果返回 None，则内部创建新会话
        """
        super().__init__()
        self.ssh_manager = ssh_manager
        self.ip = ip
        self.command = command
        self._shell_getter = shell_getter

    def run(self):
        """执行命令发送（通过交互式 shell）。"""
        self.log.emit(f'[{self.ip}] > {self.command}')

        # 获取或创建交互式 shell
        shell = None
        if self._shell_getter:
            try:
                shell = self._shell_getter(self.ip)
            except Exception:
                shell = None

        if shell is None or not shell.is_alive:
            # 创建新的交互式会话
            try:
                from ssh_manager import InteractiveShell
                shell = InteractiveShell(
                    self.ssh_manager.username,
                    self.ssh_manager.password,
                    self.ip,
                    self.ssh_manager.port,
                )
                self.log.emit(f'[{self.ip}] SSH 会话已建立')
            except Exception as e:
                self.log.emit(f'[{self.ip}] SSH 连接失败: {e}')
                self.finished.emit()
                return

        # 通过交互式 shell 发送命令
        try:
            rc, stdout = shell.send_command(self.command, timeout=30)
            if rc == 0:
                self.log.emit(f'[{self.ip}] (rc={rc})\n{stdout}' if stdout.strip() else f'[{self.ip}] (rc={rc})')
            else:
                self.log.emit(f'[{self.ip}] 失败 (rc={rc}): {stdout or "(无输出)"}')
        except Exception as e:
            self.log.emit(f'[{self.ip}] 命令执行异常: {e}')

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

    完整三步流水线（多线程并发）：
      阶段1: 扫描 IP 范围（可选），获取在线设备列表 + 主机名筛选
      阶段2: rsync 推送本地文件到所有目标设备
      阶段3: 对推送成功的设备并发执行指令序列

    Signals:
        log: 日志信号 (message)
        progress: 进度信号 (current, total, phase)
        finished: 完成信号 (summary_dict)
    """
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)

    def __init__(self, rsync_manager, ssh_manager, script: dict,
                 scan_progress_callback=None):
        """初始化部署工作线程。

        Args:
            rsync_manager: RsyncManager实例
            ssh_manager: SSHManager实例
            script: 部署脚本字典，结构见 scripts/default_deploy.json
            scan_progress_callback: 扫描进度回调 (ip, available, uname, scanned, total)
        """
        super().__init__()
        self.rsync_manager = rsync_manager
        self.ssh_manager = ssh_manager
        self.script = script
        self._scan_progress_cb = scan_progress_callback
        self._cancelled = False

    def cancel(self):
        """请求取消部署（协作式，当前阶段完成后停止）。"""
        self._cancelled = True

    # ------------------------------------------------------------------
    # 阶段1: 确定目标 IP 列表
    # ------------------------------------------------------------------

    def _resolve_targets(self) -> list:
        """根据脚本 step1_targets 确定最终要操作的 IP 列表。"""
        step1 = self.script.get('step1_targets', {})
        mode = step1.get('mode', 'scan')

        if mode == 'manual':
            # 手动填入 IP（逗号/换行分隔）
            raw = step1.get('manual_ips', '')
            ips = [ip.strip() for ip in raw.replace('\n', ',').split(',') if ip.strip()]
            self.log.emit(f'阶段1: 手动指定 {len(ips)} 个 IP')
            return ips

        # scan 模式：解析 IP 范围 → 扫描 → 可选主机名筛选
        ip_range = step1.get('ip_range', '').strip()
        if not ip_range:
            self.log.emit('阶段1: IP 范围为空，无目标')
            return []

        ip_list = parse_ip_range(ip_range)
        if not ip_list:
            self.log.emit(f'阶段1: 无法解析 IP 范围: {ip_range}')
            return []

        hostname_filter = step1.get('hostname_filter', '').strip()
        self.log.emit(f'阶段1: 扫描 {len(ip_list)} 个 IP（范围: {ip_range}）'
                      + (f'，筛选主机名包含「{hostname_filter}」' if hostname_filter else ''))

        # 执行扫描
        def progress_cb(ip, available, uname_info, scanned, total):
            if self._scan_progress_cb:
                self._scan_progress_cb(ip, available, uname_info, scanned, total)
            self.progress.emit(scanned, total, '扫描')

        results = self.ssh_manager.scan_network(ip_list, max_workers=20, progress_callback=progress_cb)

        # results: {ip: {'available': bool, 'uname': str, 'hostname': str}}[{'ip': ip, 'uname': uname_info}]
        online_ips = []
        for item in results:
            ip = item["ip"]
            uname = item["uname"]
            if hostname_filter:
                index = uname.find(hostname_filter)
                if index != -1:
                    online_ips.append(ip)
                else:
                    pass
            else:
                online_ips.append(ip)
        self.log.emit(f'阶段1: 扫描完成，在线 {len(results)} 台，筛选后 {len(online_ips)} 台目标')
        return online_ips

    # ------------------------------------------------------------------
    # 阶段2: rsync 推送
    # ------------------------------------------------------------------

    def _push_files(self, ip_list: list) -> dict:
        """rsync 推送文件到目标设备列表，返回 {ip: (code, output)}。"""
        step2 = self.script.get('step2_push', {})
        local_path = step2.get('local_path', '').strip()
        remote_path = step2.get('remote_path', '').strip()
        delete = bool(step2.get('delete', False))

        if not local_path or not remote_path:
            self.log.emit('阶段2: 本地/远程路径为空，跳过推送')
            return {ip: (0, 'skipped') for ip in ip_list}

        if not os.path.exists(local_path):
            self.log.emit(f'阶段2: 本地路径不存在: {local_path}')
            return {ip: (-1, 'local path not found') for ip in ip_list}

        self.log.emit(f'阶段2: 推送文件 {local_path} → {remote_path}（{len(ip_list)} 台，delete={delete}）')

        def output_cb(ip, line):
            self.log.emit(f'[推送 {ip}] {line}')

        results = self.rsync_manager.push_to_multiple(
            ip_list, local_path, remote_path,
            delete=delete, output_callback=output_cb, max_workers=5
        )

        total_tasks = len(results)
        fully_success = sum(1 for code, _ in results.values() if code == 0)
        partial_success = sum(1 for code, _ in results.values() if code == 23)
        failed = total_tasks - fully_success - partial_success

        self.log.emit(f"完全成功: {fully_success}, 部分成功: {partial_success}, 失败: {failed} 一共{len(ip_list)} 台")
        return results

    # ------------------------------------------------------------------
    # 阶段3: 远程执行指令
    # ------------------------------------------------------------------

    def _exec_commands(self, ip_list: list) -> dict:
        """对所有目标设备并发执行指令序列，返回 {ip: all_ok}。"""
        commands = self.script.get('step3_commands', [])
        if not commands:
            self.log.emit('阶段3: 无指令，部署完成')
            return {ip: True for ip in ip_list}

        self.log.emit(f'阶段3: 执行 {len(commands)} 条指令 → {len(ip_list)} 台设备')
        results_lock = threading.Lock()
        cmd_results = {}
        done_count = [0]

        def exec_one(ip):
            all_ok = True
            for idx, cmd in enumerate(commands, 1):
                if self._cancelled:
                    break
                code, stdout, stderr = self.ssh_manager.execute_command(ip, cmd, timeout=60)
                if code == 0:
                    self.log.emit(f'[{ip}] ({idx}/{len(commands)}) OK: {cmd}')
                    if stdout and stdout.strip():
                        self.log.emit(f'[{ip}] {stdout.strip()}')
                else:
                    self.log.emit(f'[{ip}] ({idx}/{len(commands)}) 失败({code}): {cmd}')
                    if stderr:
                        self.log.emit(f'[{ip}] {stderr.strip()}')
                    all_ok = False
                    # break
            with results_lock:
                cmd_results[ip] = all_ok
                done_count[0] += 1
                self.progress.emit(done_count[0], len(ip_list), '执行指令')

        threads = []
        for ip in ip_list:
            t = threading.Thread(target=exec_one, args=(ip,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        success = sum(1 for ok in cmd_results.values() if ok)
        self.log.emit(f'阶段3: 指令执行完成 {success}/{len(ip_list)} 台')
        return cmd_results

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self):
        """执行完整部署流水线。"""
        script_name = self.script.get('name', '未命名')
        self.log.emit(f'========== 开始部署: {script_name} ==========')

        # 阶段1: 确定目标
        if self._cancelled:
            self.log.emit('部署已取消')
            self.finished.emit({'cancelled': True})
            return

        target_ips = self._resolve_targets()
        if not target_ips:
            self.log.emit('无目标设备，部署终止')
            self.finished.emit({'targets': 0})
            return

        # 阶段2: 推送文件
        if self._cancelled:
            self.log.emit('部署已取消（推送前）')
            self.finished.emit({'cancelled': True, 'targets': len(target_ips)})
            return

        sync_results = self._push_files(target_ips)
        ACCEPTABLE_CODES = {0, 23}
        success_ips = [ip for ip, (code, _) in sync_results.items() if code in ACCEPTABLE_CODES]

        # 阶段3: 执行指令（仅对推送成功的设备）
        if self._cancelled:
            self.log.emit('部署已取消（指令前）')
            self.finished.emit({'cancelled': True, 'targets': len(target_ips),
                                'pushed': len(success_ips)})
            return

        if success_ips:
            self._exec_commands(success_ips)
        else:
            self.log.emit('无设备推送成功，跳过指令执行')

        # 汇总
        summary = {
            'targets': len(target_ips),
            'pushed': len(success_ips),
            'cancelled': self._cancelled,
        }
        self.log.emit(f'========== 部署结束: 目标 {summary["targets"]} 台, 推送成功 {summary["pushed"]} 台 ==========')
        self.finished.emit(summary)


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

    # 后台线程SSH连接建立后，通知主线程刷新远程文件面板
    _remote_refresh_needed = pyqtSignal(str)
    # 后台线程日志转发到主线程写 GUI（避免非主线程操作 QPlainTextEdit 崩溃）
    _log_signal = pyqtSignal(str)

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

        # 指令面板：按设备缓存交互式 shell 会话（保持指令连续性）
        self._interactive_shells: Dict[str, object] = {}
        self._shells_lock = threading.Lock()

        # 尽早连接日志信号（在 _init_ui 之前），保证后台线程日志能安全转发到主线程
        self._log_signal.connect(self._append_log_text)
        self._init_ui()
        # 跨线程信号：后台SSH连接建立后通知主线程刷新远程面板
        self._remote_refresh_needed.connect(self._on_remote_refresh_needed)
        self._check_dependencies()

        # UI 初始化完成后（log_text 已创建）再加载部署脚本，避免写日志时报 log_text 不存在
        self._init_deploy_script()

    def _update_managers(self):
        """根据配置更新管理器实例。

        SSH 凭据严格从配置文件读取，不再使用代码兜底的 gdlocal 默认值，
        确保所有部署环境必须通过配置文件配置账号信息。
        """
        username, password, port = self.config.get_ssh_credentials()
        # 若配置为空则退回到模板默认值（config.default.json 中定义的默认账号）
        from config_dialog import get_default_config
        _fallback = get_default_config()
        username = username or _fallback['ssh']['username']
        password = password or _fallback['ssh']['password']
        port = port or _fallback['ssh']['port']
        self.ssh_manager = SSHManager(username, password, int(port))
        self.rsync_manager = RsyncManager(username, password, int(port))
        self.vnc_manager = VNCManager()

    def _update_managers_if_needed(self):
        """保证 ssh_manager / rsync_manager 已被初始化（懒加载时调用）。

        Returns:
            bool: 总是返回 True，方便工厂函数里 (self._update_managers_if_needed(), self.ssh_manager)[1] 这样使用。
        """
        if not hasattr(self, 'ssh_manager') or self.ssh_manager is None:
            self._update_managers()
        return True

    def _get_browser_target_ip(self) -> str:
        """返回文件管理器用于传输的目标 IP（仅允许单台）。

        策略：
        1) 文件管理器和指令面板只能单选一台：若被勾选多台，弹提示并自动取消其它勾选，保留第一台
        2) 用户已勾选设备 → 优先用户当前选择（最新的点击意图）
        3) 用户未勾选 → 回退到持久化的 paths.browser_target_ip（仅当它仍在设备表里）
        返回空字符串表示未选（此时 UI 会提示用户选设备）。
        """
        checked = self.get_selected_ips()
        if len(checked) > 1:
            # 互斥取消：保留第一台
            first_ip = checked[0]
            for r in range(self.device_table.rowCount()):
                w = self.device_table.cellWidget(r, 0)
                if not w:
                    continue
                cb = w.findChild(QCheckBox)
                if not cb:
                    continue
                ip_item = self.device_table.item(r, 1)
                row_ip = ip_item.text() if ip_item else ''
                if row_ip and row_ip != first_ip and cb.isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            self._update_selected_count()
            checked = [first_ip]

        # 用户已勾选 → 优先用户当前选择（不要再被持久化的旧 IP 覆盖）
        if checked:
            return checked[0]

        # 未勾选 → 回退到持久化的上次目标，仅当它仍存在于设备表里
        saved_ip = self.config.get('paths.browser_target_ip', '')
        if saved_ip:
            for r in range(self.device_table.rowCount()):
                ip_item = self.device_table.item(r, 1)
                if ip_item and ip_item.text() == saved_ip:
                    return saved_ip
        return ''

    def _on_device_check_changed(self):
        """设备勾选变化时：更新文件管理器目标 IP 显示，自动建立 SSH 连接并刷新远程列表。

        选中单台 IP 时，在后台线程建立交互式 SSH 会话（避免阻塞 UI），
        连接成功后通过信号通知主线程刷新远程文件面板。
        """
        try:
            self.file_browser  # type: ignore[has-type]
        except AttributeError:
            return
        ip = self._get_browser_target_ip()
        if not ip:
            if hasattr(self.file_browser, 'set_target_ip'):
                self.file_browser.set_target_ip('')
            return

        # 更新目标 IP 显示
        if hasattr(self.file_browser, 'set_target_ip'):
            self.file_browser.set_target_ip(ip)

        # 只在当前有且仅有1台被选时自动连接 SSH + 刷新远程面板
        if len(self.get_selected_ips()) != 1:
            return

        # 后台线程建立 SSH 连接（密码认证可能耗时数秒），完成后通知主线程刷新
        def _connect_and_notify(target_ip=ip):
            shell = self._get_or_create_shell(target_ip)
            if shell and shell.is_alive:
                self._remote_refresh_needed.emit(target_ip)
            else:
                self.log_message(f'[{target_ip}] SSH 连接失败，远程面板未刷新')

        threading.Thread(target=_connect_and_notify, daemon=True).start()

    def _on_remote_refresh_needed(self, ip: str):
        """主线程槽：后台SSH连接建立后，刷新远程文件面板。

        Args:
            ip: 已建立连接的目标 IP
        """
        try:
            self.file_browser.refresh_remote(ip)
        except Exception as e:
            self.log_message(f'刷新远程文件列表失败: {e}')

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

        布局策略：垂直结构，中间为「左配置区(4成) + 右设备表(6成)」的左右布局。
        模式切换行/操作面板/日志横跨全宽，配置区（扫描/筛选/SSH/进度条）上下排列。
        """
        # 应用紧凑字体到本插件
        self.setFont(QFont(self.font().family(), UI_FONT_SIZE))

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(UI_SPACING)
        main_layout.setContentsMargins(UI_MARGIN, UI_MARGIN, UI_MARGIN, UI_MARGIN)

        # ===== 1. 操作模式切换行 — 始终可见（即使部署界面也能切回来）=====
        mode_row = QHBoxLayout()
        mode_row.setSpacing(UI_SPACING)
        mode_row.setContentsMargins(0, 0, 0, 0)

        # 模式按钮（checkable，互斥）：0=调试模式 1=一键自动部署
        self.mode_btn_group = []
        for idx, text in enumerate(['调试模式', '一键自动部署']):
            btn = self._make_btn(text)
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

        mode_row.addStretch()

        self.selected_count_label = QLabel('已选 0 台')
        self.selected_count_label.setStyleSheet('color: #666; padding-right: 4px;')
        mode_row.addWidget(self.selected_count_label)
        main_layout.addLayout(mode_row)

        # ===== 2. 中间区域：左侧配置面板(4成) + 右侧设备表(6成) 左右布局 =====
        self.middle_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.middle_splitter.setChildrenCollapsible(False)

        # --- 左侧配置面板：扫描框 + 筛选框 + SSH配置 + 进度条（上下结构）---
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(UI_SPACING)
        left_layout.setContentsMargins(0, 0, UI_SPACING, 0)

        # 扫描配置框
        scan_row = QHBoxLayout()
        scan_row.setSpacing(UI_SPACING)
        scan_row.setContentsMargins(0, 0, 0, 0)
        scan_row.addWidget(QLabel('扫描:'))
        self.scan_range_edit = QLineEdit(self.config.get('scan.range', ''))
        self.scan_range_edit.setPlaceholderText('10.8.30.14-23 或 10.8.30.0/24')
        scan_row.addWidget(self.scan_range_edit, 1)

        self.scan_btn = self._make_btn('扫描')
        self.scan_btn.clicked.connect(self.on_scan)
        scan_row.addWidget(self.scan_btn)

        self.stop_scan_btn = self._make_btn('停止')
        self.stop_scan_btn.setEnabled(False)
        scan_row.addWidget(self.stop_scan_btn)
        left_layout.addLayout(scan_row)

        # 筛选框（主机名/IP 包含匹配）
        filter_row = QHBoxLayout()
        filter_row.setSpacing(UI_SPACING)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel('筛选:'))
        self.device_filter_edit = QLineEdit()
        self.device_filter_edit.setPlaceholderText('主机名或IP 包含的字符串，例: RD01 / 10.8.30.15')
        self.device_filter_edit.setText(self.config.get('ui.device_filter', ''))
        self.device_filter_edit.textChanged.connect(self._apply_device_filter)
        filter_row.addWidget(self.device_filter_edit, 1)

        self.filter_clear_btn = self._make_btn('清除')
        self.filter_clear_btn.clicked.connect(lambda: self.device_filter_edit.clear())
        filter_row.addWidget(self.filter_clear_btn)

        self.device_filter_hint = QLabel('共 0 台 | 显示 0 台')
        self.device_filter_hint.setStyleSheet('color: #888; padding-left: 6px;')
        filter_row.addWidget(self.device_filter_hint)
        left_layout.addLayout(filter_row)

        # SSH 连接配置（用户名/密码/端口，编辑完成后自动应用到传输管理器）
        ssh_row = QHBoxLayout()
        ssh_row.setSpacing(UI_SPACING)
        ssh_row.setContentsMargins(0, 0, 0, 0)
        ssh_row.addWidget(QLabel('SSH:'))
        ssh_row.addWidget(QLabel('用户'))
        self.ssh_username_edit = QLineEdit()
        self.ssh_username_edit.setPlaceholderText('用户名')
        ssh_row.addWidget(self.ssh_username_edit, 2)
        ssh_row.addWidget(QLabel('密码'))
        self.ssh_password_edit = QLineEdit()
        self.ssh_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_password_edit.setPlaceholderText('密码')
        ssh_row.addWidget(self.ssh_password_edit, 2)
        ssh_row.addWidget(QLabel('端口'))
        self.ssh_port_edit = QLineEdit()
        self.ssh_port_edit.setMaximumWidth(50)
        ssh_row.addWidget(self.ssh_port_edit)
        left_layout.addLayout(ssh_row)

        # 从配置填充初始 SSH 凭据
        _username, _password, _port = self.config.get_ssh_credentials()
        self.ssh_username_edit.setText(_username or '')
        self.ssh_password_edit.setText(_password or '')
        self.ssh_port_edit.setText(str(_port or 22))
        # 编辑完成后自动写回配置并重建传输管理器
        self.ssh_username_edit.editingFinished.connect(self._apply_ssh_from_ui)
        self.ssh_password_edit.editingFinished.connect(self._apply_ssh_from_ui)
        self.ssh_port_edit.editingFinished.connect(self._apply_ssh_from_ui)

        # 进度条（细条，扫描时显示）
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        # 剩余空间留白，配置项靠上排列
        left_layout.addStretch()

        # --- 右侧设备表（占 6 成）---
        self.device_table = QTableWidget(0, 4)
        self.device_table.setHorizontalHeaderLabels(['选', 'IP地址', '主机名', 'VNC'])
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setShowGrid(False)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # 列宽策略：选择/IP/VNC 自适应内容长度，主机名拉伸填充剩余
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        # 紧凑行高
        self.device_table.verticalHeader().setDefaultSectionSize(22)

        # 左右布局：左侧 4 成、右侧 6 成
        self.middle_splitter.addWidget(left_panel)
        self.middle_splitter.addWidget(self.device_table)
        self.middle_splitter.setStretchFactor(0, 4)
        self.middle_splitter.setStretchFactor(1, 6)
        self.middle_splitter.setSizes([400, 600])
        main_layout.addWidget(self.middle_splitter, 1)

        # ===== 5. 操作面板（QStackedWidget：0 调试模式 / 1 一键自动部署）=====
        self.ops_stack = QStackedWidget()
        self.ops_stack.setCurrentIndex(0)
        main_layout.addWidget(self.ops_stack, 3)

        # --- 0. 调试模式（文件管理器 + 指令面板 整合在一个页面）---
        debug_page = QWidget()
        debug_layout = QVBoxLayout(debug_page)
        debug_layout.setSpacing(2)
        debug_layout.setContentsMargins(0, 0, 0, 0)

        # 上半部分：FinalShell 风格双栏文件管理器（占主要空间）
        from file_browser_panel import FinalShellFileBrowser
        self.file_browser = FinalShellFileBrowser(
            ssh_manager_factory=lambda: (
                self._update_managers() if False else None,
                self.ssh_manager,
            )[1] if True else None,
            rsync_manager_factory=lambda: (self._update_managers() if False else None, self.rsync_manager)[1],
            target_ip_getter=self._get_browser_target_ip,
            initial_local_path=self.config.get('paths.browser_local_path', '') or os.path.expanduser('~'),
            initial_remote_path=self.config.get('paths.browser_remote_path', '') or '/',
            log_func=self.log_message,
            show_message_box=lambda t, m: QMessageBox.warning(self, t, m),
            shell_getter=self._get_or_create_shell,
            parent=self,
        )
        self.file_browser._ssh_factory = lambda: (self._update_managers_if_needed(), self.ssh_manager)[1]
        self.file_browser._rsync_factory = lambda: (self._update_managers_if_needed(), self.rsync_manager)[1]
        self.file_browser.cb_delete.setChecked(bool(self.config.get('browser.delete_sync', False)))

        # 下半部分：指令面板（命令行 + 历史列表 + 会话CWD显示）
        cmd_widget = QWidget()
        cmd_layout = QVBoxLayout(cmd_widget)
        cmd_layout.setSpacing(2)
        cmd_layout.setContentsMargins(0, 0, 0, 0)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(UI_SPACING)
        cmd_row.setContentsMargins(0, 0, 0, 0)
        cmd_row.addWidget(QLabel('命令:'))
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText('先 cd /tmp 再 ls — 目录会在当前设备上保持')
        self.cmd_edit.returnPressed.connect(self.on_send_command)
        cmd_row.addWidget(self.cmd_edit, 2)

        self.cmd_btn = self._make_btn('发送')
        self.cmd_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white;
                font-weight: bold; border-radius: 3px; }
            QPushButton:hover { background-color: #F57C00; }
            QPushButton:disabled { background-color: #aaa; }
        """)
        self.cmd_btn.clicked.connect(self.on_send_command)
        cmd_row.addWidget(self.cmd_btn)
        cmd_layout.addLayout(cmd_row)

        self.cmd_history_list = QListWidget()
        self.cmd_history_list.setMaximumHeight(60)
        self.cmd_history_list.itemDoubleClicked.connect(self._use_history_command)
        self.cmd_history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cmd_history_list.customContextMenuRequested.connect(self._show_cmd_history_menu)
        cmd_layout.addWidget(self.cmd_history_list)

        # 用垂直 QSplitter 把文件管理器和指令面板上下整合
        debug_splitter = QSplitter(Qt.Orientation.Vertical)
        debug_splitter.addWidget(self.file_browser)
        debug_splitter.addWidget(cmd_widget)
        debug_splitter.setStretchFactor(0, 4)   # 文件管理器占大头
        debug_splitter.setStretchFactor(1, 1)   # 指令面板紧凑
        debug_splitter.setSizes([400, 150])
        debug_layout.addWidget(debug_splitter)

        self.ops_stack.addWidget(debug_page)

        # --- 2. 部署面板（脚本加载/编写 → 三步流水线：扫描→推送→执行）---
        deploy_page = QWidget()
        deploy_layout = QVBoxLayout(deploy_page)
        deploy_layout.setSpacing(4)
        deploy_layout.setContentsMargins(0, 0, 0, 0)

        # 脚本工具栏：加载/保存/另存/新建 + 当前脚本名
        deploy_toolbar = QHBoxLayout()
        deploy_toolbar.setSpacing(4)
        deploy_toolbar.setContentsMargins(0, 0, 0, 0)
        deploy_toolbar.addWidget(QLabel('部署脚本:'))
        self.deploy_script_label = QLabel('（未加载）')
        script_font = QFont(self.deploy_script_label.font())
        script_font.setPointSize(script_font.pointSize() + 3)
        script_font.setBold(True)
        self.deploy_script_label.setFont(script_font)
        self.deploy_script_label.setStyleSheet('color: #0D47A1; padding: 4px 8px;')
        deploy_toolbar.addWidget(self.deploy_script_label, 2)

        btn_load = self._make_btn('加载')
        btn_load.clicked.connect(self._on_deploy_load_script)
        deploy_toolbar.addWidget(btn_load)

        btn_save = self._make_btn('保存')
        btn_save.clicked.connect(self._on_deploy_save_script)
        deploy_toolbar.addWidget(btn_save)

        btn_saveas = self._make_btn('另存为')
        btn_saveas.clicked.connect(self._on_deploy_saveas_script)
        deploy_toolbar.addWidget(btn_saveas)

        btn_new = self._make_btn('新建')
        btn_new.clicked.connect(self._on_deploy_new_script)
        deploy_toolbar.addWidget(btn_new)
        deploy_layout.addLayout(deploy_toolbar)

        # 用 ScrollArea 包裹，内容多时可滚动
        deploy_scroll = QScrollArea()
        deploy_scroll.setWidgetResizable(True)
        deploy_scroll.setFrameShape(QFrame.Shape.NoFrame)
        deploy_inner = QWidget()
        deploy_inner_layout = QVBoxLayout(deploy_inner)
        deploy_inner_layout.setSpacing(4)
        deploy_inner_layout.setContentsMargins(0, 0, 0, 0)

        # === 变量区 ===
        var_group = QGroupBox('变量（SSH 凭据）')
        var_layout = QFormLayout(var_group)
        var_layout.setSpacing(2)
        self.deploy_username_edit = QLineEdit()
        self.deploy_password_edit = QLineEdit()
        self.deploy_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.deploy_port_edit = QLineEdit()
        self.deploy_port_edit.setMaximumWidth(60)
        var_layout.addRow('用户名:', self.deploy_username_edit)
        var_layout.addRow('密码:', self.deploy_password_edit)
        var_layout.addRow('端口:', self.deploy_port_edit)
        deploy_inner_layout.addWidget(var_group)

        # === 步骤1: 目标设备 ===
        step1_group = QGroupBox('步骤1: 确定目标设备')
        step1_layout = QVBoxLayout(step1_group)
        step1_layout.setSpacing(2)

        # 模式选择
        mode_row = QHBoxLayout()
        self.deploy_rb_scan = QRadioButton('扫描 IP 范围')
        self.deploy_rb_manual = QRadioButton('手动填入 IP')
        self.deploy_target_mode = QButtonGroup(self)
        self.deploy_target_mode.addButton(self.deploy_rb_scan)
        self.deploy_target_mode.addButton(self.deploy_rb_manual)
        self.deploy_rb_scan.setChecked(True)
        mode_row.addWidget(self.deploy_rb_scan)
        mode_row.addWidget(self.deploy_rb_manual)
        mode_row.addStretch()
        step1_layout.addLayout(mode_row)

        # IP 范围
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel('IP 范围:'))
        self.deploy_ip_range_edit = QLineEdit()
        self.deploy_ip_range_edit.setPlaceholderText('10.8.30.14-23 或 10.8.30.0/24 或 10.8.30.14,10.8.30.20')
        range_row.addWidget(self.deploy_ip_range_edit, 2)
        step1_layout.addLayout(range_row)

        # 手动 IP
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel('手动 IP:'))
        self.deploy_manual_ips_edit = QLineEdit()
        self.deploy_manual_ips_edit.setPlaceholderText('10.8.30.14,10.8.30.15（逗号分隔）')
        manual_row.addWidget(self.deploy_manual_ips_edit, 2)
        step1_layout.addLayout(manual_row)

        # 主机名筛选
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('主机名筛选:'))
        self.deploy_hostname_filter_edit = QLineEdit()
        self.deploy_hostname_filter_edit.setPlaceholderText('留空=全部，填入字符串=主机名包含该字符串才部署')
        filter_row.addWidget(self.deploy_hostname_filter_edit, 2)
        step1_layout.addLayout(filter_row)
        deploy_inner_layout.addWidget(step1_group)

        # === 步骤2: 推送文件 ===
        step2_group = QGroupBox('步骤2: 推送文件到远程')
        step2_layout = QVBoxLayout(step2_group)
        step2_layout.setSpacing(2)

        push_row = QHBoxLayout()
        push_row.addWidget(QLabel('本地路径:'))
        self.deploy_local_edit = QLineEdit()
        self.deploy_local_edit.setPlaceholderText('本地源路径（文件或文件夹）')
        push_row.addWidget(self.deploy_local_edit, 2)
        deploy_local_btn = self._make_btn('…')
        deploy_local_btn.setMaximumWidth(24)
        deploy_local_btn.clicked.connect(lambda: self._browse_dir(self.deploy_local_edit))
        push_row.addWidget(deploy_local_btn)
        step2_layout.addLayout(push_row)

        remote_row = QHBoxLayout()
        remote_row.addWidget(QLabel('远程路径:'))
        self.deploy_remote_edit = QLineEdit()
        self.deploy_remote_edit.setPlaceholderText('远程目标路径')
        remote_row.addWidget(self.deploy_remote_edit, 2)
        self.deploy_delete_cb = QCheckBox('--delete')
        self.deploy_delete_cb.setToolTip('删除目标中源端没有的文件')
        remote_row.addWidget(self.deploy_delete_cb)
        step2_layout.addLayout(remote_row)
        deploy_inner_layout.addWidget(step2_group)

        # === 步骤3: 远程执行指令 ===
        step3_group = QGroupBox('步骤3: 远程执行指令（每行一条，# 开头为注释）')
        step3_layout = QVBoxLayout(step3_group)
        step3_layout.setSpacing(2)
        self.deploy_cmds_edit = QPlainTextEdit()
        self.deploy_cmds_edit.setPlaceholderText('killall shTool\nopen /vault/...\ncp -r ...\nln -s ...')
        self.deploy_cmds_edit.setFixedHeight(100)
        step3_layout.addWidget(self.deploy_cmds_edit)
        deploy_inner_layout.addWidget(step3_group)

        deploy_inner_layout.addStretch()
        deploy_scroll.setWidget(deploy_inner)
        deploy_layout.addWidget(deploy_scroll, 2)

        # 部署进度条
        self.deploy_progress = QProgressBar()
        self.deploy_progress.setVisible(False)
        deploy_layout.addWidget(self.deploy_progress)

        # 部署按钮
        deploy_btn_row = QHBoxLayout()
        deploy_btn_row.setSpacing(4)
        deploy_btn_row.addStretch()
        self.deploy_stop_btn = self._make_btn('停止')
        self.deploy_stop_btn.setEnabled(False)
        self.deploy_stop_btn.clicked.connect(self._on_deploy_stop)
        deploy_btn_row.addWidget(self.deploy_stop_btn)
        self.deploy_btn = self._make_btn('执行部署')
        deploy_btn_font = QFont(self.deploy_btn.font())
        deploy_btn_font.setPointSize(deploy_btn_font.pointSize() + 2)
        deploy_btn_font.setBold(True)
        self.deploy_btn.setFont(deploy_btn_font)
        self.deploy_btn.setMinimumHeight(int(UI_BTN_HEIGHT * 1.5))
        qss_path = os.path.join(PLUGIN_DIR, 'styles', 'deploy_btn.qss')
        self._bind_deploy_button_style(qss_path)
        self.deploy_btn.clicked.connect(self.on_deploy)
        deploy_btn_row.addWidget(self.deploy_btn)
        deploy_layout.addLayout(deploy_btn_row)

        self.ops_stack.addWidget(deploy_page)

        # 保存脚本路径的初始值，初始化延后到 __init__ 末尾（log_text 创建后）进行
        self._deploy_script_path = ''

        main_layout.addWidget(self.ops_stack, 2)

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
        # 等宽字体：macOS 优先 Menlo，跨平台回退 System Fixed / Courier New，
        # 避免硬写 "Courier New" 在 macOS 下触发 "SF Mono 缺字" 的性能警告
        mono_families = ['Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'DejaVu Sans Mono']
        chosen = None
        for family in mono_families:
            if family in QFontDatabase.families():
                chosen = family
                break
        if chosen:
            self.log_text.setFont(QFont(chosen, UI_FONT_SIZE))
        else:
            fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            if fixed_font is not None:
                fixed_font.setPointSize(UI_FONT_SIZE)
                self.log_text.setFont(fixed_font)
            else:
                self.log_text.setFont(QFont('Courier New', UI_FONT_SIZE))
        self.log_text.setFixedHeight(80)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(self.log_container)

        # ===== 7. 恢复UI持久化状态 =====
        self._restore_ui_state()
        # 命令历史加载
        self._restore_command_history()

    def _restore_ui_state(self):
        """从配置恢复UI持久化状态：上次操作模式。"""
        # 上次操作模式（无记录时默认启动直接进入一键自动部署 = 索引 1）
        _default_mode = 1  # 1 = 一键自动部署
        last_mode = int(self.config.get('ui.last_mode', _default_mode) or _default_mode)
        if 0 <= last_mode < len(self.mode_btn_group):
            self._on_mode_changed(last_mode)

    def _restore_command_history(self):
        """从配置恢复命令历史列表（最多 30 条）。"""
        history = self.config.get_command_history()
        for cmd in history:
            if cmd and isinstance(cmd, str):
                self.cmd_history_list.addItem(QListWidgetItem(cmd))

    def _snapshot_command_history(self):
        """将当前命令历史列表中的条目快照保存到配置。"""
        commands = [
            self.cmd_history_list.item(i).text()
            for i in range(self.cmd_history_list.count())
        ]
        self.config.set_command_history(commands)

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
        """切换操作模式（调试模式 / 一键自动部署）。

        Args:
            index: 模式索引 0=调试模式 1=一键自动部署
        """
        # 互斥选中
        for i, btn in enumerate(self.mode_btn_group):
            btn.setChecked(i == index)
        self.ops_stack.setCurrentIndex(index)

        # 显示策略：部署模式（index==1）下隐藏中间区域（扫描/筛选/SSH/设备表），
        # 部署面板自带目标设备选择与 IP 范围配置；调试模式（index==0）显示中间区域。
        is_deploy = (index == 1)
        if hasattr(self, 'middle_splitter'):
            self.middle_splitter.setVisible(not is_deploy)

    def _update_selected_count(self):
        """更新已选设备数量显示。

        显示两部分信息：
        - 可见行中的被选中数量（筛选语境下用户实际关注的）
        - 全表范围内被选中的数量
        """
        visible_selected = 0
        for row in self._iter_visible_rows():
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    visible_selected += 1
        total_selected = len(self.get_selected_ips())
        total_visible = sum(1 for _ in self._iter_visible_rows())
        if total_selected == visible_selected:
            self.selected_count_label.setText(f'已选 {visible_selected}/{total_visible} 台')
        else:
            self.selected_count_label.setText(
                f'已选 {visible_selected}/{total_visible} 台 (含筛选外共 {total_selected} 台)'
            )

    def log_message(self, message):
        """记录日志消息到界面。

        线程安全：后台线程调用时通过 Qt 信号转发到主线程写 GUI，
        避免非主线程直接操作 QPlainTextEdit 导致崩溃。
        初始化阶段容错：如果 log_text 还没被创建（_init_ui 执行中），降级到 print
        以避免 'RsyncPlugin object has no attribute log_text' 的加载期错误。

        Args:
            message: 日志消息字符串
        """
        # logger 本身线程安全，先落盘
        logger.info(message)
        if not hasattr(self, 'log_text') or self.log_text is None:
            # UI 尚未初始化完成，直接打印
            print(message, file=sys.stderr)
            return
        # 通过信号转发到主线程（跨线程自动 queued connection）
        self._log_signal.emit(message)

    def _append_log_text(self, message: str):
        """主线程槽：真正把日志写入 GUI 控件。

        此方法只会在主线程（事件循环）中执行，由 _log_signal 跨线程 queued 调用，
        因此可以安全操作 QPlainTextEdit。

        Args:
            message: 日志消息字符串
        """
        if hasattr(self, 'log_text') and self.log_text is not None:
            self.log_text.appendPlainText(message)
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_text.setTextCursor(cursor)
        else:
            print(message, file=sys.stderr)

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

    def _apply_ssh_from_ui(self):
        """把界面上 SSH 凭据写回配置并重建传输管理器。

        由 ssh_username_edit / ssh_password_edit / ssh_port_edit 的 editingFinished
        信号触发（主线程执行），端口非法时回退到 22。
        """
        self.config.set('ssh.username', self.ssh_username_edit.text().strip())
        self.config.set('ssh.password', self.ssh_password_edit.text())
        try:
            port = int(self.ssh_port_edit.text().strip() or 22)
        except ValueError:
            port = 22
        self.config.set('ssh.port', port)
        self.config.save()
        self._update_managers()
        self.log_message(
            f'SSH 凭据已更新: {self.ssh_username_edit.text().strip()}:{port}'
        )

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
        # 重新应用筛选（空表下刷新提示文字）并更新计数
        self._apply_device_filter()
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

        # 保存设备列表到配置
        devices = [{'ip': dev['ip'], 'uname': dev['uname']} for dev in results]
        self.config.set_devices(devices)

        # 单选模式：如果扫描到了至少一台，自动勾选第一台（保持即扫即用体验）
        if len(results) > 0:
            # 先把所有 cb 清空（清空后再勾第一台，避免触发互斥取消逻辑时信号被重复刷）
            for r in range(self.device_table.rowCount()):
                w = self.device_table.cellWidget(r, 0)
                if not w:
                    continue
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            first_widget = self.device_table.cellWidget(0, 0)
            if first_widget:
                first_cb = first_widget.findChild(QCheckBox)
                if first_cb:
                    # 直接 setChecked(...) 会触发互斥逻辑，互斥逻辑里会再 _update_selected_count，所以不用手动刷新
                    first_cb.setChecked(True)

    def _add_device_row(self, ip, uname):
        """向设备表添加一行设备记录。

        Args:
            ip: 设备IP地址
            uname: 系统信息
        """
        row = self.device_table.rowCount()
        self.device_table.insertRow(row)

        # 选择复选框（居中、无 margin；单选互斥：有新的被勾选就把其它取消）
        cb = QCheckBox()
        cb_widget = QWidget()
        cb_layout = QHBoxLayout(cb_widget)
        cb_layout.addWidget(cb)
        cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        self.device_table.setCellWidget(row, 0, cb_widget)

        def _on_single_check(state, me=cb):
            """单选互斥：当某台被勾选时，把设备表里其它所有行的 cb 取消掉。"""
            if state == 2:  # Qt.Checked == 2
                for r in range(self.device_table.rowCount()):
                    other_widget = self.device_table.cellWidget(r, 0)
                    if not other_widget:
                        continue
                    other_cb = other_widget.findChild(QCheckBox)
                    if other_cb and other_cb is not me:
                        other_cb.blockSignals(True)
                        other_cb.setChecked(False)
                        other_cb.blockSignals(False)
            self._update_selected_count()
            self._on_device_check_changed()
        cb.stateChanged.connect(_on_single_check)

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

        # 新增行后，重新应用当前筛选（让新增行按当前关键字显示/隐藏），并刷新计数
        self._apply_device_filter()

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
        index = uname_str.find("Darwin")
        if index != -1:
            uname_str = uname_str[index:]
        parts = uname_str.split()
        if len(parts) >= 2:
            return parts[1]
        return uname_str

    # ------------------------------------------------------------------
    # 设备筛选（主机名/IP 包含匹配，大小写不敏感）
    # ------------------------------------------------------------------

    def _apply_device_filter(self, keyword: Optional[str] = None):
        """根据关键字筛选设备表行（匹配 IP 或 主机名，大小写不敏感）。

        显示规则：
        - 空关键字：全部显示
        - 否则：IP 列 或 主机名列 文本包含关键字的行显示，其余隐藏
        每次过滤后刷新「显示/共 X 台」提示和已选计数。

        Args:
            keyword: 筛选关键字，None 时从 self.device_filter_edit 读取
        """
        if keyword is None:
            keyword = self.device_filter_edit.text()
        kw = keyword.strip().lower()

        total = self.device_table.rowCount()
        visible_count = 0
        for row in range(total):
            ip_item = self.device_table.item(row, 1)
            host_item = self.device_table.item(row, 2)
            ip_text = ip_item.text().lower() if ip_item else ''
            host_text = host_item.text().lower() if host_item else ''
            # 额外匹配 tooltip（完整 uname 信息）里的内容
            tip_text = host_item.toolTip().lower() if host_item else ''
            if (not kw
                    or kw in ip_text
                    or kw in host_text
                    or kw in tip_text):
                self.device_table.setRowHidden(row, False)
                visible_count += 1
            else:
                self.device_table.setRowHidden(row, True)

        self.device_filter_hint.setText(f'共 {total} 台 | 显示 {visible_count} 台')
        self._update_selected_count()

    def _iter_visible_rows(self):
        """遍历设备表所有未隐藏的行号。

        Yields:
            int: 行号
        """
        for row in range(self.device_table.rowCount()):
            if not self.device_table.isRowHidden(row):
                yield row

    # ------------------------------------------------------------------

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
        """全选设备（仅选中筛选后的可见行）。"""
        for row in self._iter_visible_rows():
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and not cb.isChecked():
                    cb.setChecked(True)
        self._update_selected_count()

    def deselect_all_devices(self):
        """取消全选设备（仅取消筛选后的可见行）。"""
        for row in self._iter_visible_rows():
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    cb.setChecked(False)
        self._update_selected_count()

    def get_selected_ips(self):
        """获取已选中的设备IP列表。

        注：对隐藏行也进行返回，避免用户之前筛选选中后取消筛选导致
        某些操作丢失目标；通常用户会在筛选视图里操作，所以同时
        收集可见+隐藏里被选中的 IP，重复自动去重。

        Returns:
            list: 已选中的IP地址列表（去重，按表格出现顺序）
        """
        selected = []
        seen = set()
        for row in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    ip_item = self.device_table.item(row, 1)
                    if ip_item:
                        ip = ip_item.text()
                        if ip not in seen:
                            seen.add(ip)
                            selected.append(ip)
        return selected

    def on_sync_push(self):
        """已由文件管理器面板替代。

        此按钮/方法仅保留为兼容占位：推送/拉取旧 UI 已被文件管理器 + 部署面板替代，
        如果通过异常路径被调用，给出提示而不是炸 AttributeError。
        """
        QMessageBox.information(self, '提示', '旧的推送面板已被双栏文件管理器替代，请切换到「文件管理器」Tab，拖拽即可上传/下载；批量部署请使用「部署」Tab。')

    def on_list_files(self):
        """已由文件管理器替代。（占位，避免对不存在控件的访问。）"""
        QMessageBox.information(self, '提示', '请切换到「文件管理器」Tab，右侧直接浏览远程目录。')

    def on_pull_files(self):
        """已由文件管理器替代。（占位，避免对不存在控件的访问。）"""
        QMessageBox.information(self, '提示', '请切换到「文件管理器」Tab，把右侧的远程文件/文件夹拖到左侧即可下载。')

    def _get_or_create_shell(self, ip: str):
        """获取或创建指定 IP 的交互式 shell（线程安全）。

        shell 会话按 IP 缓存，保证文件管理器和指令面板共用同一个 SSH 连接，
        从而 cd / export / source 等命令的效果在两侧持续生效。

        Args:
            ip: 目标设备 IP

        Returns:
            InteractiveShell: 已建立连接的 shell 实例；连接失败返回 None
        """
        # 1) 先查缓存（快速路径）
        with self._shells_lock:
            shell = self._interactive_shells.get(ip)
            if shell and shell.is_alive:
                return shell
        # 2) 缓存未命中或已断开 → 新建（在锁外创建，避免长时间持锁）
        try:
            from ssh_manager import InteractiveShell
            self._update_managers_if_needed()
            shell = InteractiveShell(
                self.ssh_manager.username,
                self.ssh_manager.password,
                ip,
                self.ssh_manager.port,
            )
        except Exception as e:
            self.log_message(f'[{ip}] SSH 会话建立失败: {e}')
            return None
        # 3) 写回缓存（双重检查，避免并发重复创建）
        with self._shells_lock:
            existing = self._interactive_shells.get(ip)
            if existing and existing.is_alive:
                shell.close()
                return existing
            self._interactive_shells[ip] = shell
        self.log_message(f'[{ip}] SSH 会话已建立')
        return shell

    def _close_all_shells(self):
        """关闭所有缓存的交互式 shell 会话（关闭插件/切换设备时调用）。"""
        with self._shells_lock:
            shells = list(self._interactive_shells.values())
            self._interactive_shells.clear()
        for shell in shells:
            try:
                shell.close()
            except Exception:
                pass

    def on_send_command(self):
        """向已选设备发送命令（通过交互式 shell，保持指令连续性）。

        指令面板为「单台设备」操作：选 0 台提示选设备，选 >1 台提示请只勾一台。
        cd / export / source 等命令的效果会保留到后续命令（shell 是持续的）。
        """
        ip_list = self.get_selected_ips()
        if not ip_list:
            QMessageBox.warning(self, '警告', '请先选择一台设备（指令面板仅支持单台操作）')
            return
        if len(ip_list) > 1:
            QMessageBox.warning(self, '警告', '指令面板仅支持单台操作，请先取消其它勾选')
            return

        command = self.cmd_edit.text().strip()
        if not command:
            QMessageBox.warning(self, '警告', '请输入要执行的命令')
            return

        # 添加到历史
        self._add_command_history(command)
        # 清空输入框，方便连续发命令
        self.cmd_edit.clear()

        self.cmd_btn.setEnabled(False)
        # 保证在用户点了按钮之后，最新的 ssh_manager/rsync_manager 凭据已被应用
        self._update_managers_if_needed()

        ip = ip_list[0]
        self.command_worker = CommandWorker(
            self.ssh_manager, ip, command,
            shell_getter=self._get_or_create_shell,
        )
        self.command_worker.log.connect(self.log_message)

        def on_finished():
            self.cmd_btn.setEnabled(True)

        self.command_worker.finished.connect(on_finished)

        self.command_worker_thread = threading.Thread(target=self.command_worker.run, daemon=True)
        self.command_worker_thread.start()

    # ------------------------------------------------------------------
    # 部署脚本管理
    # ------------------------------------------------------------------

    _DEPLOY_SCRIPTS_DIR = os.path.join(PLUGIN_DIR, 'scripts')
    _DEPLOY_DEFAULT_SCRIPT = os.path.join(PLUGIN_DIR, 'scripts', 'default_deploy.json')

    def _init_deploy_script(self):
        """初始化部署面板：加载上次使用的脚本或默认脚本。

        文件不存在时静默跳过（首次使用，UI 保持空表单），
        避免插件加载阶段打印"加载部署脚本失败"错误日志。
        """
        last_path = self.config.get('paths.deploy_script_path', '')
        if last_path and os.path.isfile(last_path):
            self._load_deploy_script_file(last_path)
        elif os.path.isfile(self._DEPLOY_DEFAULT_SCRIPT):
            self._load_deploy_script_file(self._DEPLOY_DEFAULT_SCRIPT)
        else:
            # 默认脚本不存在（首次使用），保持空表单，不报错
            self._deploy_script_path = self._DEPLOY_DEFAULT_SCRIPT

    def _collect_deploy_script(self) -> dict:
        """从 UI 表单收集当前部署脚本字典。"""
        commands_text = self.deploy_cmds_edit.toPlainText()
        commands = [
            line.strip() for line in commands_text.split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]
        return {
            'name': os.path.splitext(os.path.basename(self._deploy_script_path or '未命名'))[0],
            'ssh': {
                'username': self.deploy_username_edit.text().strip(),
                'password': self.deploy_password_edit.text().strip(),
                'port': int(self.deploy_port_edit.text().strip() or '22'),
            },
            'step1_targets': {
                'mode': 'manual' if self.deploy_rb_manual.isChecked() else 'scan',
                'ip_range': self.deploy_ip_range_edit.text().strip(),
                'manual_ips': self.deploy_manual_ips_edit.text().strip(),
                'hostname_filter': self.deploy_hostname_filter_edit.text().strip(),
            },
            'step2_push': {
                'local_path': self.deploy_local_edit.text().strip(),
                'remote_path': self.deploy_remote_edit.text().strip(),
                'delete': self.deploy_delete_cb.isChecked(),
            },
            'step3_commands': commands,
        }

    def _apply_deploy_script(self, script: dict):
        """将脚本字典填充到 UI 表单。"""
        ssh = script.get('ssh', {})
        self.deploy_username_edit.setText(ssh.get('username', ''))
        self.deploy_password_edit.setText(ssh.get('password', ''))
        self.deploy_port_edit.setText(str(ssh.get('port', 22)))

        step1 = script.get('step1_targets', {})
        if step1.get('mode') == 'manual':
            self.deploy_rb_manual.setChecked(True)
        else:
            self.deploy_rb_scan.setChecked(True)
        self.deploy_ip_range_edit.setText(step1.get('ip_range', ''))
        self.deploy_manual_ips_edit.setText(step1.get('manual_ips', ''))
        self.deploy_hostname_filter_edit.setText(step1.get('hostname_filter', ''))

        step2 = script.get('step2_push', {})
        self.deploy_local_edit.setText(step2.get('local_path', ''))
        self.deploy_remote_edit.setText(step2.get('remote_path', ''))
        self.deploy_delete_cb.setChecked(bool(step2.get('delete', False)))

        commands = script.get('step3_commands', [])
        self.deploy_cmds_edit.setPlainText('\n'.join(commands))

    def _load_deploy_script_file(self, path: str):
        """从 JSON 文件加载部署脚本到 UI。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                script = json.load(f)
            self._deploy_script_path = path
            name = script.get('name', os.path.basename(path))
            self.deploy_script_label.setText(name)
            self._apply_deploy_script(script)
            self.log_message(f'已加载部署脚本: {name} ({path})')
        except Exception as e:
            self.log_message(f'加载部署脚本失败: {e}')

    def _on_deploy_load_script(self):
        """打开文件对话框加载部署脚本。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '加载部署脚本',
            self._DEPLOY_SCRIPTS_DIR,
            '部署脚本 (*.json);;所有文件 (*)'
        )
        if path:
            self._load_deploy_script_file(path)

    def _on_deploy_save_script(self):
        """保存当前脚本（若未指定路径则走另存为）。"""
        if not self._deploy_script_path or not os.path.isfile(self._deploy_script_path):
            self._on_deploy_saveas_script()
            return
        self._save_deploy_script_file(self._deploy_script_path)

    def _on_deploy_saveas_script(self):
        """另存为新的脚本文件。"""
        default_name = self.deploy_script_label.text() + '.json'
        default_path = os.path.join(self._DEPLOY_SCRIPTS_DIR, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, '另存为部署脚本',
            default_path,
            '部署脚本 (*.json);;所有文件 (*)'
        )
        if path:
            if not path.endswith('.json'):
                path += '.json'
            self._save_deploy_script_file(path)

    def _save_deploy_script_file(self, path: str):
        """将当前 UI 表单保存为 JSON 脚本文件。"""
        script = self._collect_deploy_script()
        script['name'] = os.path.splitext(os.path.basename(path))[0]
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            self._deploy_script_path = path
            self.deploy_script_label.setText(script['name'])
            self.log_message(f'部署脚本已保存: {path}')
        except Exception as e:
            QMessageBox.warning(self, '保存失败', str(e))

    def _on_deploy_new_script(self):
        """新建空白部署脚本。"""
        self._deploy_script_path = ''
        self.deploy_script_label.setText('（新建）')
        self.deploy_username_edit.clear()
        self.deploy_password_edit.clear()
        self.deploy_port_edit.setText('22')
        self.deploy_rb_scan.setChecked(True)
        self.deploy_ip_range_edit.clear()
        self.deploy_manual_ips_edit.clear()
        self.deploy_hostname_filter_edit.clear()
        self.deploy_local_edit.clear()
        self.deploy_remote_edit.clear()
        self.deploy_delete_cb.setChecked(False)
        self.deploy_cmds_edit.clear()
        self.log_message('已新建空白部署脚本')

    def _on_deploy_stop(self):
        """请求停止当前部署任务。"""
        if hasattr(self, 'deploy_worker') and self.deploy_worker:
            self.deploy_worker.cancel()
            self.log_message('正在停止部署（将在当前阶段完成后终止）…')

    # ------------------------------------------------------------------
    # 部署执行
    # ------------------------------------------------------------------

    def on_deploy(self):
        """执行部署：从 UI 收集脚本 → 构造 DeployWorker → 后台运行三步流水线。"""
        script = self._collect_deploy_script()

        # 基本校验
        step1 = script.get('step1_targets', {})
        if step1.get('mode') == 'scan' and not step1.get('ip_range', '').strip():
            QMessageBox.warning(self, '警告', '步骤1: 请填写 IP 范围，或切换到手动填入模式')
            return
        if step1.get('mode') == 'manual' and not step1.get('manual_ips', '').strip():
            QMessageBox.warning(self, '警告', '步骤1: 请填写手动 IP 列表，或切换到扫描模式')
            return

        step2 = script.get('step2_push', {})
        if not step2.get('local_path', '').strip() or not step2.get('remote_path', '').strip():
            reply = QMessageBox.question(
                self, '确认',
                '步骤2: 本地/远程路径为空，将跳过文件推送，仅执行指令。继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        elif not os.path.exists(step2['local_path'].strip()):
            QMessageBox.warning(self, '警告', f'本地路径不存在: {step2["local_path"]}')
            return

        # 用脚本中的 SSH 凭据创建专属 manager（不影响主界面的 manager）
        ssh_cfg = script.get('ssh', {})
        username = ssh_cfg.get('username', '').strip()
        password = ssh_cfg.get('password', '').strip()
        port = int(ssh_cfg.get('port', 22) or 22)
        if not username or not password:
            QMessageBox.warning(self, '警告', '变量区: 请填写用户名和密码')
            return

        try:
            from ssh_manager import SSHManager
            from rsync_manager import RsyncManager
            deploy_ssh = SSHManager(username, password, port)
            deploy_rsync = RsyncManager(username, password, port)
        except Exception as e:
            QMessageBox.warning(self, '错误', f'创建部署管理器失败: {e}')
            return

        self.deploy_btn.setEnabled(False)
        self.deploy_stop_btn.setEnabled(True)
        self.deploy_progress.setVisible(True)
        self.deploy_progress.setValue(0)

        self.deploy_worker = DeployWorker(deploy_rsync, deploy_ssh, script)

        def on_log(msg):
            self.log_message(msg)

        def on_progress(current, total, phase):
            if total > 0:
                self.deploy_progress.setMaximum(total)
                self.deploy_progress.setValue(current)
                self.deploy_progress.setFormat(f'{phase}: {current}/{total}')

        def on_finished(summary):
            self.deploy_btn.setEnabled(True)
            self.deploy_stop_btn.setEnabled(False)
            self.deploy_progress.setVisible(False)
            targets = summary.get('targets', 0)
            pushed = summary.get('pushed', 0)
            cancelled = summary.get('cancelled', False)
            if cancelled:
                self.log_message(f'部署已停止: 目标 {targets} 台, 推送 {pushed} 台')
            else:
                self.log_message(f'部署完成: 目标 {targets} 台, 推送成功 {pushed} 台')

        self.deploy_worker.log.connect(on_log)
        self.deploy_worker.progress.connect(on_progress)
        self.deploy_worker.finished.connect(on_finished)

        self.deploy_worker_thread = threading.Thread(target=self.deploy_worker.run, daemon=True)
        self.deploy_worker_thread.start()

    def _add_command_history(self, command):
        """添加命令到历史列表，并立即持久化到配置文件。

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
        # 立即持久化
        self._snapshot_command_history()

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
        """关闭事件处理：保存所有用户配置和UI状态到配置文件。

        确保插件目录连同 config.json 一起分发时，下一次打开即完整恢复：
        扫描范围、文件管理器路径/目标IP/--delete勾选、命令历史、模式、日志折叠状态、
        部署脚本路径（脚本内容本身保存在 scripts/*.json 中）。
        """
        # 关闭所有缓存的交互式 SSH 会话
        self._close_all_shells()

        # 部署脚本路径（脚本内容在 scripts/ 目录里独立保存，config 只记路径）
        self.config.set('paths.deploy_script_path', self._deploy_script_path or '')

        # 文件管理器双栏路径 + 目标IP
        self.config.set('paths.browser_local_path',
                        self.file_browser.tb_local.current_path() if hasattr(self, 'file_browser') else '')
        self.config.set('paths.browser_remote_path',
                        self.file_browser.tb_remote.current_path() if hasattr(self, 'file_browser') else '')
        self.config.set('paths.browser_target_ip', self._get_browser_target_ip())

        # 扫描范围
        self.config.set('scan.range', self.scan_range_edit.text().strip())

        # SSH 凭据（直接从界面控件读取，防止编辑后未失焦就关闭导致丢失）
        self.config.set('ssh.username', self.ssh_username_edit.text().strip())
        self.config.set('ssh.password', self.ssh_password_edit.text())
        try:
            self.config.set('ssh.port', int(self.ssh_port_edit.text().strip() or 22))
        except ValueError:
            self.config.set('ssh.port', 22)

        # 文件管理器 --delete 勾选
        if hasattr(self, 'file_browser'):
            self.config.set('browser.delete_sync', bool(self.file_browser.cb_delete.isChecked()))
            self.config.set('sync.push_delete', bool(self.file_browser.cb_delete.isChecked()))
            self.config.set('sync.pull_delete', bool(self.file_browser.cb_delete.isChecked()))

        # 命令历史快照
        self._snapshot_command_history()

        # UI状态
        self.config.set('ui.last_mode', int(self.ops_stack.currentIndex()))
        self.config.set('ui.device_filter', self.device_filter_edit.text().strip())

        # 持久化写入
        self.config.save()
        event.accept()
