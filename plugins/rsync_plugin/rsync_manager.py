#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rsync管理模块 - 负责文件同步推送到多设备、从远程设备拉取文件

使用 expect 包装 rsync 实现密码认证的文件同步。
依赖: expect (macOS/Linux 系统自带，无需额外安装)
"""

import subprocess
import threading
import os
import shlex

from ssh_manager import check_expect


class RsyncManager:
    """Rsync管理器 - 负责文件同步操作。

    提供文件推送到单台/多台设备、从设备拉取文件等功能。
    使用 expect 包装 rsync 实现密码认证。

    Attributes:
        username: SSH用户名
        password: SSH密码
        port: SSH端口，默认22
    """

    def __init__(self, username, password, port=22):
        """初始化Rsync管理器。

        凭据必须由上层显式传入（通常从 RsyncConfig 读取）。
        禁止在本模块中硬编码项目特定的用户名/密码默认值，
        确保所有配置都通过配置文件统一管理，便于分发「打开即用」。

        Args:
            username: SSH用户名（必填）
            password: SSH密码（必填）
            port: SSH端口号，默认 22（SSH标准端口）
        """
        if not username:
            raise ValueError('RsyncManager: username 不能为空，请在配置文件中设置 ssh.username')
        if not password:
            raise ValueError('RsyncManager: password 不能为空，请在配置文件中设置 ssh.password')
        self.username = username
        self.password = password
        self.port = port
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

    def _build_rsync_cmd(self, ip, local_path, remote_path,
                         direction='push', delete=False, extra_args=None):
        """构建expect包装的rsync命令。

        使用环境变量 RSYNC_PWD 传递密码，避免特殊字符转义。
        expect 脚本捕获 rsync 退出码并作为自身退出码返回。

        Args:
            ip: 目标IP地址
            local_path: 本地路径
            remote_path: 远程路径
            direction: 方向 'push'(推送) 或 'pull'(拉取)
            delete: 是否删除目标中源端没有的文件
            extra_args: 额外的rsync参数列表

        Returns:
            list: subprocess命令参数列表 ['expect', '-c', script]
        """
        rsync_args = ['-avhz']
        ssh_opts = f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {self.port}'
        if delete:
            rsync_args.append('--delete')
        if extra_args:
            rsync_args.extend(extra_args)

        # 调整路径尾部斜杠（目录同步时尾部加 / 表示同步目录内容）
        if direction == 'push':
            if not local_path.endswith('/') and os.path.isdir(local_path):
                local_path = local_path + '/'
            src = local_path
            dst = f'{self.username}@{ip}:{remote_path}'
        else:
            if not remote_path.endswith('/'):
                remote_path = remote_path + '/'
            src = f'{self.username}@{ip}:{remote_path}'
            dst = local_path

        # 使用 shlex.quote 安全处理路径中的空格和特殊字符
        # -e 参数值需用双引号包裹传给 rsync（内部含空格）
        spawn_parts = ['rsync'] + rsync_args + ['-e', f'"{ssh_opts}"']
        spawn_parts.append(shlex.quote(src))
        spawn_parts.append(shlex.quote(dst))
        spawn_line = ' '.join(spawn_parts)

        # rsync 同步可能耗时较长，默认 30 分钟超时
        expect_timeout = 1800
        script = (
            f'set timeout {expect_timeout}\n'
            f'spawn {spawn_line}\n'
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

    def push_to_device(self, ip, local_path, remote_path, delete=False, output_callback=None, timeout=None):
        """推送本地文件到单台远程设备。

        Args:
            ip: 目标IP地址
            local_path: 本地源路径
            remote_path: 远程目标路径
            delete: 是否删除目标中源端没有的文件
            output_callback: 输出回调函数 callback(line_str)
            timeout: 超时时间(秒)，None表示不限制

        Returns:
            tuple: (return_code, output_text)
        """
        if not os.path.exists(local_path):
            msg = f'本地路径不存在: {local_path}'
            if output_callback:
                output_callback(msg)
            return -1, msg

        cmd = self._build_rsync_cmd(ip, local_path, remote_path, 'push', delete)
        return self._run_rsync(cmd, output_callback, timeout)

    def pull_from_device(self, ip, remote_path, local_path, delete=False, output_callback=None, timeout=None):
        """从远程设备拉取文件到本地。

        Args:
            ip: 远程设备IP地址
            remote_path: 远程源路径
            local_path: 本地目标路径
            delete: 是否删除本地中远程没有的文件
            output_callback: 输出回调函数 callback(line_str)
            timeout: 超时时间(秒)，None表示不限制

        Returns:
            tuple: (return_code, output_text)
        """
        # 确保本地目录存在
        local_dir = local_path
        if not os.path.isdir(local_path):
            local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        cmd = self._build_rsync_cmd(ip, local_path, remote_path, 'pull', delete)
        return self._run_rsync(cmd, output_callback, timeout)

    def push_to_multiple(self, ip_list, local_path, remote_path, delete=False,
                         output_callback=None, max_workers=5):
        """推送本地文件到多台远程设备（多线程并发）。

        Args:
            ip_list: 目标IP地址列表
            local_path: 本地源路径
            remote_path: 远程目标路径
            delete: 是否删除目标中源端没有的文件
            output_callback: 输出回调函数 callback(ip, line_str)
            max_workers: 最大并发数

        Returns:
            dict: 每个IP的同步结果 {ip: (return_code, output_text)}
        """
        results = {}
        results_lock = threading.Lock()
        semaphore = threading.Semaphore(max_workers)

        def push_one(ip):
            semaphore.acquire()
            try:
                def ip_callback(line):
                    if output_callback:
                        output_callback(ip, line)
                code, output = self.push_to_device(
                    ip, local_path, remote_path, delete, ip_callback
                )
                with results_lock:
                    results[ip] = (code, output)
            finally:
                semaphore.release()

        threads = []
        for ip in ip_list:
            t = threading.Thread(target=push_one, args=(ip,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        return results

    def _run_rsync(self, cmd, output_callback=None, timeout=None):
        """执行rsync命令并实时捕获输出。

        使用 expect 包装执行 rsync，自动过滤 spawn 行和密码提示回显。
        密码通过 RSYNC_PWD 环境变量传递给 expect 脚本。

        Args:
            cmd: 命令参数列表（expect -c 脚本）
            output_callback: 输出回调函数 callback(line_str)
            timeout: 超时时间(秒)

        Returns:
            tuple: (return_code, output_text)
        """
        output_lines = []

        def _filter_line(line):
            """过滤 expect 输出中的杂质行。

            Args:
                line: 原始行

            Returns:
                str: 过滤后的行，None表示应跳过
            """
            stripped = line.strip()
            # 过滤 expect 的 spawn 命令行
            if stripped.startswith('spawn rsync') or stripped.startswith('spawn ssh'):
                return None
            # 过滤密码提示回显
            if stripped.lower().endswith('password:') or \
               stripped.lower().endswith('passwd:'):
                return None
            return line

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._get_env()
            )

            try:
                for line in proc.stdout:
                    line = line.rstrip('\n\r')
                    if not line:
                        continue
                    filtered = _filter_line(line)
                    if filtered is None:
                        continue
                    output_lines.append(filtered)
                    if output_callback:
                        output_callback(filtered)
            except Exception:
                pass

            proc.wait(timeout=timeout)
            return proc.returncode, '\n'.join(output_lines)

        except subprocess.TimeoutExpired:
            proc.kill()
            msg = 'rsync执行超时'
            output_lines.append(msg)
            if output_callback:
                output_callback(msg)
            return -1, '\n'.join(output_lines)
        except FileNotFoundError:
            msg = 'expect未安装，请确认系统已安装 expect'
            output_lines.append(msg)
            if output_callback:
                output_callback(msg)
            return -1, '\n'.join(output_lines)
        except Exception as e:
            msg = f'rsync执行异常: {str(e)}'
            output_lines.append(msg)
            if output_callback:
                output_callback(msg)
            return -1, '\n'.join(output_lines)
