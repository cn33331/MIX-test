#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SSH管理模块 - 负责SSH连接检测、远程命令执行、远程文件列表获取

使用 expect 包装 ssh 实现密码认证的SSH操作。
依赖: expect (macOS/Linux 系统自带，无需额外安装)
"""

import subprocess
import socket
import threading
import ipaddress
import shutil
import os


def check_expect():
    """检查expect是否已安装。

    Returns:
        bool: expect是否可用
    """
    return shutil.which('expect') is not None


def parse_ip_range(ip_range_str):
    """解析IP范围字符串为IP列表。

    支持以下格式:
        - "10.8.30.14"              单个IP
        - "10.8.30.14-20"           范围 (14到20)
        - "10.8.30.0/24"            CIDR
        - "10.8.30.14,10.8.30.20"   逗号分隔

    Args:
        ip_range_str: IP范围字符串

    Returns:
        list: IP地址列表
    """
    ip_range_str = ip_range_str.strip()
    if not ip_range_str:
        return []

    result = []
    # 逗号分隔的多段
    for segment in ip_range_str.split(','):
        segment = segment.strip()
        if not segment:
            continue
        # CIDR格式
        if '/' in segment:
            try:
                net = ipaddress.ip_network(segment, strict=False)
                for ip in net.hosts():
                    result.append(str(ip))
            except ValueError:
                continue
        # 范围格式 x.x.x.x-y
        elif '-' in segment:
            parts = segment.split('-')
            if len(parts) == 2:
                base = parts[0].strip()
                try:
                    end_num = int(parts[1].strip())
                    prefix = base.rsplit('.', 1)[0]
                    start_num = int(base.rsplit('.', 1)[1])
                    for i in range(start_num, end_num + 1):
                        result.append(f"{prefix}.{i}")
                except (ValueError, IndexError):
                    continue
        else:
            result.append(segment)
    return result


def check_port_open(ip, port=22, timeout=1.0):
    """检测目标IP的端口是否开放。

    Args:
        ip: 目标IP地址
        port: 端口号，默认22
        timeout: 超时时间(秒)

    Returns:
        bool: 端口是否开放
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


