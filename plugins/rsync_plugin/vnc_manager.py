#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VNC管理模块 - 负责VNC远程桌面连接

在macOS上通过 `open vnc://IP` 命令打开屏幕共享（Screen Sharing）。
支持动态创建 .vncloc 文件以保存VNC连接配置。
"""

import subprocess
import platform
import os


class VNCManager:
    """VNC管理器 - 负责VNC远程桌面连接。

    提供打开VNC连接、创建vncloc配置文件等功能。
    在macOS上使用系统自带的屏幕共享应用。

    Attributes:
        vncloc_dir: vncloc文件保存目录
    """

    def __init__(self, vncloc_dir=None):
        """初始化VNC管理器。

        Args:
            vncloc_dir: vncloc文件保存目录，默认为插件目录下的vncloc文件夹
        """
        if vncloc_dir is None:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            vncloc_dir = os.path.join(plugin_dir, 'vncloc')
        self.vncloc_dir = vncloc_dir
        os.makedirs(self.vncloc_dir, exist_ok=True)

    def open_vnc(self, ip, port=5900):
        """打开VNC连接到指定IP。

        在macOS上通过 `open vnc://IP` 启动屏幕共享应用。

        Args:
            ip: 目标IP地址
            port: VNC端口，默认5900

        Returns:
            bool: 是否成功启动
        """
        system = platform.system()
        if system == 'Darwin':
            # macOS
            vnc_url = f'vnc://{ip}'
            if port != 5900:
                vnc_url = f'vnc://{ip}:{port}'
            try:
                subprocess.Popen(['open', vnc_url])
                return True
            except Exception:
                return False
        elif system == 'Linux':
            # Linux尝试使用vncviewer
            vnc_url = f'{ip}::{port}'
            try:
                subprocess.Popen(['vncviewer', vnc_url])
                return True
            except Exception:
                return False
        else:
            return False

    def create_vncloc(self, ip, port=5900, filename=None):
        """创建.vncloc配置文件。

        .vncloc文件是macOS屏幕共享应用的配置文件，为plist XML格式。
        双击即可打开对应的VNC连接。

        Args:
            ip: 目标IP地址
            port: VNC端口，默认5900
            filename: 文件名（不含路径），默认为 IP.vncloc

        Returns:
            str: 创建的vncloc文件路径，失败返回None
        """
        if filename is None:
            # 替换IP中的点为下划线
            safe_name = ip.replace('.', '_')
            filename = f'{safe_name}.vncloc'

        filepath = os.path.join(self.vncloc_dir, filename)

        vnc_url = f'vnc://{ip}'
        if port != 5900:
            vnc_url = f'vnc://{ip}:{port}'

        plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>URL</key>
\t<string>{vnc_url}</string>
</dict>
</plist>
'''
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(plist_content)
            return filepath
        except Exception:
            return None

    def open_vncloc(self, filepath):
        """打开已有的.vncloc文件。

        Args:
            filepath: vncloc文件路径

        Returns:
            bool: 是否成功打开
        """
        if not os.path.exists(filepath):
            return False
        system = platform.system()
        if system == 'Darwin':
            try:
                subprocess.Popen(['open', filepath])
                return True
            except Exception:
                return False
        return False

    def open_vnc_by_ip(self, ip, port=5900):
        """根据IP打开VNC连接（优先使用open命令直接打开）。

        Args:
            ip: 目标IP地址
            port: VNC端口，默认5900

        Returns:
            bool: 是否成功启动
        """
        return self.open_vnc(ip, port)

    def list_vncloc_files(self):
        """列出所有已保存的vncloc文件。

        Returns:
            list: vncloc文件路径列表
        """
        if not os.path.exists(self.vncloc_dir):
            return []
        result = []
        for f in os.listdir(self.vncloc_dir):
            if f.endswith('.vncloc'):
                result.append(os.path.join(self.vncloc_dir, f))
        return result
