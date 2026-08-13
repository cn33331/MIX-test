#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
文件管理器面板（FinalShell 风格双栏）

结构：
  左侧：本地文件浏览器（使用 QFileSystemModel，显示名称/大小/类型/修改时间/权限）
  中间：方向箭头按钮区（→ 上传 / ← 下载 / 刷新 / 删除 / 新建文件夹等）
  右侧：远程文件浏览器（通过 SSH/rsync 列出文件，同样表格展示）

拖拽交互：
  * 从 Finder/Windows 资源管理器拖文件/文件夹 进「远程面板」→ 上传到远程当前目录
  * 从远程面板拖到「本地面板」→ 下载到本地当前目录
  * 面板内部双击文件夹切换路径，双击非目录文件（可选项）执行打开/下载
  * 两个面板都支持本地系统拖入（本地面板拖入=移动/复制到本地当前路径）

单通道串行传输：
  所有 rsync 任务通过 TransferQueueManager 串行排队，同一时间只允许一个传输任务运行。
"""

import os
import threading
import datetime
import queue
from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QFrame,
    QLineEdit, QPushButton, QLabel, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QAbstractItemView, QMenu,
    QStyledItemDelegate, QToolButton, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import (
    Qt, QMimeData, QObject, pyqtSignal, QModelIndex, QUrl
)
from PyQt6.QtGui import QDrag, QAction, QIcon, QFont, QFileSystemModel


# ---------------------------------------------------------------------------
# 数据结构：文件条目
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    """通用文件条目（本地/远程共用）。"""
    name: str
    path: str            # 完整路径（本地绝对路径 或 服务器绝对路径）
    is_dir: bool
    size: int = 0        # 字节
    mtime: str = ''      # 修改时间字符串
    perms: str = ''      # 权限，例 drwxr-xr-x
    owner: str = ''      # 所有者 例 root:root
    raw: dict = field(default_factory=dict)  # 原始解析结果

    @staticmethod
    def format_size(n: int) -> str:
        """格式化字节为人类可读字符串。"""
        step = 1024.0
        for unit in ['B', 'K', 'M', 'G', 'T', 'P']:
            if n < step:
                return f'{n:.1f}{unit}' if unit != 'B' else f'{int(n)}{unit}'
            n /= step
        return f'{n:.1f}E'


# ---------------------------------------------------------------------------
# 单通道串行传输管理器（线程安全）
# ---------------------------------------------------------------------------

@dataclass
class TransferTask:
    """一个传输任务。"""
    direction: str               # 'upload' 或 'download'
    target_ip: str
    source_paths: list           # 源文件/夹路径列表
    dest_dir: str                # 目标目录（本地绝对路径或服务器绝对路径）
    delete: bool = False
    on_log: Optional[Callable[[str], None]] = None
    on_done: Optional[Callable[[bool, str], None]] = None   # (ok, message)


class TransferQueueManager(QObject):
    """单通道传输队列管理器。

    保证同时只有一个 rsync 传输在运行；新任务先入队，按提交顺序串行执行。
    任务本身不依赖 QThread 事件循环，通过独立 worker 线程消费队列。

    Signals:
        queue_changed: (running_count, pending_count) 队列状态变化
    """

    queue_changed = pyqtSignal(int, int)

    def __init__(self, rsync_manager_factory: Callable, log_func: Optional[Callable[[str], None]] = None):
        """初始化传输管理器。

        Args:
            rsync_manager_factory: 可调用，返回一个可用的 RsyncManager 实例
                （设备凭据可能变，不能缓存，故每次调用再拿新的）
            log_func: 全局日志函数，任务运行时用于输出通用信息
        """
        super().__init__()
        self._rsync_factory = rsync_manager_factory
        self._log = log_func or (lambda _m: None)
        self._queue: 'queue.Queue[TransferTask]' = queue.Queue()
        self._pending_count = 0
        self._running = False
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

    def submit(self, task: TransferTask) -> None:
        """提交一个传输任务。"""
        with self._lock:
            self._pending_count += 1
            self._queue.put(task)
            self.queue_changed.emit(1 if self._running else 0, self._pending_count)
            self._log(f'[传输队列] 入队: {task.direction} → {task.target_ip} {task.dest_dir} (待执行 {self._pending_count})')
            if not self._running:
                self._start_worker()

    def _start_worker(self):
        """启动队列消费线程（仅在空闲时调用）。"""
        self._running = True
        self._worker_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._worker_thread.start()

    def _consume_loop(self):
        """持续消费队列，直到队列为空后退出。"""
        while True:
            with self._lock:
                if self._queue.empty():
                    self._running = False
                    self.queue_changed.emit(0, 0)
                    return
                task = self._queue.get()
                self._pending_count -= 1
                self.queue_changed.emit(1, self._pending_count)
            # 执行单任务
            ok, msg = self._run_one(task)
            try:
                if task.on_done:
                    task.on_done(ok, msg)
            except Exception as e:
                self._log(f'[传输队列] done回调异常: {e}')

    # -- 执行 --

    def _run_one(self, task: TransferTask) -> tuple[bool, str]:
        """执行单条传输任务。

        Returns:
            (是否成功, 说明文本)
        """
        def _log(msg: str):
            self._log(msg)
            if task.on_log:
                try:
                    task.on_log(msg)
                except Exception:
                    pass

        rsync = self._rsync_factory()
        try:
            if task.direction == 'upload':
                _log(f'[上传] → {task.target_ip}  目标: {task.dest_dir}')
                return self._run_upload_manual(rsync, task, _log)

            elif task.direction == 'download':
                _log(f'[下载] ← {task.target_ip}  保存: {task.dest_dir}')
                return self._run_download_manual(rsync, task, _log)

            else:
                return False, f'未知 direction={task.direction}'
        except Exception as e:
            msg = f'传输异常: {e}'
            _log(f'[错误] {msg}')
            return False, msg

    def _run_upload_manual(self, rsync, task: TransferTask, log_fn) -> tuple[bool, str]:
        """多文件/夹上传：依次 rsync push 每个源到目标设备的目标目录。"""
        ok_count = 0
        for src in task.source_paths:
            if not os.path.exists(src):
                log_fn(f'[上传跳过] 源不存在: {src}')
                continue
            log_fn(f'[上传] {src}  →  {task.target_ip}:{task.dest_dir}')
            code, _ = rsync.push_to_device(
                task.target_ip, src, task.dest_dir,
                delete=task.delete,
                output_callback=lambda line, s=src: log_fn(f'[{s}] {line}'),
            )
            if code == 0:
                ok_count += 1
                log_fn(f'[上传完成] {src}')
            else:
                log_fn(f'[上传失败] {src} (code={code})')
        total = len([s for s in task.source_paths if os.path.exists(s)])
        ok = ok_count == total and total > 0
        msg = f'上传完成 {ok_count}/{total}'
        log_fn(f'[结果] {msg}')
        return ok, msg

    def _run_download_manual(self, rsync, task: TransferTask, log_fn) -> tuple[bool, str]:
        """多文件/夹下载：依次 rsync pull 每个远程源到本地目录。"""
        os.makedirs(task.dest_dir, exist_ok=True)
        ok_count = 0
        for src in task.source_paths:
            log_fn(f'[下载] {task.target_ip}:{src}  →  {task.dest_dir}')
            code, _ = rsync.pull_from_device(
                task.target_ip, src, task.dest_dir,
                delete=task.delete,
                output_callback=lambda line, s=src: log_fn(f'[{s}] {line}'),
            )
            if code == 0:
                ok_count += 1
                log_fn(f'[下载完成] {src}')
            else:
                log_fn(f'[下载失败] {src} (code={code})')
        total = len(task.source_paths)
        ok = ok_count == total and total > 0
        msg = f'下载完成 {ok_count}/{total}'
        log_fn(f'[结果] {msg}')
        return ok, msg


# ---------------------------------------------------------------------------
# 通用文件表格组件（本地/远程共用 UI 框架）
# ---------------------------------------------------------------------------

class BaseFileTable(QTableWidget):
    """支持拖拽进出的文件表格基类。

    子类实现：
      - refresh(path)
      - list_children(path) -> list[FileEntry]
      - resolve_path_name(row) -> full_path
    Signals 通过外部 callback 注入（避免太多自定义信号）。
    """

    # 用于外部区分：'local' / 'remote'
    SIDE = 'base'

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(['名称', '大小', '类型', '修改时间', '权限/所有者'])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setFont(QFont(self.font().family(), 11))

        # 允许拖拽
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.current_path: str = ''
        self._entries: list[FileEntry] = []

        # 回调（外部设置）
        self.on_double_click_dir: Optional[Callable[[FileEntry], None]] = None
        self.on_double_click_file: Optional[Callable[[FileEntry], None]] = None
        self.on_request_upload: Optional[Callable[[list[str]], None]] = None   # 本地文件拖到远程面板触发
        self.on_request_download: Optional[Callable[[list[str]], None]] = None  # 远程选中文件拖出
        self.on_files_dropped_local: Optional[Callable[[list[str]], None]] = None  # Finder 拖入本地面板

        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # -- 子类实现 --

    def refresh(self):
        """刷新当前目录。子类重写。"""
        pass

    def list_children(self, directory: str) -> list[FileEntry]:
        """列出 directory 下所有条目。子类重写。"""
        return []

    # -- 填充/访问 --

    def set_entries(self, entries: list[FileEntry]):
        """用新的条目列表填充表格，保留父目录条目在首位（如有）。"""
        self.setRowCount(0)
        self._entries = list(entries)
        # 排序：目录在前、文件在后；同类型按名称字母序
        self._entries.sort(key=lambda e: (0 if e.is_dir else 1, e.name.lower()))
        for e in self._entries:
            self._append_row(e)

    def _append_row(self, e: FileEntry):
        row = self.rowCount()
        self.insertRow(row)
        name_item = QTableWidgetItem(e.name)
        name_item.setData(Qt.ItemDataRole.UserRole, e)
        # 文件夹使用特殊提示
        if e.is_dir:
            name_item.setToolTip(f'目录: {e.path}\n双击进入')
        else:
            name_item.setToolTip(f'{e.path}\n{e.size} 字节')
        self.setItem(row, 0, name_item)

        self.setItem(row, 1, QTableWidgetItem('-' if e.is_dir else FileEntry.format_size(e.size)))
        self.setItem(row, 2, QTableWidgetItem('文件夹' if e.is_dir else self._guess_file_type(e.name)))
        self.setItem(row, 3, QTableWidgetItem(e.mtime or '-'))
        perm_owner = e.perms + (' ' + e.owner if e.owner else '')
        self.setItem(row, 4, QTableWidgetItem(perm_owner or '-'))

    @staticmethod
    def _guess_file_type(name: str) -> str:
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        type_map = {
            'app': '应用',
            'py': 'Python脚本',
            'sh': 'Shell脚本',
            'log': '日志',
            'json': 'JSON',
            'zip': '压缩包',
            'tar': '压缩包', 'gz': '压缩包', 'bz2': '压缩包',
            'txt': '文本',
            'csv': 'CSV',
            'pdf': 'PDF',
            'png': '图片', 'jpg': '图片', 'jpeg': '图片', 'gif': '图片',
            'dmg': '磁盘镜像',
            'mp4': '视频', 'mov': '视频',
        }
        return type_map.get(ext, f'{ext.upper()}文件' if ext else '文件')

    def selected_entries(self) -> list[FileEntry]:
        """当前选中的条目列表。"""
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        result = []
        for r in rows:
            item = self.item(r, 0)
            if item:
                entry = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(entry, FileEntry):
                    result.append(entry)
        return result

    def _on_double_clicked(self, item: QTableWidgetItem):
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(entry, FileEntry):
            return
        if entry.is_dir:
            if self.on_double_click_dir:
                self.on_double_click_dir(entry)
        elif self.on_double_click_file:
            self.on_double_click_file(entry)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        act_refresh = QAction('刷新(F5)', self)
        act_refresh.triggered.connect(self.refresh)
        menu.addAction(act_refresh)
        menu.exec(self.viewport().mapToGlobal(pos))

    # -- 拖出：给系统/其他面板提供 file:// URLs --

    def startDrag(self, supportedActions):  # noqa: N802（Qt 标准函数名）
        """拖出：生成 QMimeData 里带 file:// URL 列表。"""
        entries = self.selected_entries()
        if not entries:
            return
        drag = QDrag(self)
        md = QMimeData()
        urls = []
        for e in entries:
            if e.path.startswith('/'):
                urls.append(QUrl.fromLocalFile(e.path))
        # 远程条目没有本地 file://，用自定义 mime 标记传递
        if not urls:
            # 自定义 MIME：application/x-rsync-remote-files
            remote_paths = [e.path for e in entries if e.path]
            if remote_paths:
                md.setData('application/x-rsync-remote-files',
                           '\n'.join(remote_paths).encode('utf-8'))
                # 额外附带 side 信息
                md.setData('application/x-rsync-side', self.SIDE.encode('utf-8'))
        else:
            md.setUrls(urls)
            md.setData('application/x-rsync-side', self.SIDE.encode('utf-8'))
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)

    # -- 拖入 --

    def dragEnterEvent(self, event):  # noqa: N802
        md = event.mimeData()
        # 本地文件路径
        if md.hasUrls() and all(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()
            return
        # 自定义远程路径
        if md.hasFormat('application/x-rsync-remote-files'):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        md = event.mimeData()
        if md.hasUrls() or md.hasFormat('application/x-rsync-remote-files'):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        md = event.mimeData()
        # 1) 系统本地文件拖入
        if md.hasUrls():
            local_paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile() and u.toLocalFile()]
            local_paths = [p for p in local_paths if p]
            if local_paths:
                self._handle_local_paths_dropped(local_paths)
                event.acceptProposedAction()
                return
        # 2) 自定义远程路径拖入（从另一面板拖来）
        if md.hasFormat('application/x-rsync-remote-files'):
            raw = md.data('application/x-rsync-remote-files')
            remote_paths = raw.data().decode('utf-8').split('\n') if hasattr(raw, 'data') else bytes(raw).decode('utf-8').split('\n')
            remote_paths = [p for p in remote_paths if p]
            if remote_paths:
                self._handle_remote_paths_dropped(remote_paths)
                event.acceptProposedAction()
                return
        event.ignore()

    def _handle_local_paths_dropped(self, local_paths: list[str]):
        """默认不做；子类覆盖实现上传或本地复制。"""
        if self.SIDE == 'remote':
            if self.on_request_upload:
                self.on_request_upload(local_paths)
        elif self.SIDE == 'local':
            if self.on_files_dropped_local:
                self.on_files_dropped_local(local_paths)

    def _handle_remote_paths_dropped(self, remote_paths: list[str]):
        """默认不做；远程面板覆盖此方法或使用 on_request_download。"""
        if self.SIDE == 'local':
            if self.on_request_download:
                self.on_request_download(remote_paths)