class SSHManager:
    """SSH管理器 - 负责SSH相关操作。

    提供网络扫描、远程命令执行、远程文件列表等功能。
    使用 expect 包装 ssh 实现密码认证。

    Attributes:
        username: SSH用户名
        password: SSH密码
        port: SSH端口，默认22
    """

    def __init__(self, username='gdlocal', password='gdlocal', port=22):
        """初始化SSH管理器。

        Args:
            username: SSH用户名
            password: SSH密码
            port: SSH端口号
        """
        self.username = username
        self.password = password
        self.port = port
        # 密码通过环境变量传给 expect，避免特殊字符转义问题
        self._env = None

    def _get_env(self):
        """获取包含密码环境变量的子进程环境。

        expect 脚本通过 $env(RSYNC_PWD) 读取密码，避免命令行转义。

        Returns:
            dict: 环境变量字典
        """
        if self._env is None:
            env = os.environ.copy()
            env['RSYNC_PWD'] = self.password
            self._env = env
        return self._env

    def _build_ssh_cmd(self, ip, command, timeout=10):
        """构建expect包装的ssh命令。

        使用环境变量 RSYNC_PWD 传递密码，避免特殊字符转义。
        expect 脚本捕获 ssh 退出码并作为自身退出码返回。

        Args:
            ip: 目标IP
            command: 要执行的远程命令
            timeout: 命令超时时间(秒)

        Returns:
            list: subprocess命令参数列表 ['expect', '-c', script]
        """
        # 转义 command 中的双引号和反斜杠，防止破坏 Tcl 字符串
        escaped_cmd = command.replace('\\', '\\\\').replace('"', '\\"')
        # expect 超时时间要比 ssh 超时略长，确保 ssh 先超时
        expect_timeout = max(timeout + 5, 15)
        script = (
            f'set timeout {expect_timeout}\n'
            f'spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
            f'-o ConnectTimeout=5 -p {self.port} {self.username}@{ip} "{escaped_cmd}"\n'
            f'expect {{\n'
            f'    -re {{(?i)(password|passwd):}} {{ send "$env(RSYNC_PWD)\\r"; exp_continue }}\n'
            f'    "yes/no" {{ send "yes\\r"; exp_continue }}\n'
            f'    timeout {{ exit 124 }}\n'
            f'    eof\n'
            f'}}\n'
            f'catch wait result\n'
            f'exit [lindex $result 3]\n'
        )
        return ['expect', '-c', script]

    @staticmethod
    def _parse_expect_output(stdout):
        """解析expect包装命令的输出，去除spawn行等杂质。

        expect 输出会包含 "spawn ssh ..." 和回显的密码提示等，需要过滤。

        Args:
            stdout: expect 命令的原始 stdout

        Returns:
            str: 过滤后的输出文本
        """
        if not stdout:
            return ''
        lines = stdout.split('\n')
        filtered = []
        for line in lines:
            # 过滤 expect 的 spawn 命令行
            if line.startswith('spawn ssh') or line.startswith('spawn rsync'):
                continue
            # 过滤密码提示回显
            if line.strip().lower().endswith('password:') or \
               line.strip().lower().endswith('passwd:'):
                continue
            filtered.append(line)
        return '\n'.join(filtered).strip()

    def execute_command(self, ip, command, timeout=10):
        """在远程主机上执行命令。

        使用 expect 包装 ssh，密码通过 RSYNC_PWD 环境变量传递。

        Args:
            ip: 目标IP地址
            command: 要执行的命令字符串
            timeout: 超时时间(秒)

        Returns:
            tuple: (return_code, stdout, stderr)
        """
        if not check_expect():
            return -1, '', 'expect未安装，请确认系统已安装 expect'

        cmd = self._build_ssh_cmd(ip, command, timeout)
        env = self._get_env()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,  # 外层超时略宽松
                env=env
            )
            # expect 输出需要过滤 spawn 行和密码提示回显
            stdout = self._parse_expect_output(proc.stdout)
            return proc.returncode, stdout, proc.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, '', '命令执行超时'
        except FileNotFoundError as e:
            return -1, '', f'依赖程序未安装: {str(e)}'
        except Exception as e:
            return -1, '', str(e)

    def get_uname(self, ip, timeout=10):
        """获取远程主机的系统信息。

        使用 uname -a 获取远程主机名称和系统信息。

        Args:
            ip: 目标IP地址
            timeout: 超时时间(秒)

        Returns:
            str: 远程主机系统信息，失败返回空字符串
        """
        code, stdout, stderr = self.execute_command(ip, 'uname -a', timeout)
        if code == 0:
            return stdout
        return ''

    def get_hostname(self, ip, timeout=10):
        """获取远程主机名。

        Args:
            ip: 目标IP地址
            timeout: 超时时间(秒)

        Returns:
            str: 主机名，失败返回空字符串
        """
        code, stdout, stderr = self.execute_command(ip, 'hostname', timeout)
        if code == 0:
            return stdout.strip()
        return ''

    def check_ssh_available(self, ip, timeout=8):
        """检测SSH连接是否可用。

        先检测端口开放，再尝试SSH连接。

        Args:
            ip: 目标IP地址
            timeout: SSH连接超时时间(秒)

        Returns:
            tuple: (是否可用, 主机名/系统信息)
        """
        if not check_port_open(ip, self.port, timeout=1.0):
            return False, ''
        uname_info = self.get_uname(ip, timeout)
        if uname_info:
            return True, uname_info
        return False, ''

    def list_remote_files(self, ip, remote_path, timeout=10):
        """列出远程主机指定路径下的文件和目录。

        Args:
            ip: 目标IP地址
            remote_path: 远程路径
            timeout: 超时时间(秒)

        Returns:
            list: 文件信息字典列表，每个字典包含:
                  name(名称), type(类型: file/dir), size(大小), modify(修改时间)
                  失败返回空列表
        """
        if not remote_path:
            return []
        # 使用ls -l获取详细信息，通过awk格式化输出
        # 格式: 类型|大小|修改时间|名称
        cmd = f'ls -l --time-style=long-iso "{remote_path}" 2>/dev/null'
        code, stdout, stderr = self.execute_command(ip, cmd, timeout)
        if code != 0 or not stdout:
            # macOS的ls不支持--time-style，尝试备用命令
            cmd = f'ls -lT "{remote_path}" 2>/dev/null'
            code, stdout, stderr = self.execute_command(ip, cmd, timeout)
            if code != 0 or not stdout:
                return []

        files = []
        for line in stdout.split('\n'):
            line = line.strip()
            if not line or line.startswith('total'):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            perms = parts[0]
            size = parts[4]
            name = parts[8]
            # 拼接修改时间
            date_str = ' '.join(parts[5:8])
            file_type = 'dir' if perms.startswith('d') else 'file'
            files.append({
                'name': name,
                'type': file_type,
                'size': size,
                'modify': date_str,
                'perms': perms
            })
        return files

    def scan_network(self, ip_list, max_workers=20, progress_callback=None):
        """扫描IP列表，检测哪些IP可以通过SSH连接。

        使用多线程并发扫描，提高扫描速度。

        Args:
            ip_list: 要扫描的IP地址列表
            max_workers: 最大并发线程数
            progress_callback: 进度回调函数 callback(ip, is_online, hostname)

        Returns:
            list: 可用设备列表，每个元素为 {'ip': ip, 'uname': uname_info}
        """
        results = []
        results_lock = threading.Lock()
        total = len(ip_list)
        scanned = [0]  # 使用列表实现可变计数器
        scanned_lock = threading.Lock()

        def scan_one(ip):
            available, uname_info = self.check_ssh_available(ip)
            with scanned_lock:
                scanned[0] += 1
            if available:
                with results_lock:
                    results.append({'ip': ip, 'uname': uname_info})
            if progress_callback:
                progress_callback(ip, available, uname_info, scanned[0], total)

        threads = []
        for ip in ip_list:
            while len(threads) >= max_workers:
                # 等待部分线程完成
                for t in threads[:]:
                    if not t.is_alive():
                        t.join()
                        threads.remove(t)
                threading.Event().wait(0.05)
            t = threading.Thread(target=scan_one, args=(ip,), daemon=True)
            t.start()
            threads.append(t)

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 按IP排序
        results.sort(key=lambda x: [int(p) if p.isdigit() else 0 for p in x['ip'].split('.')])
        return results
