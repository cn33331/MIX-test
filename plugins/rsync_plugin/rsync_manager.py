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

    @staticmethod
    def _tcl_brace(path):
        """把路径包装成 Tcl 花括号引用（brace quoting）。

        为什么不能用 shlex.quote：
            shlex 生成的是 **POSIX shell** 引号（单引号），而 expect 脚本是
            **Tcl** 语言。把 shlex 产物拼进 Tcl 源码后，Tcl 会按自己的规则
            解析这些字符，导致引号语义错乱；更糟的是远端 rsync 会把路径
            再次交给远端 shell 解析，单引号会破坏远端 `~` 展开，
            报出 ``zsh:1: unmatched '`` 并让连接中断（rsync code 12）。

            Tcl 的花括号引用是「完全字面量」：花括号内除 ``\\{`` / ``\\}``
            配对外不做任何替换，且花括号本身不会传给子进程。因此
            ``{root@ip:~/Library/Atlas2/}`` 传给 rsync 的就是
            ``root@ip:~/Library/Atlas2/``，波浪号得以保留给远端展开。

        Args:
            path: 待引用的路径

        Returns:
            str: 形如 ``{path}`` 的 Tcl 花括号引用；路径含花括号时回退为
                 反斜杠转义（这种极端情况无法用花括号表达）
        """
        if '{' in path or '}' in path:
            # 花括号无法自引用，退化为反斜杠转义（逐字符转义 Tcl 元字符）
            out = []
            for ch in path:
                if ch in ' \t\\{}[]$;"\'`*?':
                    out.append('\\' + ch)
                else:
                    out.append(ch)
            return ''.join(out)
        return '{' + path + '}'

    def _build_spawn_line(self, rsync_args, ssh_opts, src, dst):
        """构建 expect 的 spawn 命令行。

        路径通过 Tcl 花括号引用传递，保证：
          * 空格、单引号、$、* 等字符原样到达 rsync
          * 远端 `~` 不会被引号抑制，仍可由远端 shell 展开

        Args:
            rsync_args: rsync 参数列表（不含 -e）
            ssh_opts: ssh 选项字符串
            src: 源路径（可能含 user@host: 前缀）
            dst: 目标路径

        Returns:
            str: rsync 命令行文本（不含 spawn 前缀）
        """
        parts = ['rsync'] + list(rsync_args) + ['-e', self._tcl_brace(ssh_opts)]
        parts.append(self._tcl_brace(src))
        parts.append(self._tcl_brace(dst))
        return ' '.join(parts)

    def _build_rsync_cmd(self, ip, local_path, remote_path,
                         direction='push', delete=False, extra_args=None,
                         is_dir=None):
        """构建expect包装的rsync命令。

        使用环境变量 RSYNC_PWD 传递密码，避免特殊字符转义。
        路径使用 Tcl 花括号引用（见 ``_tcl_brace``），而不是 shlex.quote，
        以避免 Tcl 与 POSIX shell 引号语义混淆破坏远端路径解析。
        expect 脚本捕获 rsync 退出码并作为自身退出码返回。

        Args:
            ip: 目标IP地址
            local_path: 本地路径
            remote_path: 远程路径
            direction: 方向 'push'(推送) 或 'pull'(拉取)
            delete: 是否删除目标中源端没有的文件
            extra_args: 额外的rsync参数列表
            is_dir: pull 时远端源是目录(True)/文件(False)/未知(None)。
                    决定尾斜杠语义：目录不加斜杠=连文件夹一起同步；
                    文件若带斜杠会触发 rsync code 23。

        Returns:
            list: subprocess命令参数列表 ['expect', '-c', script]
        """
        rsync_args = ['-avhz']
        # ssh 复用 InteractiveShell 建立的 ControlMaster 主连接（同一 ControlPath）：
        # 设备 sshd 并发会话受限时不再新建连接；无主连接时自动回退独立认证。
        ssh_opts = (
            f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
            f'-o ControlPath=/tmp/mix_ssh_mux_{ip}_{self.port}.sock '
            f'-p {self.port}'
        )
        if delete:
            rsync_args.append('--delete')
        if extra_args:
            rsync_args.extend(extra_args)

        # 路径尾部斜杠处理（rsync 语义，实测确认）：
        #   目录 + 尾斜杠  a/dir/  → 只同步「目录内容」，不创建 dir 本身
        #   目录 + 无斜杠  a/dir   → 连「目录本身」一起同步 → 目标下出现 dir/
        #   文件 + 尾斜杠  a/f.txt/ → rsync 报错 code 23（文件不能加尾斜杠）
        #
        # 因此这里**不能**无条件补斜杠：
        #   * pull 时远端路径指向文件还是目录，本地无法用 os.path.isdir 判断，
        #     由调用方通过 is_dir 参数显式告知（默认 None = 保持原样）。
        #   * 目录下载要保持「包含整个文件夹」的语义，即不加尾斜杠。
        if direction == 'push':
            if not local_path.endswith('/') and os.path.isdir(local_path):
                local_path = local_path + '/'
            src = local_path
            dst = f'{self.username}@{ip}:{remote_path}'
        else:
            if is_dir is not None:
                # 文件或目录都去掉尾斜杠：
                #   文件带斜杠 → rsync code 23
                #   目录带斜杠 → 只同步内容，丢失文件夹本身
                remote_path = remote_path.rstrip('/') or '/'
            # is_dir is None 时保持调用方传入的原样
            src = f'{self.username}@{ip}:{remote_path}'
            dst = local_path

        # 用 Tcl 花括号引用路径（不要用 shlex.quote：那是 POSIX shell 语义，
        # 会让远端 rsync 收到字面单引号，破坏 ~ 展开并报 unmatched '）
        spawn_line = self._build_spawn_line(rsync_args, ssh_opts, src, dst)

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

    # -- 远程路径规范化 --

    def resolve_remote_home(self, ip, timeout=15):
        """探测远程设备家目录的绝对路径。

        远端 `~` 在 rsync 2.6.9（macOS 自带）下极易失败：rsync 的
        safe_arg() 会把含 `~` 的路径加单引号保护，而单引号恰好抑制了
        远端 shell 的波浪号展开，最终报 `unmatched '` 并中断连接。
        因此下载/推送到 `~` 路径前，先把 `~` 换成绝对路径最稳妥。

        Returns:
            str: 家目录绝对路径（如 /Users/xxx）；失败时返回空字符串
        """
        try:
            proc = subprocess.run(
                ['ssh', '-o', 'StrictHostKeyChecking=no',
                 '-o', 'UserKnownHostsFile=/dev/null',
                 '-o', f'ControlPath=/tmp/mix_ssh_mux_{ip}_{self.port}.sock',
                 '-p', str(self.port),
                 f'{self.username}@{ip}', 'echo "$HOME"'],
                capture_output=True, text=True, timeout=timeout,
                env=self._get_env(), stdin=subprocess.DEVNULL,
            )
            home = (proc.stdout or '').strip()
            if proc.returncode == 0 and home.startswith('/'):
                return home
        except Exception:
            pass
        return ''

    def expand_remote_path(self, ip, remote_path, output_callback=None):
        """把远程路径开头的 `~` 展开为绝对路径。

        仅当路径以 `~` 或 `~/` 开头时才探测家目录；其他路径原样返回。
        探测失败时返回原路径（保持旧行为，由调用方看到真实报错）。

        Args:
            ip: 目标IP地址
            remote_path: 远程路径，可能以 `~` 开头
            output_callback: 可选日志回调

        Returns:
            str: 展开后的路径
        """
        if not remote_path or not remote_path.startswith('~'):
            return remote_path
        if remote_path != '~' and not remote_path.startswith('~/'):
            # 形如 ~otheruser/... ：不做处理，交给远端 shell
            return remote_path
        home = self.resolve_remote_home(ip)
        if not home:
            if output_callback:
                output_callback(f'[提示] 无法探测 {ip} 的家目录，保留原路径 {remote_path}')
            return remote_path
        expanded = home + remote_path[1:]
        if output_callback:
            output_callback(f'[路径] {remote_path}  →  {expanded}')
        return expanded

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

        # 目标远端路径先去 ~，避免 rsync 2.6.9 加引号破坏波浪号展开
        remote_path = self.expand_remote_path(ip, remote_path, output_callback)
        cmd = self._build_rsync_cmd(ip, local_path, remote_path, 'push', delete)
        return self._run_rsync(cmd, output_callback, timeout)

    def pull_from_device(self, ip, remote_path, local_path, delete=False,
                         output_callback=None, timeout=None, is_dir=None):
        """从远程设备拉取文件到本地。

        Args:
            ip: 远程设备IP地址
            remote_path: 远程源路径
            local_path: 本地目标路径
            delete: 是否删除本地中远程没有的文件
            output_callback: 输出回调函数 callback(line_str)
            timeout: 超时时间(秒)，None表示不限制
            is_dir: 远端源是目录(True)/文件(False)/未知(None)。
                    传 None 时保持路径原样，由 rsync 自行判断。

        Returns:
            tuple: (return_code, output_text)
        """
        # 确保本地目录存在
        local_dir = local_path
        if not os.path.isdir(local_path):
            local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        # 源远端路径先去 ~，避免 rsync 2.6.9 加引号破坏波浪号展开
        remote_path = self.expand_remote_path(ip, remote_path, output_callback)
        cmd = self._build_rsync_cmd(ip, local_path, remote_path, 'pull', delete,
                                    is_dir=is_dir)
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
            code = proc.returncode
            if code == 12:
                # code 12 = 协议数据流错误，常见成因是远端 shell 未能启动
                # rsync --server（例如路径引号不配对报 unmatched '）。
                # 这里补一条提示，避免只看到本地 receiver 的 code=12 被误导。
                hint = ('[提示] rsync 协议流中断(code=12)：多为远端 shell 解析路径失败。'
                        '若上面出现 "unmatched" / "unexpected EOF"，请检查远程路径中的引号或波浪号。')
                output_lines.append(hint)
                if output_callback:
                    output_callback(hint)
            return code, '\n'.join(output_lines)

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
