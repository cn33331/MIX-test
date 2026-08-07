#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
QSS 样式表管理模块 - 出厂/用户双目录加载 + 文件变更自动热重载 + 持久化保存。

设计目标：
    1. 把硬编码在 Python 源码中的 setStyleSheet 多行字符串抽离为独立 .qss 文件，
       便于 UI 设计师/前端人员修改而无需触碰 Python 代码。
    2. 样式文件保存后，UI 立即生效，无需重启应用（热重载）。
    3. **持久化配置**：用户对样式的修改保存到用户配置目录，重启/重新打包后仍然生效，
       不会"被还原"（这是与 v1.0 最核心的差异）。
    4. 提供统一接口，所有插件/主应用均可复用，消除重复代码。

双目录工作原理（区分只读分发资源 / 可写用户配置）：

    出厂目录（只读，跟随代码分发）        用户目录（可写，持久化保存）
    ┌─────────────────────────────┐      ┌─────────────────────────────┐
    │ plugins/xxx/styles/a.qss    │      │ ~/.MIX-Tool/styles/a.qss    │
    │  - 首次启动存在这份         │ ---> │  - 首次启动时自动复制一份   │
    │  - 打包后只读，不可持久写   │ <--- │  - 优先级高（先读这个）     │
    └─────────────────────────────┘      │  - 用户编辑/调用 save_user_style │
                                         │  - reset_to_factory 会删除它     │
                                         └─────────────────────────────┘
    启动加载顺序：用户目录文件存在则优先读，否则读出厂文件。
    保存顺序：始终写用户目录文件（出厂文件不改动），下次自动读用户版。
    热重载监视：同时监视两个文件，任一变更都触发 reload。

工作原理：
    - 加载阶段：按优先级读取 .qss 文件 → 调用 widget.setStyleSheet(text)。
    - 监视阶段：使用 QFileSystemWatcher 注册文件路径，文件写入完成后通过 fileChanged 信号
      触发重新读取 + 应用样式。QFileSystemWatcher 基于操作系统原生事件（inotify/kqueue/ReadDirectoryChanges），
      零轮询、零 CPU 浪费，响应延迟通常 < 50ms。
    - 父控件删除时，QObject 析构链路会自动解除监视，无需手动清理。

约束与边界：
    - .qss 文件使用 UTF-8 编码（PyQt 默认）。
    - 支持任意 QWidget 派生类（QPushButton / QFrame / QTabWidget / 整个 QMainWindow 等）。
    - 用户目录：macOS/Linux 为 `~/.MIX-Tool/styles/`，Windows 为 `%APPDATA%/MIX-Tool/styles/`。