# ---------------------------------------------------------------------------
# 本地面板（使用 QFileSystemModel 取信息，展示到 BaseFileTable 里）
# ---------------------------------------------------------------------------

class LocalFileTable(BaseFileTable):
    SIDE = 'local'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fs_model: Optional[QFileSystemModel] = None  # 延后创建

    def _ensure_fs_model(self):
        if self._fs_model is None:
            self._fs_model = QFileSystemModel(self)
            self._fs_model.setRootPath('/')

    def list_children(self, directory: str) -> list[FileEntry]:
        self._ensure_fs_model()
        entries: list[FileEntry] = []
        directory = os.path.abspath(directory or '/')
        try:
            names = sorted(os.listdir(directory))
        except (PermissionError, FileNotFoundError, OSError):
            names = []
        # 父目录按钮
        if directory != '/':
            parent = os.path.dirname(directory) or '/'
            entries.append(FileEntry(name='..', path=parent, is_dir=True, mtime=''))
        for name in names:
            full = os.path.join(directory, name)
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            is_dir = os.path.isdir(full)
            try:
                import pwd, grp
                uid_name = pwd.getpwuid(st.st_uid).pw_name if hasattr(pwd, 'getpwuid') else str(st.st_uid)
                grp_name = grp.getgrgid(st.st_gid).gr_name if hasattr(grp, 'getgrgid') else str(st.st_gid)
                owner = f'{uid_name}:{grp_name}'
            except Exception:
                owner = f'{st.st_uid}:{st.st_gid}'
            perms = self._fmt_mode(st.st_mode, is_dir)
            mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')
            entries.append(FileEntry(
                name=name, path=full, is_dir=is_dir,
                size=0 if is_dir else st.st_size,
                mtime=mtime, perms=perms, owner=owner,
            ))
        return entries

    def refresh(self):
        if not self.current_path:
            self.current_path = os.path.expanduser('~')
        self.current_path = os.path.abspath(self.current_path)
        entries = self.list_children(self.current_path)
        self.set_entries(entries)

    @staticmethod
    def _fmt_mode(mode: int, is_dir: bool) -> str:
        """将 st_mode 转成 ls 风格权限字符串，例 drwxr-xr-x。"""
        import stat
        chars = ['d' if is_dir else ('l' if stat.S_ISLNK(mode) else '-')]
        for who in ('USR', 'GRP', 'OTH'):
            for perm in ('R', 'W', 'X'):
                bit = getattr(stat, f'S_I{perm}{who}')
                chars.append(perm.lower() if mode & bit else '-')
        return ''.join(chars)


