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
import pty
import select
import time
import re


class InteractiveShell:
    """交互式 SSH Shell 会话 — 保持指令连续性。

    使用 PTY (伪终端) 打开一个长期存活的 ssh 进程，所有命令通过同一个
    shell 会话发送，因此 cd / export / source 等操作的效果会持续到下一条命令。

    典型用法:
        shell = InteractiveShell('user', 'pass', '10.8.30.14')
        shell.send_command('cd /tmp')      # 切到 /tmp
        shell.send_command('ls')            # 显示 /tmp 的内容（连续性）
        shell.send_command('pwd')           # 输出 /tmp
        shell.close()

    线程安全：内部有锁，但建议同一时刻只有一个线程发送命令。
    """

    # 命令完成后打印的标记（用于检测输出结束 + 提取返回码）
    _MARKER = '__SHELL_MARKER_RC__'

    # 密码认证失败原因 → 用户可读提示（用于异常信息，便于日志定位根因）
    _AUTH_FAIL_HINTS = {
        'bad_password': '密码错误或账号无权限',
        'ssh_exited': '连接被拒绝或网络不可达',
        'timeout': '等待密码提示超时（连接卡住）',
        'io_error': 'PTY 读取异常',
    }

    def __init__(self, username, password, ip, port=22, connect_timeout=15):
        """初始化交互式 SSH 会话。

        Args:
            username: SSH 用户名
            password: SSH 密码
            ip: 目标 IP
            port: SSH 端口
            connect_timeout: 连接超时（秒）

        Raises:
            RuntimeError: 连接失败或密码认证失败
        """
        self.username = username
        self.password = password
        self.ip = ip
        self.port = port
        self._closed = False
        self._lock = threading.Lock()

        # 创建 PTY
        self.master_fd, self.slave_fd = pty.openpty()

        # 关闭 PTY 回显：否则 ssh 输入（如 export PS1="marker"）会被回显到 master，
        # 导致 _read_until 匹配到「回显文本里的标记」而提前返回（真实应答残留），
        # send_command 的 marker 解析因此取不到返回码（rc=-1）
        try:
            import termios
            attrs = termios.tcgetattr(self.slave_fd)
            attrs[3] &= ~termios.ECHO
            termios.tcsetattr(self.slave_fd, termios.TCSANOW, attrs)
        except Exception:
            pass  # 平台不支持 termios 时忽略，仅影响回显清理精度

        # 启动 ssh 进程（绑定到 PTY 的 slave 端）
        # ConnectTimeout 与 expect 路径（execute_command 用 5s）保持一致，避免等待过长
        ssh_args = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', f'ConnectTimeout={min(connect_timeout, 5)}',
            '-p', str(port),
            f'{username}@{ip}',
        ]
        try:
            self.proc = subprocess.Popen(
                ssh_args,
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                close_fds=True,
            )
        except Exception as e:
            os.close(self.master_fd)
            os.close(self.slave_fd)
            raise RuntimeError(f'启动 ssh 失败: {e}')

        # 关闭 slave 端（父进程不需要）
        os.close(self.slave_fd)

        # 等待密码提示并输入密码（返回精确失败原因，便于日志定位）
        reason = self._handle_password(connect_timeout)
        if reason != 'ok':
            self.close()
            hint = self._AUTH_FAIL_HINTS.get(reason, f'认证异常({reason})')
            raise RuntimeError(f'SSH 连接失败: {ip}（{hint}）')

        # 设置一个独特的 PS1，便于检测命令结束
        self._prompt_marker = f'__SHELL_PROMPT_{id(self)}__'
        self._send_raw(f'export PS1="{self._prompt_marker}"\n')
        # 等待第一次 prompt 出现（消费掉初始输出）
        self._read_until(self._prompt_marker, timeout=5)

    # ------------------------------------------------------------------
    # 内部 PTY 读写
    # ------------------------------------------------------------------

    def _send_raw(self, data: str):
        """直接写入 PTY master（不加锁，内部辅助方法）。"""
        os.write(self.master_fd, data.encode('utf-8'))

    def _read_until(self, pattern: str, timeout=30) -> str:
        """从 PTY 读取数据，直到看到 pattern 或超时。

        Args:
            pattern: 要匹配的字符串
            timeout: 超时秒数

        Returns:
            str: 读到的所有输出（包含 pattern 之前的所有内容）
        """
        buf = b''
        deadline = time.monotonic() + timeout
        pattern_bytes = pattern.encode('utf-8')

        while time.monotonic() < deadline:
            # 检查是否有数据可读
            rlist, _, _ = select.select([self.master_fd], [], [], 0.2)
            if rlist:
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                if pattern_bytes in buf:
                    break
            # 检查 ssh 进程是否已退出
            if self.proc.poll() is not None:
                # 读完剩余输出
                try:
                    while True:
                        rlist, _, _ = select.select([self.master_fd], [], [], 0.1)
                        if rlist:
                            chunk = os.read(self.master_fd, 4096)
                            if not chunk:
                                break
                            buf += chunk
                        else:
                            break
                except OSError:
                    pass
                break

        return buf.decode('utf-8', errors='replace')

    def _handle_password(self, timeout=15) -> str:
        """等待密码提示并输入密码，返回认证结果状态码。

        使用事件驱动的状态机替代固定延时轮询，避免慢网络下误判：
        1. 未发送密码前：匹配密码提示 / yes-no 确认 / 免密已登录；
        2. 发送密码后进入认证确认窗口（默认 4 秒）：
           - 出现 Permission denied 或重复密码提示 → 密码错误；
           - 出现 shell prompt 特征（$/#/%）→ 认证成功；
           - 窗口结束仍无失败关键词 → 保守视为认证成功。

        Returns:
            str: 状态码，取值含义：
                - 'ok': 认证成功
                - 'bad_password': 密码错误（Permission denied 或重复密码提示）
                - 'ssh_exited': ssh 进程提前退出（连接被拒/网络不通）
                - 'timeout': 等待密码提示整体超时
                - 'io_error': PTY 读取异常

        Warning:
            本方法在确认窗口内最多阻塞约 4 秒（网络正常时通常 <1 秒即返回）；
            返回 'ok' 仅代表"未观察到失败证据"，极端慢网络下仍可能误判成功，
            后续 send_command 失败时可视为认证未真正完成。
        """
        buf = b''
        deadline = time.monotonic() + timeout
        auth_pending = False        # 是否已发送密码，等待认证确认
        confirm_deadline = 0.0      # 认证确认窗口截止时间（发送密码后 +4s）

        while time.monotonic() < deadline:
            # 认证确认窗口结束且未出现失败关键词 → 视为成功
            if auth_pending and time.monotonic() >= confirm_deadline:
                return 'ok'

            rlist, _, _ = select.select([self.master_fd], [], [], 0.3)
            if rlist:
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError:
                    return 'io_error'
                if not chunk:
                    return 'ssh_exited'
                buf += chunk
                text = buf.decode('utf-8', errors='replace').lower()

                if not auth_pending:
                    # 密码提示（首次）
                    if 'password:' in text or 'passwd:' in text:
                        self._send_raw(self.password + '\n')
                        auth_pending = True
                        buf = b''
                        confirm_deadline = time.monotonic() + 4.0
                        continue
                    # 首次连接的 yes/no 确认
                    if 'are you sure you want to continue connecting' in text or 'yes/no' in text:
                        self._send_raw('yes\n')
                        buf = b''
                        continue
                    # 已有 shell 输出（key-based 认证或已登录）
                    if '$' in text or '#' in text or '%' in text:
                        return 'ok'
                else:
                    # 已发送密码：判定认证结果
                    if 'permission denied' in text or 'password:' in text or 'passwd:' in text:
                        return 'bad_password'
                    if '$' in text or '#' in text or '%' in text:
                        return 'ok'

            # ssh 进程退出（连接被拒 / 认证失败次数超限 / 网络断开）
            if self.proc.poll() is not None:
                return 'ssh_exited'

        # 整体超时：已发送密码但全程未见失败关键词 → 保守按成功处理
        if auth_pending:
            return 'ok'
        return 'timeout'

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def send_command(self, command: str, timeout=30) -> tuple:
        """在交互式 shell 中执行一条命令。

        因为 shell 是持续的，cd / export / source 等的效果会保留到后续命令。

        Args:
            command: 要执行的命令
            timeout: 超时秒数

        Returns:
            tuple: (return_code, stdout) — return_code 为 int，stdout 为命令输出文本
        """
        if self._closed:
            return -1, '会话已关闭'

        with self._lock:
            # 发送命令 + 标记行（通过 echo 打印返回码和标记）
            # 用 ; 分隔确保即使命令本身失败也能拿到 RC
            full_cmd = f'{command}\n'
            self._send_raw(full_cmd)

            # 立即发送标记命令（单独一行，获取上一条命令的 $?）
            marker_cmd = f'echo {self._MARKER}=$?\n'
            self._send_raw(marker_cmd)

            # 读取直到看到标记
            output = self._read_until(self._MARKER, timeout=timeout)

            # 提取返回码
            rc = -1
            rc_match = re.search(rf'{self._MARKER}=(\d+)', output)
            if rc_match:
                rc = int(rc_match.group(1))

            # 清理输出：
            # 1. 去掉命令回显行（PTY 回显时输出即命令原文，精确等值匹配避免误删真实结果）
            # 2. 去掉标记行与 prompt marker
            lines = output.split('\n')
            cleaned = []
            for line in lines:
                if line.strip() == command.strip():
                    continue
                if self._MARKER in line:
                    continue
                if self._prompt_marker in line:
                    continue
                if line.strip() == f'echo {self._MARKER}=$?':
                    continue
                cleaned.append(line)

            # 去掉首尾空行
            stdout = '\n'.join(cleaned).strip()
            return rc, stdout

    def close(self):
        """关闭交互式 shell 会话。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._send_raw('exit\n')
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass

    @property
    def is_alive(self) -> bool:
        """会话是否仍然存活。"""
        return not self._closed and self.proc.poll() is None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


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

    def __init__(self, username, password, port=22):
        """初始化SSH管理器。

        凭据必须由上层显式传入（通常从 RsyncConfig 读取）。
        禁止在本模块中硬编码项目特定的用户名/密码默认值，
        确保所有配置都通过配置文件统一管理，便于分发「打开即用」。

        Args:
            username: SSH用户名（必填）
            password: SSH密码（必填）
            port: SSH端口号，默认 22（SSH标准端口）
        """
        if not username:
            raise ValueError('SSHManager: username 不能为空，请在配置文件中设置 ssh.username')
        if not password:
            raise ValueError('SSHManager: password 不能为空，请在配置文件中设置 ssh.password')
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