典型场景：
    - 工控机 UI 调色（按钮颜色、边框、悬停态）在真机上调优，**保存后重启仍保持**。
    - 主题系统（白天/夜间两套 .qss 自由切换，用户修改持久化）。
    - 多插件共享同一套配色方案（所有插件引用公共 static/styles/*.qss）。
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Dict, List, Optional, Callable

from PyQt6.QtCore import QFileSystemWatcher, QObject, pyqtSignal


# ----------------------------------------------------------------------
# 路径工具：统一可写"用户配置目录"与只读"出厂资源目录"的解析
# ----------------------------------------------------------------------

def get_user_styles_dir() -> str:
    """返回用户样式目录（可写，持久化保存位置）。

    与 ConfigManager / logger 保持一致的目录策略：
    - macOS / Linux: ``~/.MIX-Tool/styles/``
    - Windows: ``%APPDATA%/MIX-Tool/styles/``
    - 其他系统或用户目录创建失败: 降级到 ``os.getcwd()/.mix-tool-styles/``

    Returns:
        str: 用户样式目录的绝对路径（已确保存在，若不存在则创建）。
            若所有位置都不可写（极端权限场景），返回 ``os.getcwd()`` 下的兜底目录。

    Raises:
        OSError: 若目标目录无法创建且无任何降级路径（极端权限失败），
            由 os.makedirs 抛出；调用方应捕获并按"配置持久化失败"处理。

    Note:
        路径策略必须与 ``utils/config.py`` / ``utils/logger.py`` 保持同步，
        避免"保存写到 A，启动读 B"造成重启丢失的经典缺陷（参见经验 1354015）。
    """
    if os.name == 'posix':
        home_dir = os.path.expanduser('~')
        base = os.path.join(home_dir, '.MIX-Tool')
    elif os.name == 'nt':
        base = os.path.join(os.environ.get('APPDATA', ''), 'MIX-Tool')
    else:
        base = os.path.join(os.getcwd(), '.mix-tool-data')

    styles_dir = os.path.join(base, 'styles')
    try:
        os.makedirs(styles_dir, exist_ok=True)
    except OSError:
        # 主目录不可写的极端情况，降级到当前工作目录
        styles_dir = os.path.join(os.getcwd(), '.mix-tool-styles')
        os.makedirs(styles_dir, exist_ok=True)
    return styles_dir


def get_user_qss_path(factory_qss_path: str) -> str:
    """将一个出厂 qss 文件路径映射到对应的用户样式目录中的路径。

    映射规则：以出厂文件名作为用户文件名（保留 basename），存放到用户样式目录。
    例如 ``plugins/rsync_plugin/styles/deploy_btn.qss`` →
    ``~/.MIX-Tool/styles/deploy_btn.qss``。

    Args:
        factory_qss_path: 出厂 qss 的相对或绝对路径，仅取其 basename 用于映射。

    Returns:
        str: 对应的用户 qss 文件的绝对路径（文件本身可能存在也可能不存在）。
    """
    basename = os.path.basename(factory_qss_path)
    return os.path.join(get_user_styles_dir(), basename)


class StyleSheetManager(QObject):
    """QSS 样式表加载 + 持久化 + 文件变更热重载管理器。

    以单控件为粒度绑定：一个控件 ↔ 一份 (出厂qss, 用户qss)。
    所有已绑定的 (widget, 双路径) 关系保存在内部字典，fileChanged 信号分发时按路径查找。

    Signals:
        reloaded: 样式热重载成功时发出，参数 (已加载的 qss 文件路径, 绑定控件)。
            路径是"实际被使用的那个"（用户版或出厂版），
            可用于在 UI 上打印日志或执行额外刷新。

    Example::

        from utils.stylesheet_manager import StyleSheetManager
        from PyQt6.QtWidgets import QApplication, QPushButton

        app = QApplication([])
        btn = QPushButton('部署')
        sm = StyleSheetManager()

        # 绑定出厂 qss；首次会复制一份到用户目录，之后以用户目录为准
        sm.bind_style(btn, 'plugins/rsync_plugin/styles/deploy_btn.qss')

        # 用户改了颜色，持久化保存（写到 ~/.MIX-Tool/styles/deploy_btn.qss）
        sm.save_user_style(btn, '''
            QPushButton{background:#E53935;color:white;font-weight:bold;}
        ''')

        # 下次启动：自动读到用户的红色，不再是出厂的紫色
        # 想回退：
        # sm.reset_to_factory(btn)
    """

    reloaded = pyqtSignal(str, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化样式表管理器。

        Args:
            parent: 父 QObject。若传入主窗口，则窗口销毁时自动释放监视资源；
                传入 None 则由调用方显式管理生命周期（不影响功能）。
        """
        super().__init__(parent)

        # 核心：QFileSystemWatcher（操作系统原生事件，非轮询）
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        # 绑定关系：widget_id -> {widget, factory_path, user_path, on_reload, auto_watch}
        self._bindings: Dict[int, Dict] = {}

        # 反向索引：任意受监视路径 -> [widget_id, ...]
        # 同一个 widget 可能同时占据"出厂路径"和"用户路径"两条条目
        self._path_to_ids: Dict[str, List[int]] = {}

        # fileChanged 去抖：editor "保存为临时文件+rename" 会短时间触发多次
        self._last_reload_ts: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # 公有 API
    # ------------------------------------------------------------------
    def bind_style(
        self,
        widget: QObject,
        factory_qss_path: str,
        auto_watch: bool = True,
        on_reload: Optional[Callable[[str, QObject], None]] = None,
        seed_if_absent: bool = True,
    ) -> bool:
        """绑定一个控件与 .qss 样式文件（出厂→用户双目录），并立即首次加载。

        启动应用时调用一次即相当于"自动记载"；后续文件保存即热重载。
        加载优先级：用户目录文件 > 出厂文件。首次绑定时若用户文件不存在，
        将把出厂文件复制一份作为"用户初始定制"，之后用户编辑的就是自己那份。

        Args:
            widget: 要应用样式的 PyQt 控件（QPushButton / QWidget / 主窗口等）。
                必须是 QObject 派生类，以便访问 setStyleSheet()。
            factory_qss_path: 出厂 qss 文件路径（相对路径或绝对路径）。
                通常位于 ``plugins/*/styles/`` 或 ``static/styles/`` 目录。
            auto_watch: 是否启用文件变更热重载。默认为 True；
                若在打包发布环境中 .qss 只读且用户不编辑，可传 False 禁用监视以节省少量资源。
            on_reload: 可选回调，每次样式（首次加载 + 热重载）应用成功后调用。
                签名: callback(loaded_qss_abs_path, widget) -> None。
                可用于记录日志或触发额外界面刷新（如 repaint）。
            seed_if_absent: 当用户目录下对应 qss 不存在时，是否自动从出厂文件复制一份。
                默认 True（推荐）。若传 False，则用户文件不存在时直接使用出厂文件（只读态）。

        Returns:
            bool: True 表示首次加载成功并已绑定；False 表示出厂文件不存在或读取失败。
                失败时控件样式保持不变，不抛出异常便于非关键 UI 降级运行。

        Raises:
            AttributeError: 若 widget 不具备 setStyleSheet 方法（非 QWidget/QObject 派生）。
                属于编程错误，快速暴露调用问题。

        Warning:
            QFileSystemWatcher 在 macOS 上对某些编辑器"原子保存"(write-then-rename) 策略
            可能偶发丢失监视；本类在每次触发 fileChanged 后会重新 addPath 以规避此问题。

        Example::

            sm.bind_style(
                self.deploy_btn,
                'plugins/rsync_plugin/styles/deploy_btn.qss',
                on_reload=lambda p, w: self.log_message(f'样式已重载: {os.path.basename(p)}')
            )
        """
        if not hasattr(widget, 'setStyleSheet'):
            raise AttributeError(
                f'widget={type(widget).__name__} 缺少 setStyleSheet() 方法，'
                '请传入 QWidget/QPushButton 等 PyQt 控件。'
            )

        factory_abs = os.path.abspath(factory_qss_path)
        user_abs = get_user_qss_path(factory_abs)

        # seed：若用户目录下不存在则复制出厂模板作为起点
        if seed_if_absent and not os.path.isfile(user_abs):
            if os.path.isfile(factory_abs):
                try:
                    shutil.copy2(factory_abs, user_abs)
                except OSError:
                    # 用户目录不可写就跳过，退化为仅使用出厂文件（只读）
                    pass

        # 首次加载（优先级：用户版 > 出厂版）
        effective_path = user_abs if os.path.isfile(user_abs) else factory_abs
        success = self._apply_style_file(widget, effective_path, on_reload)
        if not success:
            # 都失败则绑定不成立
            return False

        wid = id(widget)
        self._bindings[wid] = {
            'widget': widget,
            'factory_path': factory_abs,
            'user_path': user_abs,
            'on_reload': on_reload,
            'auto_watch': auto_watch,
        }

        if auto_watch:
            self._watch(factory_abs, wid)
            # 用户文件可能此时还不存在，但仍先登记——save_user_style 创建后需要热重载
            if os.path.isfile(user_abs):
                self._watch(user_abs, wid)
            else:
                # 记录到反向索引但不 addPath（因为还没创建，后续 save_user_style 会调用 _watch）
                self._path_to_ids.setdefault(user_abs, [])

        # 控件销毁时自动解绑（避免 dangling reference）
        if hasattr(widget, 'destroyed'):
            widget.destroyed.connect(lambda _=None, w=widget: self._auto_unbind(w))

        return True

    def unbind_style(self, widget: QObject) -> bool:
        """解除一个控件的样式绑定（停止热重载，不会清空已应用的样式）。

        被 destroyed 信号触发时，_watcher 可能已被 C++ 层析构，
        此处先通过 try/except 保护，避免 RuntimeError 泄漏到业务代码。

        Args:
            widget: 之前通过 bind_style 绑定过的控件。

        Returns:
            bool: True 解绑成功；False 表示该控件从未绑定。
        """
        wid = id(widget)
        binding = self._bindings.pop(wid, None)
        if binding is None:
            return False

        factory_abs = binding['factory_path']
        user_abs = binding['user_path']

        # 从反向索引 + 监视器中移除
        for path in (factory_abs, user_abs):
            ids = self._path_to_ids.get(path)
            if ids is not None and wid in ids:
                ids.remove(wid)
                if not ids:
                    self._path_to_ids.pop(path, None)
                    try:
                        if path in self._watcher.files():
                            self._watcher.removePath(path)
                    except RuntimeError:
                        # _watcher 已被 C++ 析构（父对象先被销毁），静默忽略
                        pass
        return True

    def save_user_style(self, widget: QObject, qss_content: str) -> bool:
        """把用户自定义样式内容写入用户配置目录中的对应 .qss 文件。

        写入成功后立即触发热重载（UI 直接应用）。下次应用启动会自动加载用户版，
        不会被出厂文件还原（解决"重新运行后内容又还原"的核心诉求）。

        Args:
            widget: 已通过 bind_style 绑定的目标控件。
            qss_content: 要保存的 QSS 文本字符串（UTF-8）。若为空字符串，
                效果等同于"无样式"，但仍会落盘并被下次启动读取。

        Returns:
            bool: True 保存成功；False 表示控件未绑定或文件系统写入失败。

        Raises:
            KeyError: widget 尚未被 bind_style 绑定（由 _bindings[wid] 抛出）。
                调用方可捕获并提示"请先绑定样式"。

        Warning:
            此方法会覆盖用户目录下已有的同名 qss 文件；若需保留历史版本，
            请调用方自行在写入前做备份。
        """
        wid = id(widget)
        binding = self._bindings.get(wid)
        if binding is None:
            return False

        user_abs = binding['user_path']
        try:
            os.makedirs(os.path.dirname(user_abs), exist_ok=True)
            with open(user_abs, 'w', encoding='utf-8') as fh:
                fh.write(qss_content)
        except OSError:
            return False

        # 若用户文件之前不存在（首次 save），此时加上监视
        if binding['auto_watch'] and user_abs not in self._watcher.files():
            self._watch(user_abs, wid)

        # 立即应用新内容（QFileSystemWatcher 也会触发，但这里保证同步生效）
        self._apply_style_file(widget, user_abs, binding.get('on_reload'))
        return True

    def reset_to_factory(self, widget: QObject) -> bool:
        """删除用户目录下对应的 .qss，恢复到出厂默认样式。

        删除成功后立即重新加载出厂文件。后续 save_user_style 再次保存用户定制。

        Args:
            widget: 已通过 bind_style 绑定的目标控件。

        Returns:
            bool: True 重置成功（用户文件不存在也算成功）；False 表示控件未绑定。
        """
        wid = id(widget)
        binding = self._bindings.get(wid)
        if binding is None:
            return False

        user_abs = binding['user_path']
        factory_abs = binding['factory_path']

        if os.path.isfile(user_abs):
            try:
                os.remove(user_abs)
            except OSError:
                return False
            # QFileSystemWatcher 会触发删除通知；此处直接同步加载出厂版
            self._apply_style_file(widget, factory_abs, binding.get('on_reload'))
        else:
            # 本来就没有用户文件，直接再加载一次出厂（确保确实是出厂态）
            self._apply_style_file(widget, factory_abs, binding.get('on_reload'))

        return True

    def has_user_style(self, widget: QObject) -> bool:
        """判断某控件当前是否使用的是用户自定义样式（用户目录文件存在）。

        用于 UI 显示"已定制"/"默认"状态标识。

        Args:
            widget: 已通过 bind_style 绑定的目标控件。

        Returns:
            bool: True 表示存在用户版（即便内容与出厂一致也算）；
                False 表示未绑定或不存在用户文件。
        """
        binding = self._bindings.get(id(widget))
        if binding is None:
            return False
        return os.path.isfile(binding['user_path'])

    def reload_all(self) -> int:
        """强制重新加载所有已绑定的样式文件（按优先级读用户版/出厂版）。

        通常在主题切换、窗口大小变化后手动触发；也可作为"编辑器保存没被监视到"的兜底。

        Returns:
            int: 成功重新加载的控件数量。
        """
        count = 0
        for wid in list(self._bindings.keys()):
            binding = self._bindings.get(wid)
            if binding is None:
                continue
            effective_path = self._effective_path_for(binding)
            ok = self._apply_style_file(
                binding['widget'], effective_path, binding.get('on_reload')
            )
            if ok:
                count += 1
        return count

    def list_bindings(self) -> List[Dict[str, str]]:
        """返回当前所有绑定关系的摘要列表，供调试/日志使用。

        Returns:
            List[Dict]: 每元素为:
                widget (str): 控件类型名
                factory (str): 出厂 qss 绝对路径
                user (str): 用户 qss 绝对路径
                using (str): 当前实际使用的路径（用户 or 出厂）
                has_user (str): "yes" / "no"
        """
        result = []
        for binding in self._bindings.values():
            effective = self._effective_path_for(binding)
            result.append({
                'widget': type(binding['widget']).__name__,
                'factory': binding['factory_path'],
                'user': binding['user_path'],
                'using': 'user' if os.path.isfile(binding['user_path']) else 'factory',
                'using_path': effective,
            })
        return result

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _watch(self, abs_path: str, widget_id: int) -> None:
        """把一个路径加入监视，并登记反向索引。

        重复调用对同一路径是安全的：addPath 不会重复添加，反向索引也不会重复 wid。

        Args:
            abs_path: 绝对路径（出厂或用户 qss）。
            widget_id: 对应控件的 id()。
        """
        if abs_path not in self._watcher.files() and os.path.isfile(abs_path):
            self._watcher.addPath(abs_path)
        ids = self._path_to_ids.setdefault(abs_path, [])
        if widget_id not in ids:
            ids.append(widget_id)

    @staticmethod
    def _read_qss_file(abs_path: str) -> Optional[str]:
        """读取 .qss 文件内容，使用 UTF-8 编码。

        设计为独立静态方法以便单元测试，且任何 I/O 失败返回 None 而非抛异常，
        避免样式加载失败把整个应用搞崩。

        Args:
            abs_path: .qss 文件的绝对路径。

        Returns:
            str | None: 成功返回样式文本；文件不存在 / 编码错误 / 权限错误返回 None。
        """
        if not os.path.isfile(abs_path):
            return None
        try:
            with open(abs_path, 'r', encoding='utf-8') as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _effective_path_for(binding: Dict) -> str:
        """根据 binding 返回实际应读取的路径（用户版优先，否则出厂版）。

        Args:
            binding: 单控件 binding 字典。

        Returns:
            str: 应读取的绝对路径。
        """
        user_abs = binding['user_path']
        factory_abs = binding['factory_path']
        return user_abs if os.path.isfile(user_abs) else factory_abs

    def _apply_style_file(
        self,
        widget: QObject,
        abs_path: str,
        on_reload: Optional[Callable[[str, QObject], None]],
    ) -> bool:
        """读取 .qss 文件并应用到 widget。

        Args:
            widget: 目标控件。
            abs_path: .qss 绝对路径（用户版或出厂版，有效优先级者）。
            on_reload: 成功时触发的回调。

        Returns:
            bool: 是否成功。
        """
        content = self._read_qss_file(abs_path)
        if content is None:
            # 不抛异常，但控件已绑定的话，后续监视器仍会重试
            return False

        try:
            widget.setStyleSheet(content)
        except Exception:
            # PyQt 对非法 QSS 通常不会抛异常，只会静默忽略；兜底捕获
            return False

        # 触发 reloaded 信号与可选回调
        self.reloaded.emit(abs_path, widget)
        if on_reload is not None:
            try:
                on_reload(abs_path, widget)
            except Exception:
                # 回调异常不影响主流程
                pass

        return True

    def _on_file_changed(self, changed_path: str) -> None:
        """QFileSystemWatcher.fileChanged 信号槽：文件变更时热重载。

        处理三件事：
            1. 原子写导致的监视器丢失 → 重新 addPath。
            2. 编辑器"删了再写"导致文件暂时不存在 → 忽略（30ms 内写入完成下次会再触发）。
            3. 用户文件出现/消失时自动切换"使用路径"（按优先级重新选）。

        Args:
            changed_path: 文件系统返回的变化路径（与注册时一致，是绝对路径）。
        """
        # macOS 原子写会导致路径被移除，重新挂接
        if os.path.isfile(changed_path) and changed_path not in self._watcher.files():
            self._watcher.addPath(changed_path)

        # 简单去抖（同一文件 50ms 内的多次触发只处理一次）
        now = time.time()
        last = self._last_reload_ts.get(changed_path, 0)
        if now - last < 0.05:
            return
        self._last_reload_ts[changed_path] = now

        affected_ids = list(self._path_to_ids.get(changed_path, []))
        for wid in affected_ids:
            binding = self._bindings.get(wid)
            if binding is None:
                continue
            # 重新计算优先级（用户文件可能刚被 reset 删除，此时应用出厂版）
            effective_path = self._effective_path_for(binding)
            self._apply_style_file(
                binding['widget'], effective_path, binding.get('on_reload')
            )

    def _auto_unbind(self, widget_ref: QObject) -> None:
        """控件 destroyed 信号触发时自动解绑。

        widget_ref 此时可能已是析构中对象，仅通过 id() 匹配，不调用其方法。

        Args:
            widget_ref: 正在被销毁的控件引用。
        """
        self.unbind_style(widget_ref)
