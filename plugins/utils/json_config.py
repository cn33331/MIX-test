#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用 JSON 配置管理基类 - 供各插件复用。

提供「三级配置加载体系」：
1. 代码内嵌兜底默认值（fallback_config）—— 保证最小可用
2. 模板默认配置文件（default_config_path，如 config.default.json）—— 随插件分发
3. 实际配置文件（config_file）—— 深度合并补全缺失字段后生效

宿主应用可通过 `utils.config.config_manager` 提供备选配置路径，便于插件随包分发。
"""

import copy
import json
import os
from typing import Any, List, Optional


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base 中的同名键。

    当同名键在两侧均为 dict 时递归下钻合并，保证模板中新增的嵌套字段
    不会被配置文件中的旧结构整体覆盖；其余类型一律以 override 的值整体替换。

    Args:
        base: 基础字典，作为合并骨架，不会被修改。
        override: 覆盖字典，优先级高于 base。

    Returns:
        dict: 合并产生的新字典（深拷贝，与入参完全独立）。

    Warning:
        纯内存操作，无 I/O；dict 嵌套过深（>1000 层）可能触发递归上限
        RecursionError，正常配置层级远低于该限制。

    Example:
        >>> merged = deep_merge({'a': {'x': 1}, 'b': 2}, {'a': {'y': 3}})
        >>> assert merged == {'a': {'x': 1, 'y': 3}, 'b': 2}
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class BaseJsonConfig:
    """通用 JSON 配置管理器基类，子类按需继承复用。

    配置加载优先级（从高到低）：
    1. config_file 实际配置文件 —— 存在即优先读取并作为保存目标
    2. 宿主应用 config_manager 配置目录 —— 可选兼容路径（旧版本数据）
    3. default_config_path 模板默认文件 —— 随插件分发的默认值
    4. fallback_config 代码内嵌字典 —— 保证无任何文件时也可用

    子类只需在 __init__ 中传入对应的文件路径与兜底字典，即可获得
    load/save/get/set 完整能力，再按需补充领域专用便捷方法。

    Attributes:
        config_file: 实际配置文件绝对路径（保存写入的目标）。
        config: 当前生效的配置字典（嵌套结构，get/set 操作此对象）。
    """

    def __init__(
        self,
        config_file: str,
        default_config_path: Optional[str] = None,
        fallback_config: Optional[dict] = None,
    ) -> None:
        """初始化配置管理器并立即加载配置。

        Args:
            config_file: 实际配置文件的绝对路径，须为可写目录下的文件；
                目录不存在时 save() 会自动创建。
            default_config_path: 模板默认配置文件路径；为 None 时跳过模板合并，
                仅使用 fallback_config 作为默认骨架。
            fallback_config: 代码内嵌兜底默认字典；为 None 时视为空字典。

        Warning:
            __init__ 阶段会同步读取文件（磁盘 I/O），配置较大时会有毫秒级耗时；
            构造函数不涉及任何线程安全问题，可在任意线程中创建实例。
        """
        self.config_file = config_file
        self.default_config_path = default_config_path
        self.fallback_config = fallback_config or {}
        self.config_file = self._resolve_config_path()
        self.config = self.get_default_config()
        self.load()

    # ------------------------------------------------------------------
    # 默认配置与路径解析
    # ------------------------------------------------------------------

    def get_default_config(self) -> dict:
        """构造模板默认配置：代码兜底 + 模板文件深度合并。

        模板文件缺失或解析失败时静默跳过，仅返回代码内嵌兜底值，
        保证任何分发环境下插件都能获得完整的最小配置骨架。

        Returns:
            dict: 默认配置（每次调用返回独立深拷贝，修改不影响内部状态）。

        Example:
            >>> cfg = BaseJsonConfig('/tmp/a.json',
            ...                      fallback_config={'ssh': {'port': 22}})
            >>> cfg.get_default_config()['ssh']['port']
            22
        """
        fallback = copy.deepcopy(self.fallback_config)
        if self.default_config_path and os.path.exists(self.default_config_path):
            try:
                with open(self.default_config_path, 'r', encoding='utf-8') as f:
                    default = json.load(f)
                # 兜底合并，确保模板新增字段存在
                fallback = deep_merge(fallback, default)
            except Exception:
                pass
        return fallback

    def _resolve_config_path(self) -> str:
        """确定实际使用的配置文件路径。

        优先使用插件目录内的 config_file（随插件分发、便于他人打开即用）；
        若该文件不存在但宿主 config_manager 可用且有旧版本数据，
        则回退读取宿主配置目录中的对应文件以兼容历史版本；
        最终一律以 config_file 作为保存目标。

        Returns:
            str: 配置文件绝对路径。

        Warning:
            内部会尝试导入 `utils.config`，若该模块缺失则静默忽略，
            不影响默认行为（始终返回 config_file）。
        """
        if os.path.exists(self.config_file):
            return self.config_file
        # 兼容宿主应用的 config_manager（若有）
        try:
            from utils.config import config_manager
            config_dir = config_manager.get_config_dir()
            candidate = os.path.join(config_dir, self.host_config_name)
            if os.path.exists(candidate):
                return candidate
        except Exception:
            pass
        # 默认保存到插件目录内
        return self.config_file

    @property
    def host_config_name(self) -> str:
        """宿主配置目录中的兼容文件名。

        依据插件目录名推导，例如目录 `rsync_plugin` 对应
        `rsync_plugin_config.json`，保证与历史版本路径一致。

        Returns:
            str: 用于宿主 config_manager 配置目录中的文件名。
        """
        return os.path.basename(os.path.dirname(self.config_file)) + '_config.json'

    # ------------------------------------------------------------------
    # 加载与保存
    # ------------------------------------------------------------------

    def load(self) -> None:
        """从文件加载配置并深度合并模板补全缺失字段。

        读取优先级：config_file 实际文件 > 模板 > 代码兜底。
        配置文件不存在或 JSON 解析失败时以模板为准，不中断插件启动；
        合并后 self.config 保证包含模板中定义的所有字段。

        Warning:
            同步磁盘读取，建议在启动阶段调用一次即可，避免频繁 I/O。
        """
        template = self.get_default_config()
        loaded = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
            except Exception:
                loaded = {}
        self.config = deep_merge(template, loaded)

    def save(self) -> bool:
        """保存当前配置到文件并返回是否成功。

        保存目录不存在时自动递归创建；写入使用 UTF-8 + 2 空格缩进，
        保持配置文件人类可读，便于人工校对。

        Returns:
            bool: True 表示写入成功；False 表示目录创建或写入失败
                （调用方可据此给出错误提示）。

        Warning:
            多线程场景下若多个线程同时调用 save() 可能相互覆盖，
            建议由单一线程（如主线程）负责持久化。

        Example:
            >>> cfg = BaseJsonConfig('/tmp/demo_config.json',
            ...                      fallback_config={'ui': {'last_mode': 1}})
            >>> cfg.set('ui.last_mode', 0)
            >>> assert cfg.save() is True
        """
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 通用 get / set：支持点号分隔的嵌套键，如 'ssh.username'
    # ------------------------------------------------------------------

    @staticmethod
    def _split_key(key: str) -> List[str]:
        """将点号分隔的配置键拆分为路径列表。

        Args:
            key: 配置键名，支持 'a.b.c' 嵌套形式；空段（如连续的 '..'）会被过滤。

        Returns:
            list[str]: 键路径列表，空字符串或全点号输入返回空列表。
        """
        return [part for part in key.split('.') if part]

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔的嵌套键。

        优先按点号路径逐层下钻；仅当路径长度为 1 且嵌套查找失败时，
        回退到顶层直接查找，以兼容旧代码的扁平调用方式（如 'username'）。

        Args:
            key: 配置键名，如 'ssh.username' 或旧版 'username'。
            default: 取值失败（路径不存在）时返回的默认值。

        Returns:
            配置值；路径不存在时返回 default。

        Example:
            >>> cfg = BaseJsonConfig('/tmp/demo_config.json',
            ...                      fallback_config={'ssh': {'port': 22}})
            >>> cfg.get('ssh.port')
            22
        """
        # 优先：点号嵌套路径
        path = self._split_key(key)
        node = self.config
        for part in path:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if node is not None or (len(path) > 1):
            return node if node is not None else default
        # 兜底：顶层直接查找
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置配置项，支持点号分隔的嵌套键。

        路径中的中间节点不存在或不是 dict 时会自动创建为 dict，
        便于动态扩展配置结构；设置后需调用 save() 才会持久化。

        Args:
            key: 配置键名，如 'ssh.username'。
            value: 配置值，可为任意 JSON 可序列化类型。

        Warning:
            传入空键或全点号键时静默忽略，不做任何修改。
        """
        path = self._split_key(key)
        if not path:
            return
        node = self.config
        for part in path[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[path[-1]] = value
