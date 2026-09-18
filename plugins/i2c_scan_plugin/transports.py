#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""I2C 扫描插件的传输层。

项目钩子只负责“声明按槽位要做的动作”，实际向板卡下发/读取的动作统一在
这里按 ``driver`` 解释执行：
- ``rpc`` : 通过 MIX JSON-RPC 调用设备端方法（如切 mux、读 i2c 总线）。
- ``ssh`` : 通过 expect-ssh 在板卡 shell 上执行命令（如 detect_i2c / 原始探测）。

动作（op）由项目钩子返回，是一个 dict，即“函数式接口”所返回的可序列化动作清单。
本模块刻意不 import 具体设备协议；RPC/SSH 底层均惰性导入。
在离屏 / 无板卡环境下插件仍可加载，钩子与动作编派逻辑可单测（见 _FakeRpc）。
"""

import os
import re


# --------------------------------------------------------------------------
# I2C 地址解析（通用）
# --------------------------------------------------------------------------
def parse_found_addresses(text):
    """从各种来源的扫描文本中提取“探测到的 I2C 7bit 地址”。

    兼容已知两类输出：
    1) detect_i2c / i2cdetect 风格表格（行首总线号 + 每格 “XX/--/UU”）。
    2) 纯地址列表：一行一个、逗号/空格分隔、带或不带 0x 前缀。
    返回排序去重后的小写 0x 字符串列表。

    Args:
        text: 扫描输出文本。

    Returns:
        list[str]: 如 ['0x20', '0x50', '0x77']。
    """
    if not text:
        return []
    if isinstance(text, (list, tuple, set)):
        merged = []
        for t in text:
            merged.extend(parse_found_addresses(t))
        return _norm(merged)

    found = []
    for raw_line in text.splitlines():
        # 去掉表格行首“0xNN:”或“NN:”前缀
        line = re.sub(r'^\s*(?:0x)?[0-9a-fA-F]{2}\s*:\s*', '', raw_line).rstrip()
        for tok in re.split(r'\s+', line):
            tok = tok.strip()
            if tok in ('', '--', 'xx', 'x') or tok.lower() in ('uu', 'dd'):
                continue
            m = re.fullmatch(r'(?:0[xX])?([0-9a-fA-F]{2})', tok)
            if not m:
                continue
            val = int(m.group(1), 16)
            # 极低的“保留区”地址多为表格空格误读，排除 < 0x03
            if val < 0x03 or val > 0x77:
                continue
            found.append(f'0x{val:02x}')
    return _norm(found)


def _norm(items):
    seen, out = set(), []
    for it in items:
        if not isinstance(it, str):
            continue
        low = it.strip().lower()
        if low.startswith('0x'):
            low = low[2:]
        if not low:
            continue
        try:
            v = int(low, 16)
        except ValueError:
            continue
        key = f'{v:02x}'
        if key in seen:
            continue
        seen.add(key)
        out.append(f'0x{key}')
    return sorted(out)


# --------------------------------------------------------------------------
# 执行器
# --------------------------------------------------------------------------
class TransportRegistry:
    """动作（op）执行器注册与派发。"""

    def __init__(self):
        self._runners = {}

    def register(self, name, runner):
        self._runners[name] = runner

    def run(self, ctx, op):
        driver = (op or {}).get('driver')
        if not driver:
            raise ValueError('动作缺少 driver 字段: %r' % (op,))
        runner = self._runners.get(driver)
        if runner is None:
            raise ValueError('不支持的 driver: %r，已注册 %s' % (driver, sorted(self._runners)))
        return runner(ctx, op)


class _FakeRpc:
    """无服务器测试桩：按 key 返回预设结果，便于离屏/单测。"""

    def __init__(self, table):
        self._table = table or {}

    def stub(self, service, method, *args, rpc_timeout=None, **kwargs):
        key = f'{service}.{method}'
        entry = self._table.get(key)
        if entry is None:
            raise RuntimeError(f'fake rpc 未定义 key: {key}')
        if callable(entry):
            return entry(*args, **kwargs)
        return entry

    def close(self):
        pass


def make_rpc_runner(max_rpc_timeout=30, fake=None):
    """构造 RPC 动作执行器。

    op 形如:
        {'driver': 'rpc', 'service': 'dut0.i2c_mux_base',
         'method': 'set_channel_state_doe', 'args': [1]}

    底层使用 MIX_debug_plugin/mix 目录下的 JsonRpcClient（自动注册 + stub）。
    fake 非空（dict）时改走 _FakeRpc 桩，便于无服务器环境测试编派逻辑。
    """

    def run(ctx, op):
        if not isinstance(ctx, dict):
            raise TypeError('ctx 需为 dict（传输缓存存于 ctx 内）')
        key = (ctx.get('ip'), ctx.get('rpc_port') or ctx.get('port'))
        client = ctx.get('_rpc_client')
        if client is None or ctx.get('_rpc_key') != key:
            if fake is not None:
                client = _FakeRpc(fake)
            else:
                _import_and_add_mix_path()
                from mix8_rpc_client import JsonRpcClient
                ip = ctx.get('ip')
                port = int(ctx.get('rpc_port') or ctx.get('port') or 7801)
                client = JsonRpcClient(ip, port)
            ctx['_rpc_client'] = client
            ctx['_rpc_key'] = key

        service = op['service']
        method = op['method']
        args = list(op.get('args') or [])
        timeout = op.get('rpc_timeout') or ctx.get('rpc_timeout') or max_rpc_timeout
        return client.stub(service, method, *args, rpc_timeout=int(timeout))

    return run


def _import_and_add_mix_path():
    """确保可 `from mix8_rpc_client import JsonRpcClient`。

    mix8_rpc_client 位于 MIX_debug_plugin/mix，且依赖 plugins/utils（logger）。
    main_application 已把 plugins 目录加入 sys.path，这里只需补 mix 子目录。
    """
    import sys
    if any(m for m in sys.modules if m == 'mix8_rpc_client'):
        return
    candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, 'MIX_debug_plugin', 'mix')
    candidate = os.path.abspath(candidate)
    if candidate not in sys.path and os.path.isdir(candidate):
        sys.path.insert(0, candidate)


def make_ssh_runner(default_timeout=30):
    """构造 SSH 动作执行器。

    op 形如:
        {'driver': 'ssh',       'cmd': 'echo hi'}
        {'driver': 'ssh-scan',  'cmd': 'sudo detect_i2c -y 8'}   # 自动解析地址

    底层复用 rsync_plugin 的 SSHManager（expect 包装 ssh，密码经环境变量传）。
    ctx 需含 ssh_username/ssh_password/ssh_ip/ssh_port（或 ip/port/username 兜底）。
    """

    def _manager(ctx):
        if not isinstance(ctx, dict):
            raise TypeError('ctx 需为 dict')
        mgr = ctx.get('_ssh_manager')
        addr = ctx.get('_ssh_addr')
        ip = ctx.get('ssh_ip') or ctx.get('ip')
        key = (ip, ctx.get('ssh_port') or 22)
        if mgr is None or addr != key:
            from ssh_manager import SSHManager  # noqa: lazy (rsync plugin)
            username = ctx.get('ssh_username') or ctx.get('username') or 'mixadmin'
            password = ctx.get('ssh_password') or ctx.get('password') or ''
            port = int(ctx.get('ssh_port') or 22)
            mgr = SSHManager(username, password, port=port)
            ctx['_ssh_manager'] = mgr
            ctx['_ssh_addr'] = key
        return mgr

    def run(ctx, op):
        mgr = _manager(ctx)
        ip = ctx.get('ssh_ip') or ctx.get('ip')
        cmd = str(op['cmd'])
        timeout = int(op.get('timeout') or ctx.get('ssh_timeout') or default_timeout)
        ok, out = mgr.execute_command(ip, cmd, timeout=timeout)
        if not ok:
            raise RuntimeError('ssh 执行失败: %s -> %s' % (cmd, out))
        if op.get('driver') == 'ssh-scan':
            return parse_found_addresses(out)
        return out

    return run


def make_rpc_scan_runner(addr_min=0x03, addr_max=0x77, per_addr_timeout=1.5):
    """构造“RPC 地址遍历扫描”执行器（软件 I2C 总线扫描）。

    原理：对总线上的每个 7bit 地址调用远端 `read`（读 1 字节）。能拿到回包即认为
    存在此设备；读失败即无 ACK（跳过）。可免 SSH 即可在下位机上出总线地址表。

    注意：直接走 stub() 会被 `to_float` 把标量 int 转成 float，导致 i2c 驱动层
    read/write 报错。这里改用底层 `_send_request` 直发 raw int 参数，保真下发。

    op 形如：
        {'driver': 'rpc-scan', 'bus': 0}               # 扫 i2c_0 service
        {'driver': 'rpc-scan', 'service': 'i2c_5', 'min': 0x08, 'max': 0x20}
    返回已存在的地址列表（0x 小写，去重排序）。
    """

    def run(ctx, op):
        if not isinstance(ctx, dict):
            raise TypeError('ctx 需为 dict')
        service = op.get('service') or ('i2c_%d' % int(op.get('bus', 0)))
        lo = op.get('min', addr_min)
        hi = op.get('max', addr_max)
        lo = int(lo) if lo is not None else addr_min
        hi = int(hi) if hi is not None else addr_max
        client = _ensure_client(ctx)  # 失败会抛 ConnectionError，日志直接看到
        found = []
        for a in range(lo, hi + 1):
            try:
                client._send_request(service, 'read', [a, 1], rpc_timeout=per_addr_timeout)
                found.append(a)
            except Exception:
                pass
        return ['0x%02x' % a for a in found]

    return run


def _ensure_client(ctx, _deadline=5):
    """在 ctx dict 上获取/建立（并按 ip/port 缓存）一个 JsonRpcClient。

    新建立连接时会做一次轻量可达性核验（client.ping = 裸 TCP 连接，不需 PTY）。
    ip:port 不可达直接抛 ConnectionError，并把错误信息带到上层日志，避免下游把
    “网络不通”误判成“总线上没设备”。
    """
    if not isinstance(ctx, dict):
        raise TypeError('ctx 需为 dict')
    key = (ctx.get('ip'), ctx.get('rpc_port') or ctx.get('port'))
    ip = ctx.get('ip')
    client = ctx.get('_rpc_client')
    fresh = (client is None or ctx.get('_rpc_key') != key)
    if fresh:
        _import_and_add_mix_path()
        from mix8_rpc_client import JsonRpcClient
        port = int(ctx.get('rpc_port') or ctx.get('port') or 7801)
        client = JsonRpcClient(ip, port)
        # 轻量可达：ping = TCP connect。不通立刻给出明确诊断。
        try:
            reach = bool(client.ping(ip, port))
        except Exception:
            reach = False
        if not reach:
            try:
                client.close()
            except Exception:
                pass
            raise ConnectionError(
                'RPC 无法连接 %s:%s → 网络不通或下位机平台未启动。' % (ip, port))
        # 走一次注册握手确认（部分固件要 hello/register 后才真正可用）
        if hasattr(client, 'connect'):
            try:
                if callable(getattr(client, 'connect', None)):
                    client.connect()
            except Exception:
                pass
        ctx['_rpc_client'] = client
        ctx['_rpc_key'] = key
    return client


def make_rpc_call_runner():
    """执行一个“原样 int 参数”的 RPC 方法调用（绕过 stub 的 to_float 强转）。

    用于 mux 类方法（如 i2c_mux_base.set_channel_state_doe(ch)）等需要把 int 原样
    下发到驱动层的场景。op:
        {'driver':'rpc-call','service':'i2c_mux_base',
         'method':'set_channel_state_doe','args':[1]}
    末尾以 delay 拆分回 main：由调用方决定（此处仅返回结果）。
    """

    def run(ctx, op):
        client = _ensure_client(ctx)
        service = op['service']
        method = op['method']
        args = list(op.get('args') or [])
        timeout = int(op.get('rpc_timeout') or ctx.get('rpc_timeout') or 15)
        # service 可能带 dut0./mixdevice. 等宿主前缀，底层 RPC 服务名不带该前缀
        svc = service
        for prefix in ('dut0.', 'dut1.', 'mixdevice.'):
            if svc.startswith(prefix):
                svc = svc[len(prefix):]
                break
        return client._send_request(svc, method, args, rpc_timeout=timeout)

    return run


def default_registry(fake=None):
    """构造含 rpc / rpc-call / rpc-scan / ssh / ssh-scan 的默认注册表。"""
    reg = TransportRegistry()
    reg.register('rpc', make_rpc_runner(fake=fake))
    reg.register('rpc-call', make_rpc_call_runner())
    reg.register('rpc-scan', make_rpc_scan_runner())
    reg.register('ssh', make_ssh_runner())
    reg.register('ssh-scan', make_ssh_runner())
    return reg


def fmt_result(res):
    """把动作结果格式化为单行可读文本（用于日志/界面）。"""
    if isinstance(res, (list, tuple, set)):
        return ', '.join(str(x) for x in res)
    if isinstance(res, dict):
        try:
            import json
            return json.dumps(res, ensure_ascii=False)
        except Exception:
            return str(res)
    return str(res)
