#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置管理模块 - 负责插件配置的加载、保存和配置界面

提供JSON格式的配置持久化，以及设备配置对话框。
配置内容包括：用户名、密码、端口、设备IP列表、同步路径等。
"""

import json
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QGroupBox, QMessageBox,
    QSpinBox, QCheckBox, QWidget
)
from PyQt6.QtCore import Qt


def get_default_config():
    """返回默认配置字典。

    Returns:
        dict: 默认配置
    """
    return {
        'username': 'gdlocal',
        'password': 'gdlocal',
        'port': 22,
        'scan_range': '10.8.30.14-23',
        'devices': [],
        'push_local_path': '',
        'push_remote_path': '/vault/ZJX_backup',
        'pull_remote_path': '',
        'pull_local_path': '',
    }


class RsyncConfig:
    """Rsync插件配置管理器。

    负责从JSON文件加载和保存配置。
    优先使用宿主应用的config_manager，不可用时回退到插件本地配置文件。

    Attributes:
        config: 当前配置字典
        config_file: 配置文件路径
    """

    def __init__(self):
        """初始化配置管理器，加载配置文件。"""
        self.config = get_default_config()
        self.config_file = self._get_config_path()
        self.load()

    def _get_config_path(self):
        """获取配置文件路径。

        优先使用宿主应用的config目录，不可用时使用插件目录。

        Returns:
            str: 配置文件绝对路径
        """
        try:
            from utils.config import config_manager
            config_dir = config_manager.get_config_dir()
        except Exception:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            config_dir = os.path.join(plugin_dir, 'config')

        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, 'rsync_plugin_config.json')

    def load(self):
        """从文件加载配置。

        文件不存在时使用默认配置。
        """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                # 合并配置，确保新增字段有默认值
                default = get_default_config()
                default.update(saved)
                self.config = default
            except Exception:
                self.config = get_default_config()
        else:
            self.config = get_default_config()

    def save(self):
        """保存配置到文件。

        Returns:
            bool: 是否保存成功
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key, default=None):
        """获取配置项。

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        return self.config.get(key, default)

    def set(self, key, value):
        """设置配置项。

        Args:
            key: 配置键名
            value: 配置值
        """
        self.config[key] = value

    def get_devices(self):
        """获取设备列表。

        Returns:
            list: 设备字典列表，每个设备包含 ip, name(可选)
        """
        return self.config.get('devices', [])

    def set_devices(self, devices):
        """设置设备列表。

        Args:
            devices: 设备字典列表
        """
        self.config['devices'] = devices
        self.save()


class ConfigDialog(QDialog):
    """配置对话框 - 编辑SSH连接和同步配置。

    提供用户名、密码、端口、扫描范围、同步路径等配置的编辑界面。
    """

    def __init__(self, config, parent=None):
        """初始化配置对话框。

        Args:
            config: RsyncConfig实例
            parent: 父窗口
        """
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('配置')
        self.setMinimumWidth(450)
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        """初始化界面。"""
        layout = QVBoxLayout(self)

        # SSH连接配置组
        ssh_group = QGroupBox('SSH连接配置')
        ssh_layout = QFormLayout(ssh_group)

        self.username_edit = QLineEdit()
        ssh_layout.addRow('用户名:', self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        ssh_layout.addRow('密码:', self.password_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        ssh_layout.addRow('SSH端口:', self.port_spin)

        self.scan_range_edit = QLineEdit()
        self.scan_range_edit.setPlaceholderText('如: 10.8.30.14-23 或 10.8.30.0/24')
        ssh_layout.addRow('扫描范围:', self.scan_range_edit)

        layout.addWidget(ssh_group)

        # 同步路径配置组
        path_group = QGroupBox('同步路径配置')
        path_layout = QFormLayout(path_group)

        self.push_local_edit = QLineEdit()
        self.push_local_edit.setPlaceholderText('本地源路径')
        path_layout.addRow('推送-本地路径:', self.push_local_edit)

        self.push_remote_edit = QLineEdit()
        self.push_remote_edit.setPlaceholderText('远程目标路径')
        path_layout.addRow('推送-远程路径:', self.push_remote_edit)

        self.pull_remote_edit = QLineEdit()
        self.pull_remote_edit.setPlaceholderText('远程源路径')
        path_layout.addRow('拉取-远程路径:', self.pull_remote_edit)

        self.pull_local_edit = QLineEdit()
        self.pull_local_edit.setPlaceholderText('本地目标路径')
        path_layout.addRow('拉取-本地路径:', self.pull_local_edit)

        layout.addWidget(path_group)

        # 按钮区域
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton('确定')
        cancel_btn = QPushButton('取消')
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _load_config(self):
        """从配置加载到界面控件。"""
        self.username_edit.setText(self.config.get('username', ''))
        self.password_edit.setText(self.config.get('password', ''))
        self.port_spin.setValue(self.config.get('port', 22))
        self.scan_range_edit.setText(self.config.get('scan_range', ''))
        self.push_local_edit.setText(self.config.get('push_local_path', ''))
        self.push_remote_edit.setText(self.config.get('push_remote_path', ''))
        self.pull_remote_edit.setText(self.config.get('pull_remote_path', ''))
        self.pull_local_edit.setText(self.config.get('pull_local_path', ''))

    def _on_ok(self):
        """确定按钮处理，保存配置并关闭对话框。"""
        self.config.set('username', self.username_edit.text().strip())
        self.config.set('password', self.password_edit.text())
        self.config.set('port', self.port_spin.value())
        self.config.set('scan_range', self.scan_range_edit.text().strip())
        self.config.set('push_local_path', self.push_local_edit.text().strip())
        self.config.set('push_remote_path', self.push_remote_edit.text().strip())
        self.config.set('pull_remote_path', self.pull_remote_edit.text().strip())
        self.config.set('pull_local_path', self.pull_local_edit.text().strip())
        self.config.save()
        self.accept()