# ---------------------------------------------------------------------------
# 远程面板（通过 SSHManager 执行 ls -la 获取）
# ---------------------------------------------------------------------------

class RemoteFileTable(BaseFileTable):
    SIDE = 'remote'

    def __init__(self, ssh_manager_factory: Callable, target_ip_getter: Callable[[], str],
                 log_func: Optional[Callable[[str], None]] = None,
                 shell_getter: Optional[Callable[[str], object]] = None,
                 parent=None):
        """初始化远程文件表格。

        Args:
            ssh_manager_factory: 每次执行返回可用 SSHManager
            target_ip_getter: 无参可调用，返回当前目标IP（可能为空字符串）
            log_func: 日志回调
            shell_getter: 可选，(ip) -> InteractiveShell | None；
                          传入时优先使用交互式 shell（与指令面板共用同一 SSH 会话）
        """
        super().__init__(parent)
        self._ssh_factory = ssh_manager_factory
        self._get_ip = target_ip_getter
        self._log = log_func or (lambda _m: None)
        self._shell_getter = shell_getter

    def _exec_remote(self, ip: str, cmd: str, timeout: int = 30) -> tuple:
        """执行远程命令，优先使用交互式 shell（与指令面板共用会话）。

        Args:
            ip: 目标 IP
            cmd: 要执行的命令
            timeout: 超时秒数

        Returns:
            tuple: (rc, stdout, stderr) — shell 模式下 stderr 为空字符串
        """
        if self._shell_getter:
            try:
                shell = self._shell_getter(ip)
            except Exception:
                shell = None
            if shell and shell.is_alive:
                rc, out = shell.send_command(cmd, timeout=timeout)
                return rc, out, ''
        # 回退到独立 SSH 进程
        ssh = self._ssh_factory()
        return ssh.execute_command(ip, cmd, timeout=timeout)

    def list_children(self, directory: str) -> list[FileEntry]:
        ip = self._get_ip()
        if not ip:
            return [FileEntry(name='（未选择设备，请在上方设备列表勾选）',
                              path='', is_dir=False)]
        # 使用 ls -laEn（macOS）格式：权限 链接数 所有者 组 大小 月 日 时/年 名称
        # GNU ls 使用 --time-style=long-iso，两者都可由通用解析器处理
        cmd = f"ls -laEn '{directory}' 2>/dev/null || ls -la --time-style=long-iso '{directory}' 2>/dev/null"
        code, out, err = self._exec_remote(ip, cmd, timeout=30)
        entries: list[FileEntry] = []
        if code != 0:
            msg = (err or out or f'exit {code}').strip().splitlines()
            line = msg[0] if msg else f'无法访问 {directory}'
            entries.append(FileEntry(name=f'（错误: {line[:50]}）', path='', is_dir=False))
            return entries

        # 父目录快捷条目（对应 '..'），若不在根目录
        if directory != '/':
            parent = '/' if directory.rstrip('/') == '' else os.path.dirname(directory.rstrip('/')) or '/'
            entries.append(FileEntry(name='..', path=parent, is_dir=True))
        # 解析每行
        for raw_line in out.splitlines():
            if not raw_line or raw_line.startswith('total '):
                continue
            entry = self._parse_ls_line(raw_line, directory)
            if entry and entry.name not in ('.', '..'):
                entries.append(entry)
        return entries

    def refresh(self):
        if not self.current_path:
            self.current_path = '/'
        entries = self.list_children(self.current_path)
        self.set_entries(entries)

    @staticmethod
    def _parse_ls_line(line: str, parent_dir: str) -> Optional[FileEntry]:
        """解析 ls -la 的一行输出。

        兼容两种格式：
          * BSD/macOS 短格式：权限 nlink owner group size Mon DD HH:MM name
          * GNU long-iso：权限 nlink owner group size YYYY-MM-DD HH:MM name
        """
        if not line or line.startswith('total '):
            return None
        # 先宽松地按空格分词（不限制 maxsplit），再根据日期字段特征拼接
        raw_tokens = line.split()
        if len(raw_tokens) < 8:
            return None
        perms, nlink, owner, group, size = raw_tokens[0], raw_tokens[1], raw_tokens[2], raw_tokens[3], raw_tokens[4]
        is_dir = perms.startswith('d')
        perms = perms[:10]
        try:
            int_size = int(size)
        except ValueError:
            int_size = 0
        # 从 tokens[5] 开始：有 '-' → GNU long-iso（日期+时间，占 2 位，再接name 至少 8 段）
        #             否则 → BSD（月 日 时间 占 3 位，至少 9 段）
        def _rest_from(i):
            return ' '.join(raw_tokens[i:])
        if '-' in raw_tokens[5]:
            # GNU: tokens[5]=YYYY-MM-DD, tokens[6]=HH:MM, tokens[7:]=name
            if len(raw_tokens) < 8:
                return None
            mtime_str = f'{raw_tokens[5]} {raw_tokens[6]}'
            name = _rest_from(7)
        else:
            # BSD: tokens[5]=Mon, tokens[6]=DD, tokens[7]=HH:MM or YYYY, tokens[8:]=name
            if len(raw_tokens) < 9:
                return None
            mtime_str = f'{raw_tokens[5]} {raw_tokens[6]} {raw_tokens[7]}'
            name = _rest_from(8)
        if not name:
            return None
        # 符号链接处理 "a -> target"
        pure_name = name.split(' -> ', 1)[0]
        full = parent_dir.rstrip('/') + '/' + pure_name
        return FileEntry(
            name=pure_name,
            path=full,
            is_dir=is_dir,
            size=int_size if not is_dir else 0,
            mtime=mtime_str[:19],
            perms=perms,
            owner=f'{owner}:{group}',
        )


