#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
宿主应用全局配置管理器 - 通道表、默认服务/方法、指令历史。

继承通用基类 utils.json_config.BaseJsonConfig，统一配置持久化框架：
代码内嵌兜底默认值 + ~/.MIX-Tool/config.json 加载与保存。
"""

import os
from typing import Optional

from utils.json_config import BaseJsonConfig


class ConfigManager(BaseJsonConfig):
    """宿主应用全局配置管理器。

    管理应用级配置（通道表、默认服务/方法、指令历史），配置文件位于
    用户配置目录 ~/.MIX-Tool/config.json。继承 BaseJsonConfig 获得
    load/save/get/set 与点号嵌套键能力，并保留原有领域方法
    get_channels/save_history 等供 MIX_debug_plugin 等插件调用。

    Attributes:
        config_dir: 配置目录绝对路径（跨平台解析）。
        config: 当前配置字典（嵌套结构）。
        config_file: config.json 绝对路径（保存写入目标）。
    """

    # 代码内嵌兜底默认值：无任何配置文件时保证最小可用
    _DEFAULT_CONFIG = {
        'channels': [
            {'name': 'Slot1', 'ip': '192.168.99.36', 'port': '7801'}
        ],
        'default_service': 'relay',
        'default_method': 'reset',
        'history': [],
    }

    def __init__(self) -> None:
        """初始化全局配置管理器并加载配置。

        Warning:
            模块级单例 config_manager 在首次 import 时即完成磁盘 I/O
            （读取 + 首次自动落盘），仅执行一次。
        """
        self.config_dir = self._get_config_dir()
        super().__init__(
            config_file=os.path.join(self.config_dir, 'config.json'),
            fallback_config=self._DEFAULT_CONFIG,
        )
        print(f"配置文件: {self.config_file}")
        # 保持原行为：首次启动时自动生成配置文件
        if not os.path.exists(self.config_file):
            self.save()

    def _resolve_config_path(self) -> str:
        """确定配置文件路径。

        宿主管理器自身即配置源，无需走基类的宿主备选兼容逻辑
        （那针对的是插件随包分发场景），直接使用 config_file。

        Returns:
            str: 配置文件绝对路径。
        """
        return self.config_file

    def _get_config_dir(self) -> str:
        """获取配置目录路径（跨平台）。

        优先级：posix → ~/.MIX-Tool；Windows → %APPDATA%/MIX-Tool；
        其他系统 → cwd/config（避免依赖 __file__ 路径漂移）。

        Returns:
            str: 配置目录绝对路径。
        """
        if os.name == 'posix':  # macOS or Linux
            return os.path.join(os.path.expanduser('~'), '.MIX-Tool')
        if os.name == 'nt':  # Windows
            return os.path.join(os.environ.get('APPDATA', ''), 'MIX-Tool')
        # 其他系统使用当前工作目录
        return os.path.join(os.getcwd(), 'config')

    def get_config_dir(self) -> str:
        """获取配置目录路径。

        Returns:
            str: 配置目录绝对路径。
        """
        return self.config_dir

    # ------------------------------------------------------------------
    # 兼容旧 API：load_config / save_config
    # ------------------------------------------------------------------

    def load_config(self) -> dict:
        """加载配置文件（兼容旧 API）。

        Returns:
            dict: 当前配置字典（含兜底补全字段）。
        """
        self.load()
        return self.config

    def save_config(self, config: dict) -> bool:
        """保存配置到文件（兼容旧 API）。

        Args:
            config: 完整配置字典，整体覆盖写入文件。

        Returns:
            bool: True 表示写入成功；False 表示失败。
        """
        self.config = config
        return self.save()

    # ------------------------------------------------------------------
    # 领域方法：通道与历史
    # ------------------------------------------------------------------

    def get_channels(self) -> list:
        """获取通道配置列表。

        Returns:
            list: 通道字典列表，每个含 name/ip/port 字段。
        """
        return self.config.get('channels', [])

    def get_channel(self, index: int) -> Optional[dict]:
        """获取指定索引的通道配置。

        Args:
            index: 通道索引，有效范围 0 到通道数-1。

        Returns:
            dict | None: 通道字典；索引越界返回 None。
        """
        channels = self.get_channels()
        if 0 <= index < len(channels):
            return channels[index]
        return None

    def update_channel(self, index: int, channel_data: dict) -> bool:
        """更新指定索引的通道配置并保存。

        Args:
            index: 通道索引，有效范围 0 到通道数-1。
            channel_data: 待合并到该通道的字段字典（如 ip/port）。

        Returns:
            bool: True 保存成功；索引越界返回 False。
        """
        channels = self.get_channels()
        if 0 <= index < len(channels):
            channels[index].update(channel_data)
            self.config['channels'] = channels
            return self.save_config(self.config)
        return False

    def get_history(self) -> list:
        """获取历史指令列表。

        Returns:
            list: 历史指令列表。
        """
        return self.config.get('history', [])

    def save_history(self, history: list) -> bool:
        """保存历史指令列表。

        Args:
            history: 指令列表，整体覆盖保存。

        Returns:
            bool: True 保存成功；False 失败。
        """
        self.config['history'] = history
        return self.save_config(self.config)


# 创建全局配置实例
config_manager = ConfigManager()
