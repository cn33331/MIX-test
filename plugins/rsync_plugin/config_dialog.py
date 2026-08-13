#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置管理模块 - 负责 Rsync 插件配置的加载与保存。

继承通用基类 `utils.json_config.BaseJsonConfig`，在其上补充
SSH 凭据、设备列表、命令历史等 Rsync 特有便捷方法。
所有默认配置定义在 config.default.json 中，随插件目录分发。
"""

import json
import os
from typing import List, Optional, Tuple

from utils.json_config import BaseJsonConfig, deep_merge


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DEFAULT_PATH = os.path.join(PLUGIN_DIR, 'config.default.json')
CONFIG_LOCAL_PATH = os.path.join(PLUGIN_DIR, 'config.json')


# 代码内嵌兜底默认值：无任何配置文件时保证最小可用
_FALLBACK_CONFIG = {
    'ssh': {
        'username': 'gdlocal',
        'password': 'gdlocal',
        'port': 22,
    },
    'scan': {
        'range': '10.8.30.14-23',
    },
    'paths': {
        'deploy_script_path': '',
    },
    'sync': {
        'push_delete': False,
        'pull_delete': False,
    },
    'devices': [],
    'command_history': [],
    'ui': {
        'log_expanded': True,
        'last_mode': 1,  # 0=调试模式 1=一键自动部署，默认打开直接进入部署模式
    },
}


def get_default_config() -> dict:
    """从 config.default.json 加载默认配置字典（保持向后兼容）。

    与 BaseJsonConfig.get_default_config() 逻辑一致：代码兜底 + 模板文件
    深度合并；文件缺失或解析失败时静默回退。保留此模块级函数是为了
    兼容 rsync_plugin._update_managers 中的空值兜底调用。

    Returns:
        dict: 默认配置（深拷贝，修改不影响内部状态）。
    """
    return deep_merge(
        {}, deep_merge(_FALLBACK_CONFIG, _load_template_default())
    )


def _load_template_default() -> dict:
    """读取模板默认配置文件 config.default.json。

    Returns:
        dict: 模板内容；文件缺失或解析失败返回空字典。
    """
    if os.path.exists(CONFIG_DEFAULT_PATH):
        try:
            with open(CONFIG_DEFAULT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class RsyncConfig(BaseJsonConfig):
    """Rsync插件配置管理器。

    继承通用基类 BaseJsonConfig，配置加载优先级与基类一致：
    1. 插件目录内 config.json —— 随插件目录同步，给到其他人时「打开即用」
    2. 宿主应用的 config_manager 配置目录（可选兼容）
    3. 插件目录内 config.default.json —— 模板默认值
    4. 代码内嵌兜底默认值

    Attributes:
        config: 当前配置字典（嵌套结构）。
        config_file: 实际使用的配置文件路径（用于保存写入）。
    """

    def __init__(self) -> None:
        """初始化配置管理器，按优先级加载配置文件。"""
        super().__init__(
            config_file=CONFIG_LOCAL_PATH,
            default_config_path=CONFIG_DEFAULT_PATH,
            fallback_config=_FALLBACK_CONFIG,
        )

    # ------------------------------------------------------------------
    # SSH / Devices / CommandHistory 便捷方法
    # ------------------------------------------------------------------

    def get_ssh_credentials(self) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """获取SSH连接凭据。

        Returns:
            tuple: (username, password, port) 三元组；
                username/password 为字符串，port 为整数，缺失时为 None。
        """
        return (
            self.get('ssh.username'),
            self.get('ssh.password'),
            self.get('ssh.port'),
        )

    def get_devices(self) -> list:
        """获取设备列表。

        Returns:
            list: 设备字典列表，每个设备包含 ip、uname(可选)。
        """
        return self.config.get('devices', [])

    def set_devices(self, devices: list) -> None:
        """设置设备列表并立即保存。

        Args:
            devices: 设备字典列表，元素格式与 get_devices() 返回一致。
        """
        self.config['devices'] = devices
        self.save()

    def get_command_history(self) -> List[str]:
        """获取已保存的命令历史列表。

        Returns:
            list[str]: 历史命令（最近一条在首位），最多 30 条；
                返回副本，修改不影响内部状态。
        """
        return list(self.config.get('command_history', []))

    def set_command_history(self, commands: list) -> None:
        """设置命令历史并立即保存，超出 30 条自动截断。

        Args:
            commands: 命令列表；列表长度超过 30 时仅保留前 30 条。
        """
        commands = list(commands)[:30]
        self.config['command_history'] = commands
        self.save()