# ---------------------------------------------------------------------------
# 工具栏（面包屑 + 常用操作）
# ---------------------------------------------------------------------------

class FileBrowserToolbar(QWidget):
    """单栏顶部工具条：面包屑路径 + 后退/前进/上一级/刷新/新建文件夹 等。"""

    path_changed = pyqtSignal(str)    # 用户主动改变路径时发出
    action_requested = pyqtSignal(str)  # 'back'/'forward'/'up'/'refresh'/'new_folder'/'delete'/'mkdir_home'

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setSpacing(2)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setMinimumWidth(48)
        self.title_label.setStyleSheet('font-weight:bold; padding-right:4px;')
        lay.addWidget(self.title_label)

        # 导航按钮
        self.btn_back = self._make_tbtn('◁')
        self.btn_back.clicked.connect(lambda: self.action_requested.emit('back'))
        lay.addWidget(self.btn_back)
        self.btn_forward = self._make_tbtn('▷')
        self.btn_forward.clicked.connect(lambda: self.action_requested.emit('forward'))
        lay.addWidget(self.btn_forward)
        self.btn_up = self._make_tbtn('▴')
        self.btn_up.setToolTip('上级目录')
        self.btn_up.clicked.connect(lambda: self.action_requested.emit('up'))
        lay.addWidget(self.btn_up)
        self.btn_refresh = self._make_tbtn('⟳')
        self.btn_refresh.setToolTip('刷新')
        self.btn_refresh.clicked.connect(lambda: self.action_requested.emit('refresh'))
        lay.addWidget(self.btn_refresh)

        # 路径输入条
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('路径（回车跳转）')
        self.path_edit.returnPressed.connect(self._emit_path_changed)
        lay.addWidget(self.path_edit, 1)

        # 右侧：操作
        self.btn_home = self._make_tbtn('🏠')
        self.btn_home.setToolTip('主目录')
        self.btn_home.clicked.connect(lambda: self.action_requested.emit('home'))
        lay.addWidget(self.btn_home)
        self.btn_newdir = self._make_tbtn('📁+')
        self.btn_newdir.setToolTip('新建文件夹')
        self.btn_newdir.clicked.connect(lambda: self.action_requested.emit('new_folder'))
        lay.addWidget(self.btn_newdir)
        self.btn_delete = self._make_tbtn('🗑')
        self.btn_delete.setToolTip('删除选中')
        self.btn_delete.clicked.connect(lambda: self.action_requested.emit('delete'))
        lay.addWidget(self.btn_delete)

        # 状态
        self._path_stack_back: list[str] = []
        self._path_stack_forward: list[str] = []
        self._current_path: str = ''

    @staticmethod
    def _make_tbtn(text: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setFixedHeight(24)
        return b

    def current_path(self) -> str:
        return self._current_path

    def set_path(self, path: str, add_history: bool = True):
        """设置当前路径，可选压入返回历史。"""
        if path == self._current_path:
            self.path_edit.setText(path)
            return
        if add_history and self._current_path:
            self._path_stack_back.append(self._current_path)
            self._path_stack_forward.clear()
        self._current_path = path
        self.path_edit.setText(path)
        self.btn_back.setEnabled(bool(self._path_stack_back))
        self.btn_forward.setEnabled(bool(self._path_stack_forward))
        self.path_changed.emit(path)

    def go_back(self) -> Optional[str]:
        if not self._path_stack_back:
            return None
        if self._current_path:
            self._path_stack_forward.append(self._current_path)
        prev = self._path_stack_back.pop()
        self._current_path = prev
        self.path_edit.setText(prev)
        self.btn_back.setEnabled(bool(self._path_stack_back))
        self.btn_forward.setEnabled(bool(self._path_stack_forward))
        return prev

    def go_forward(self) -> Optional[str]:
        if not self._path_stack_forward:
            return None
        if self._current_path:
            self._path_stack_back.append(self._current_path)
        nxt = self._path_stack_forward.pop()
        self._current_path = nxt
        self.path_edit.setText(nxt)
        self.btn_back.setEnabled(bool(self._path_stack_back))
        self.btn_forward.setEnabled(bool(self._path_stack_forward))
        return nxt

    def _emit_path_changed(self):
        p = self.path_edit.text().strip()
        if not p:
            return
        self.set_path(p, add_history=True)
        # 外部应连接 path_changed 信号做刷新；这里把 UI 文本同步一次


# ---------------------------------------------------------------------------
# 组合面板：FinalShell 风格 双栏文件管理器
# ---------------------------------------------------------------------------

class FinalShellFileBrowser(QWidget):
    """双栏文件浏览器：本地 | 中间箭头 | 远程。

    负责：
      * 组装 LocalFileTable + RemoteFileTable + 各工具条
      * 绑定双击导航、工具栏前进/后退/上一级/刷新/新建/删除
      * 拖拽事件→调用 TransferQueueManager 提交任务（单通道串行）
      * 对外暴露：on_* 信号式回调接口（方便主插件对接日志/消息框等）
    """

    def __init__(
        self,
        ssh_manager_factory: Callable,
        rsync_manager_factory: Callable,
        target_ip_getter: Callable[[], str],
        initial_local_path: str = '',
        initial_remote_path: str = '/',
        log_func: Optional[Callable[[str], None]] = None,
        show_message_box: Optional[Callable[[str, str], None]] = None,  # (title, msg)
        ask_text_input: Optional[Callable[[str, str], Optional[str]]] = None,  # (title, prompt) -> text or None
        shell_getter: Optional[Callable[[str], object]] = None,
        parent=None,
    ):
        """初始化双栏文件浏览器。

        Args:
            ssh_manager_factory: 返回可用 SSHManager
            rsync_manager_factory: 返回可用 RsyncManager
            target_ip_getter: 返回当前目标 IP（空表示未选）
            initial_local_path: 本地初始路径
            initial_remote_path: 远程初始路径
            log_func: 日志回调
            show_message_box: 弹窗回调（告警/提示）
            ask_text_input: 弹窗输入框回调（新建文件夹等）
            shell_getter: 可选，(ip) -> InteractiveShell | None；
                          传入时远程操作优先使用交互式 shell（与指令面板共用同一 SSH 会话）
        """
        super().__init__(parent)
        self._ssh_factory = ssh_manager_factory
        self._rsync_factory = rsync_manager_factory
        self._get_ip = target_ip_getter
        self._log = log_func or (lambda _m: None)
        self._msg = show_message_box
        self._ask = ask_text_input
        self._shell_getter = shell_getter

        # 单通道传输队列
        self.transfer_mgr = TransferQueueManager(rsync_manager_factory, log_func)

        # UI
        root = QVBoxLayout(self)
        root.setSpacing(2)
        root.setContentsMargins(0, 0, 0, 0)

        # 顶部：远程目标设备 & 传输队列状态
        top = QHBoxLayout()
        top.setSpacing(4)
        top.setContentsMargins(0, 0, 0, 0)
        self.lbl_ip = QLabel('目标设备: (未选择)')
        self.lbl_ip.setStyleSheet('padding-right: 12px;')
        top.addWidget(self.lbl_ip)

        self.lbl_queue = QLabel('传输: 空闲')
        self.lbl_queue.setStyleSheet('color:#666;')
        top.addWidget(self.lbl_queue)

        self.cb_delete = QCheckBox('传输时删除目标中源端没有的文件 (--delete)')
        top.addWidget(self.cb_delete)

        top.addStretch()
        root.addLayout(top)

        # 主体：本地 | 中间箭头栏 | 远程
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 左：本地
        left_pane = QFrame()
        left_lay = QVBoxLayout(left_pane)
        left_lay.setSpacing(2)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self.tb_local = FileBrowserToolbar('本地')
        left_lay.addWidget(self.tb_local)
        self.tbl_local = LocalFileTable(self)
        left_lay.addWidget(self.tbl_local, 1)
        splitter.addWidget(left_pane)

        # 中间：传输箭头 & 删除同步
        mid_pane = QFrame()
        mid_lay = QVBoxLayout(mid_pane)
        mid_lay.setSpacing(4)
        mid_lay.setContentsMargins(2, 20, 2, 20)
        mid_lay.addStretch()
        self.btn_upload = QPushButton('上传 →')
        self.btn_upload.setToolTip('把本地选中的文件/夹 上传到 远程当前目录')
        self.btn_upload.setStyleSheet(
            'QPushButton{background:#4CAF50;color:white;padding:10px 4px;border-radius:3px;font-weight:bold;}'
            'QPushButton:hover{background:#45a049;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_upload.clicked.connect(self._upload_selected)
        mid_lay.addWidget(self.btn_upload)

        self.btn_download = QPushButton('← 下载')
        self.btn_download.setToolTip('把远程选中的文件/夹 下载到 本地当前目录')
        self.btn_download.setStyleSheet(
            'QPushButton{background:#2196F3;color:white;padding:10px 4px;border-radius:3px;font-weight:bold;}'
            'QPushButton:hover{background:#1976D2;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_download.clicked.connect(self._download_selected)
        mid_lay.addWidget(self.btn_download)
        mid_lay.addStretch()
        mid_pane.setMaximumWidth(90)
        splitter.addWidget(mid_pane)

        # 右：远程
        right_pane = QFrame()
        right_lay = QVBoxLayout(right_pane)
        right_lay.setSpacing(2)
        right_lay.setContentsMargins(0, 0, 0, 0)
        self.tb_remote = FileBrowserToolbar('远程')
        right_lay.addWidget(self.tb_remote)
        self.tbl_remote = RemoteFileTable(ssh_manager_factory, target_ip_getter, log_func,
                                          shell_getter=self._shell_getter, parent=self)
        right_lay.addWidget(self.tbl_remote, 1)
        splitter.addWidget(right_pane)

        splitter.setSizes([400, 90, 480])
        root.addWidget(splitter, 1)

        # ---------- 绑定交互 ----------
        # 本地
        self.tb_local.path_changed.connect(self._local_goto)
        self.tb_local.action_requested.connect(self._on_local_action)
        self.tbl_local.on_double_click_dir = lambda e: self.tb_local.set_path(e.path, add_history=True)
        self.tbl_local.on_request_download = self._download_paths   # 远程拖到本地面板
        # Finder 拖到本地面板：做本地复制（用 rsync 也可以，但这里简单做 cp 避免再开子进程）
        self.tbl_local.on_files_dropped_local = self._copy_dropped_local_to_current

        # 远程
        self.tb_remote.path_changed.connect(self._remote_goto)
        self.tb_remote.action_requested.connect(self._on_remote_action)
        self.tbl_remote.on_double_click_dir = lambda e: self.tb_remote.set_path(e.path, add_history=True)
        self.tbl_remote.on_request_upload = self._upload_paths   # Finder 拖到远程面板

        # 队列状态变化
        self.transfer_mgr.queue_changed.connect(self._on_queue_changed)

        # 初始路径（blockSignals 阻止 set_path emit path_changed，
        # 否则 _remote_goto → tbl_remote.refresh() → SSH 连接会在插件加载时发起，
        # 导致 UI 卡顿和"SSH 会话建立失败"日志）
        init_local = initial_local_path or os.path.expanduser('~')
        self.tb_local.blockSignals(True)
        self.tb_local.set_path(init_local, add_history=False)
        self.tb_local.blockSignals(False)
        self._local_goto(init_local)

        init_remote = initial_remote_path or '/'
        self.tb_remote.blockSignals(True)
        self.tb_remote.set_path(init_remote, add_history=False)
        self.tb_remote.blockSignals(False)
        # 不主动刷新远程面板，等用户选中设备后 refresh_remote 显式调用

    # -- 外部 API：刷新 / 更新 IP --

    def set_target_ip(self, ip: str):
        """更新当前目标 IP 显示。"""
        ip = ip or ''
        self.lbl_ip.setText(f'目标设备: {ip}' if ip else '目标设备: (未选择)')

    def refresh_local(self):
        """刷新本地视图。"""
        p = self.tb_local.current_path() or os.path.expanduser('~')
        self._local_goto(p)

    def refresh_remote(self, force_ip: Optional[str] = None):
        """刷新远程视图。未选 IP 时表格会显示占位文字。"""
        ip = force_ip or self._get_ip()
        self.set_target_ip(ip)
        p = self.tb_remote.current_path() or '/'
        self._remote_goto(p)

    # -- 工具条动作 --

    def _on_local_action(self, act: str):
        tb = self.tb_local
        tbl = self.tbl_local
        if act == 'back':
            p = tb.go_back()
            if p is not None:
                self._local_goto(p, via_hist=True)
        elif act == 'forward':
            p = tb.go_forward()
            if p is not None:
                self._local_goto(p, via_hist=True)
        elif act == 'up':
            parent = os.path.dirname(tb.current_path() or '/')
            if parent == tb.current_path():
                return
            if not parent:
                parent = '/'
            tb.set_path(parent, add_history=True)
            self._local_goto(parent)
        elif act == 'refresh':
            self.refresh_local()
        elif act == 'home':
            tb.set_path(os.path.expanduser('~'), add_history=True)
            self._local_goto(os.path.expanduser('~'))
        elif act == 'new_folder':
            name = (self._ask or self._default_ask)('新建文件夹', '名称:')
            if name:
                self._local_mkdir(name)
        elif act == 'delete':
            self._local_delete_selected()

    def _on_remote_action(self, act: str):
        tb = self.tb_remote
        if act == 'back':
            p = tb.go_back()
            if p is not None:
                self._remote_goto(p, via_hist=True)
        elif act == 'forward':
            p = tb.go_forward()
            if p is not None:
                self._remote_goto(p, via_hist=True)
        elif act == 'up':
            parent = '/' if tb.current_path().rstrip('/') == '' else os.path.dirname(tb.current_path().rstrip('/')) or '/'
            if parent == tb.current_path():
                return
            tb.set_path(parent, add_history=True)
            self._remote_goto(parent)
        elif act == 'refresh':
            self.refresh_remote()
        elif act == 'home':
            # 回到用户配置中 push_remote_path（通常是用户 home 或 /vault/ZJX_backup），取家目录：
            tb.set_path(os.path.expanduser('~'), add_history=True)
            # 但远程家目录是用户登录后的 ~，这里 '/' 更稳妥，让用户自己选：
            # 折中：使用 "~ gdlocal" 风格展开由用户在路径栏输入。
            self._remote_goto(tb.current_path())
        elif act == 'new_folder':
            name = (self._ask or self._default_ask)('新建远程文件夹', '名称:')
            if name:
                self._remote_mkdir(name)
        elif act == 'delete':
            self._remote_delete_selected()

    def _default_ask(self, title, prompt) -> Optional[str]:
        text, ok = _qt_input_dialog(title, prompt)
        return text if ok else None

    # -- 跳转 --

    def _local_goto(self, path: str, via_hist: bool = False):
        path = os.path.abspath(path or '~')
        if not via_hist and path != self.tb_local.current_path():
            self.tb_local.set_path(path, add_history=False)
        self.tbl_local.current_path = path
        self.tbl_local.refresh()

    def _remote_goto(self, path: str, via_hist: bool = False):
        if not via_hist and path != self.tb_remote.current_path():
            self.tb_remote.set_path(path, add_history=False)
        self.tbl_remote.current_path = path
        self.tbl_remote.refresh()

    # -- 本地操作 --

    def _local_mkdir(self, name: str):
        parent = self.tb_local.current_path() or os.path.expanduser('~')
        target = os.path.join(parent, name.strip('/'))
        try:
            os.makedirs(target, exist_ok=False)
        except FileExistsError:
            self._show_warn('错误', f'文件夹已存在: {target}')
        except Exception as e:
            self._show_warn('创建失败', str(e))
        else:
            self._log(f'[本地] 创建文件夹: {target}')
            self.refresh_local()

    def _local_delete_selected(self):
        entries = self.tbl_local.selected_entries()
        if not entries:
            return
        if not self._confirm(f'本地删除确认', f'确定永久删除选中的 {len(entries)} 项？'):
            return
        import shutil
        for e in entries:
            try:
                if e.is_dir:
                    shutil.rmtree(e.path)
                else:
                    os.remove(e.path)
                self._log(f'[本地] 删除: {e.path}')
            except Exception as ex:
                self._show_warn('删除失败', f'{e.path}: {ex}')
        self.refresh_local()

    def _copy_dropped_local_to_current(self, paths: list[str]):
        """把从 Finder 拖到本地文件面板的文件复制到当前目录（避免误移动）。"""
        dst = self.tb_local.current_path() or os.path.expanduser('~')
        import shutil
        for s in paths:
            try:
                base = os.path.basename(s.rstrip('/'))
                d = os.path.join(dst, base)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        self._show_warn('跳过', f'目标已存在，跳过目录: {d}')
                        continue
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
                self._log(f'[本地] 复制 {s}  →  {d}')
            except Exception as ex:
                self._show_warn('复制失败', f'{s}: {ex}')
        self.refresh_local()

    # -- 远程操作 --

    def _exec_remote(self, ip: str, cmd: str, timeout: int = 30) -> tuple:
        """执行远程命令，优先使用交互式 shell（与指令面板共用会话）。

        Args:
            ip: 目标 IP
            cmd: 要执行的命令
            timeout: 超时秒数

        Returns:
            tuple: (rc, stdout, stderr) — shell 模式下 stderr 为空字符串
        """
        if self._shell_getter:
            try:
                shell = self._shell_getter(ip)
            except Exception:
                shell = None
            if shell and shell.is_alive:
                rc, out = shell.send_command(cmd, timeout=timeout)
                return rc, out, ''
        ssh = self._ssh_factory()
        return ssh.execute_command(ip, cmd, timeout=timeout)

    def _remote_mkdir(self, name: str):
        ip = self._get_ip()
        if not ip:
            self._show_warn('未选设备', '请先选择设备')
            return
        parent = self.tb_remote.current_path() or '/'
        target = parent.rstrip('/') + '/' + name.strip('/')
        code, _, err = self._exec_remote(ip, f"mkdir -p '{target}'", timeout=20)
        if code == 0:
            self._log(f'[远程] 创建文件夹: {ip}:{target}')
            self.refresh_remote()
        else:
            self._show_warn('创建失败', err or f'退出码 {code}')

    def _remote_delete_selected(self):
        ip = self._get_ip()
        if not ip:
            self._show_warn('未选设备', '请先选择设备')
            return
        entries = self.tbl_remote.selected_entries()
        if not entries:
            return
        if not self._confirm('远程删除确认', f'确定在 {ip} 上删除 {len(entries)} 项？（rm -rf 不可恢复）'):
            return
        for e in entries:
            cmd = f"rm -rf '{e.path}'"
            code, _, err = self._exec_remote(ip, cmd, timeout=60)
            if code == 0:
                self._log(f'[远程] 删除: {ip}:{e.path}')
            else:
                self._show_warn(f'删除失败 {e.name}', err or f'exit {code}')
        self.refresh_remote()

    # -- 上传/下载按钮触发 --

    def _upload_selected(self):
        entries = self.tbl_local.selected_entries()
        if not entries:
            self._show_warn('提示', '请在左侧本地面板选择要上传的文件/夹')
            return
        self._upload_paths([e.path for e in entries])

    def _download_selected(self):
        entries = self.tbl_remote.selected_entries()
        if not entries:
            self._show_warn('提示', '请在右侧远程面板选择要下载的文件/夹')
            return
        self._download_paths([e.path for e in entries])

    # -- 上传/下载提交任务 --

    def _upload_paths(self, local_paths: list[str]):
        ip = self._get_ip()
        if not ip:
            self._show_warn('未选设备', '请先选择一个设备作为上传目标')
            return
        remote_dir = self.tb_remote.current_path() or '/'
        if not local_paths:
            return
        delete = self.cb_delete.isChecked()
        task = TransferTask(
            direction='upload',
            target_ip=ip,
            source_paths=list(local_paths),
            dest_dir=remote_dir,
            delete=delete,
            on_log=self._log,
            on_done=lambda ok, msg: self._log(
                f'[上传完成{"" if ok else "失败"}] → {ip}:{remote_dir} {msg}'
            )
        )
        self.transfer_mgr.submit(task)

    def _download_paths(self, remote_paths: list[str]):
        ip = self._get_ip()
        if not ip:
            self._show_warn('未选设备', '请先选择一个下载源设备')
            return
        local_dir = self.tb_local.current_path() or os.path.expanduser('~')
        if not remote_paths:
            return
        delete = self.cb_delete.isChecked()
        task = TransferTask(
            direction='download',
            target_ip=ip,
            source_paths=list(remote_paths),
            dest_dir=local_dir,
            delete=delete,
            on_log=self._log,
            on_done=lambda ok, msg: (
                self._log(f'[下载完成{"" if ok else "失败"}] ← {ip} → {local_dir} {msg}'),
                self.refresh_local(),
            ),
        )
        self.transfer_mgr.submit(task)

    # -- 队列状态 UI --

    def _on_queue_changed(self, running: int, pending: int):
        total = running + pending
        if total == 0:
            self.lbl_queue.setText('传输: 空闲')
            self.lbl_queue.setStyleSheet('color:#666;')
            self.btn_upload.setEnabled(True)
            self.btn_download.setEnabled(True)
        else:
            self.lbl_queue.setText(f'传输: 执行中 {running} + 排队 {pending}')
            self.lbl_queue.setStyleSheet('color:#d80;font-weight:bold;')
            self.btn_upload.setEnabled(False)
            self.btn_download.setEnabled(False)

    # -- 辅助：弹窗 --

    def _show_warn(self, title: str, msg: str):
        if self._msg:
            self._msg(title, msg)
        else:
            self._log(f'[{title}] {msg}')

    def _confirm(self, title: str, text: str) -> bool:
        # 默认实现（如果主插件没传 confirm 回调）：直接用 QMessageBox
        return _qt_confirm(title, text)


# ---------------------------------------------------------------------------
# 内部 Qt 对话框辅助（独立函数，不依赖父类，以便 self._msg / self._ask 为空时使用）
# ---------------------------------------------------------------------------

def _qt_confirm(title: str, text: str) -> bool:
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def _qt_input_dialog(title: str, prompt: str) -> tuple[Optional[str], bool]:
    """极简输入框。返回 (text, ok_pressed)。"""
    from PyQt6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(None, title, prompt)
    return (text if ok else None, ok)

