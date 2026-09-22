#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIX8 多设备二维码解码（多线程）核心脚本。

从 mix8_rpc_client.py 中提取 MIX8 JSON-RPC 通信的"最小核心"，整理成**一个独立单文件**，
对外只暴露**一个核心函数** ``decode_barcodes()``：

- 通过纯 ZeroMQ DEALER 实现 MIX_2.0 协议客户端（自动注册客户端身份）。
- **多线程并行**连接最多 8 台 MIX8 设备，每台设备分别发送 ``barcode.decode`` 获取二维码。
- 设备 IP/端口：内置默认字典 ``DEFAULT_DEVICES``；或通过 JSON 配置文件覆盖。
- 控制字符串形如 ``"1*2*3*4*5*6*7*8"``——字符串里有哪些号，就连哪些设备：
    如 ``"1*3*5"`` 只连接并解码第 1、3、5 台；
    不传则默认带全部 8 台的 ``"1*2*3*4*5*6*7*8"``。

只依赖 pyzmq（``pip install pyzmq``），无需其它包。

用法(命令行):
    python mix8_qrcode_decode.py                          # 全部 8 台
    python mix8_qrcode_decode.py "1*3*5"                  # 只连 1、3、5 台
    python mix8_qrcode_decode.py "1*3*5" --config cfg.json
"""

import argparse
import json
import socket
import threading
import time
import uuid

import zmq


# ---------------------------------------------------------------------------
# ① 默认连接配置。设备号为 1~8（1基）。
#    每台 MIX8 的 IP/端口直接写死在 DEFAULT_DEVICES 里；端口缺省时用下面默认值。
# ---------------------------------------------------------------------------
_DEFAULT_PORT = 7801                 # 设备信息只给 IP、没给端口时采用的默认端口

# 设备号 1~8 对应的默认连接配置（可整体替换，或让 JSON / 参数覆盖）。
DEFAULT_DEVICES = {
    "1": {"ip": "192.168.99.47", "port": 7801},
    "2": {"ip": "192.168.99.47", "port": 7802},
    "3": {"ip": "192.168.99.33", "port": 7801},
    "4": {"ip": "192.168.99.33", "port": 7802},
    "5": {"ip": "192.168.99.34", "port": 7801},
    "6": {"ip": "192.168.99.34", "port": 7802},
    "7": {"ip": "192.168.99.35", "port": 7801},
    "8": {"ip": "192.168.99.35", "port": 7802},
}

# ---------------------------------------------------------------------------
# ② MIX8 JSON-RPC 最小核心客户端（从 mix8_rpc_client.py 抽取精简）
#    —— 保留连接、注册、stub 调用、关闭 这几个必要环节。
# ---------------------------------------------------------------------------
def _net_ping(ip, port, timeout=0.5):
    """TCP 层连通性检测。

    timeout 尽量短：连不上的机器不必每次空等太久（离线主机 TCP SYN 会耗满这个时间）。
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        ok = s.connect_ex((ip, port)) == 0
        s.close()
        return ok
    except Exception:
        return False


class _Mix8Client:
    """单台 MIX8 设备的最小 JSON-RPC 客户端（线程内独立使用）。

    每个线程都创建属于自己的 zmq.Context / DEALER socket（不会跨线程共享）。
    """

    def __init__(self, ip, port, snd_timeout=3000, rcv_timeout=5000):
        self.ip = ip
        self.port = int(port)
        self.connected = False
        self._snd_timeout = snd_timeout
        self._rcv_timeout = rcv_timeout
        self._ctx = None
        self._sock = None

    def connect(self, register_retries=1):
        """完整连接：网络检测 -> 建 zmq socket -> 测试 -> 注册客户端身份。"""
        if not _net_ping(self.ip, self.port):
            return False
        try:
            self._ctx = zmq.Context()
            self._sock = self._ctx.socket(zmq.DEALER)
            self._sock.setsockopt(zmq.RCVTIMEO, self._rcv_timeout)
            self._sock.setsockopt(zmq.SNDTIMEO, self._snd_timeout)
            self._sock.connect(f"tcp://{self.ip}:{self.port}")

            # 连接验证：__server__.version()
            if self._call("__server__", "version", [], _no_recheck=True) is None:
                self.close()
                return False

            # 注册客户端身份（MIX8D 协议要求）
            registered = False
            for _ in range(register_retries):
                try:
                    self._call("__MIX_CLIENT_MANAGER__", "hello",
                               ["MIX8D"], _no_recheck=True)
                    registered = True
                    break
                except Exception:
                    time.sleep(0.5)
            if not registered:
                self.close()
                return False

            self.connected = True
            return True
        except Exception:
            self.close()
            return False

    def _call(self, remote_id, method, params, rpc_timeout=None, _no_recheck=False):
        """发送一次 JSON-RPC 并返回 result，出错抛异常。"""
        if not self._sock:
            raise RuntimeError("socket 未初始化")
        # 业务服务（非系统服务）先确保已注册检查
        if not _no_recheck and remote_id not in ("__server__", "__MIX_CLIENT_MANAGER__"):
            self._call("__MIX_CLIENT_MANAGER__", "hello", ["MIX8D"], _no_recheck=True)

        req = {"id": uuid.uuid4().hex, "remote_id": remote_id, "method": method}
        if params:
            req["args"] = params

        if rpc_timeout:
            self._sock.setsockopt(zmq.RCVTIMEO, int(rpc_timeout * 1000))
        self._sock.send_multipart([remote_id.encode("utf8"),
                                   json.dumps(req).encode("utf8")])
        try:
            parts = self._sock.recv_multipart()
        except zmq.error.Again:
            raise RuntimeError("请求超时")
        finally:
            if rpc_timeout:
                self._sock.setsockopt(zmq.RCVTIMEO, self._rcv_timeout)

        payload = parts[1] if len(parts) >= 2 else parts[0]
        resp = json.loads(payload.decode("utf8"))
        if "error" in resp:
            info = resp["error"]
            raise RuntimeError(f"RPC错误: {info.get('message', info)}")
        return resp.get("result")

    def stub(self, service, method, *args, rpc_timeout=None, **kwargs):
        """便捷调用：位置参数原样传递（不再强转 float），支持 kwargs。"""
        params = list(args)
        if kwargs:
            params.append(kwargs)
        return self._call(service, method, params, rpc_timeout=rpc_timeout)

    def close(self):
        try:
            if self._sock:
                try:
                    self._call("__MIX_CLIENT_MANAGER__", "bye", [],
                               _no_recheck=True)
                except Exception:
                    pass
                self._sock.close()
                self._sock = None
            if self._ctx:
                self._ctx.term()
                self._ctx = None
        except Exception:
            pass
        self.connected = False


# ---------------------------------------------------------------------------
# ③ 工具：设备字典载入 + 控制字符串解析
# ---------------------------------------------------------------------------
def _load_devices(devices=None, config_file=None):
    """返回最终 {设备号: {ip, port}} 字典。

    优先级：方法实参 devices > config_file 内容 > 内置 DEFAULT_DEVICES。
    """
    final = {}
    final.update(_deepcopy_dict(DEFAULT_DEVICES))
    if config_file:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 兼容两种结构：顶层直接是 {设备号:...}，或含 devices 字段
        pool = cfg.get("devices", cfg) if isinstance(cfg, dict) else {}
        final.update(_deepcopy_dict(pool))
    if devices:
        final.update(_deepcopy_dict(devices))
    return final


def _deepcopy_dict(d):
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[str(k)] = {str(kk): vv for kk, vv in v.items()}
        else:
            out[str(k)] = v
    return out


def parse_control(control):
    """把控制字符串（如 "1*3*5" / "1,2,3" / "1 2 3"）解析为设备号列表。

    允许使用 *、逗号、空格、或有连接号区段(如 "1-3")作为分隔。
    逐个字符扫描更稳健，不接受脏输入时也可用。返回排好序的 int 列表。
    """
    if control is None:
        return []
    c = str(control).strip()
    if not c:
        return []
    nums = set()
    # 先把区段展开：a-b -> [a..b]，其它分隔符拆成单个
    tokens = c.replace("*", ",").replace(" ", ",").replace("；", ",").split(",")
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if "-" in t and t.count("-") == 1:
            try:
                a, b = t.split("-")
                lo, hi = int(a), int(b)
                nums.update(range(lo, hi + 1))
                continue
            except ValueError:
                pass
        try:
            nums.add(int(t))
        except ValueError:
            pass
    return sorted(nums)


# ---------------------------------------------------------------------------
# ④ 多线程执行体（内部）
# ---------------------------------------------------------------------------

def _parse_addr(v):
    """把设备信息条目规整为 (ip, port)。兼容 {ip,port} / [ip,port] / str "ip:port"。"""
    if isinstance(v, dict):
        ip = v.get("ip") or v.get("host")
        port = v.get("port")
        if ip is None:
            raise ValueError(f"设备信息缺少 ip: {v}")
        return ip, int(port if port is not None else _DEFAULT_PORT)
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return str(v[0]), int(v[1])
    if isinstance(v, str) and ":" in v:
        ip, port = v.rsplit(":", 1)
        return ip, int(port)
    raise ValueError(f"无法识别的设备信息条: {v}")


def _worker_scan(no, ip, port, service, method, extra_params, rpc_timeout,
                 connect_retries, out, lock):
    """单台设备的线程任务：连接并 decode，把结果(或错误)写入 out。"""
    client = None
    t0 = time.perf_counter()
    try:
        client = _Mix8Client(ip, port)
        ok, last_err = False, None
        retries = max(1, connect_retries)
        for attempt in range(retries):
            ok = client.connect()
            if ok:
                break
            if client.connected is False:
                client.close()
                client = _Mix8Client(ip, port)  # 失败后重建干净实例再试
            last_err = "连接/注册失败"
            if attempt < retries - 1:          # 仅在确实要再重试时才小睡
                time.sleep(0.05)
        if not ok:
            with lock:
                out[no] = {"ok": False,
                           "dt": time.perf_counter() - t0,
                           "error": f"连接失败({ip}:{port}): {last_err}"}
            return

        # 发送 barcode.decode —— extra_params 为空则无位置参数，仅给较长解码超时
        if extra_params:
            result = client.stub(service, method, *extra_params,
                                 rpc_timeout=rpc_timeout)
        else:
            result = client.stub(service, method, rpc_timeout=rpc_timeout)
        with lock:
            out[no] = {"ok": True, "ip": ip, "port": port, "result": result,
                       "dt": time.perf_counter() - t0}
    except Exception as e:
        with lock:
            out[no] = {"ok": False, "dt": time.perf_counter() - t0,
                       "error": f"设备{no}解码失败: {e}"}
    finally:
        if client:
            client.close()


# ---------------------------------------------------------------------------
# ⑤ ★ 核心函数 ★
# ---------------------------------------------------------------------------
def decode_barcodes(control="1*2*3*4*5*6*7*8", devices=None, config_file=None,
                    service="barcode", method="decode", extra_params=(500,),
                    rpc_timeout=6.0, connect_retries=1,
                    print_result=None):
    """多线程连接若干台 MIX8 设备，分别调用 barcode.decode 获取二维码。

    Args:
        control: 控制字符串，如 "1*2*3*4*5*6*7*8"；含哪个号就连哪台设备。
                 字符串里少几个号就少连几台（默认全 8 台）。
                 None / "" 时默认全 8 台。
        devices: 可选 {设备号(str或int): {"ip":..,"port":..}, ...}，
                 用于覆盖默认 IP/端口。不传则用 config_file 或 DEFAULT_DEVICES。
        config_file: 可选 json 文件路径。顶层可以是 {设备号:{ip,port}}，
                 或 {"devices": 同结构}。优先级低于 devices 实参。
        service/method: 默认 ("barcode", "decode")，一般无需修改。
        extra_params: 传给 decode 的位置参数，默认 (500,)，即发送
                 barcode.decode(500)——500 为设备端解码窗口/超时(毫秒)。
                 传 None 或空则表示不传参数，只 barcode.decode()。
        rpc_timeout: 每台设备本次 RPC 的接收超时（秒）；decode 有 params(500)
                 作为设备内等待，此值只需比它稍长保证收到结果即可。
        connect_retries: 连接(含注册)的重试次数，默认 1 次。
        print_result: 是否打印每台结果。默认 True；传 False 关闭。

    Returns:
        dict: {设备号(int): {"ok": bool, 见下}}，
              - ok=True  : {"result": <解码返回>}（含 ip/port）
              - ok=False : {"error": str}（含 ip/port 尽量）
    同时（print_result=True）把结果整齐打印到控制台。
    """
    # 1) 设备字典 + 选中设备号
    dev_pool = _load_devices(devices=devices, config_file=config_file)
    nums = parse_control(control)
    # None/空 => 默认全部；否则只取出现的设备号并忽略不存在的号
    if not nums:
        nums = sorted(int(k) for k in dev_pool.keys())
    targets = []
    for n in nums:
        n = int(n)
        key = str(n)
        if key not in dev_pool or not dev_pool[key]:
            continue
        ip, port = _parse_addr(dev_pool[key])
        targets.append((n, ip, port))

    if not targets:
        print("没有可用的目标设备（检查 control / devices / config_file）。")
        return {}

    if print_result is None:
        print_result = True
    if print_result:
        sel = ",".join(map(str, [t[0] for t in targets]))
        print(f">> 将连接 {len(targets)} 台设备: [{sel}]  调用 {service}.{method}"
              f"({', '.join(map(str, (extra_params or ())))})")

    # 2) 多线程并行连接+解码
    out, lock = {}, threading.Lock()
    threads = []
    t_start = time.perf_counter()
    for no, ip, port in targets:
        t = threading.Thread(
            target=_worker_scan,
            args=(no, ip, port, service, method,
                  extra_params or [], rpc_timeout, connect_retries,
                  out, lock),
            daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    t_elapsed = time.perf_counter() - t_start

    # 3) 有序输出
    ordered = {}
    for no, ip, port in targets:
        ordered.setdefault(no, out.get(no, {"ok": False,
                                            "error": "线程异常结束"}))
    for no in ordered:
        ordered[no].setdefault("dt", None)

    if print_result:
        print("\n" + "=" * 60)
        print("结果汇总")
        print("=" * 60)
        for no in sorted(ordered):
            r = ordered[no]
            dt = f"{r['dt']*1000:6.0f}ms" if r.get("dt") is not None else "   -- "
            if r.get("ok"):
                print(f"  设备{no}: OK  耗时{dt}  结果 = {json.dumps(r.get('result'), ensure_ascii=False)}")
            else:
                print(f"  设备{no}: 失败 耗时{dt}  {r.get('error')}  ip={_where(dev_pool, no)}")
        print(f"  总耗时(并行, 从最慢单台决定): {t_elapsed*1000:.0f} ms")
        print("=" * 60)
    return ordered


def _where(dev_pool, no):
    try:
        ip, port = _parse_addr(dev_pool[str(no)])
        return f"{ip}:{port}"
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# ⑥ 命令行入口
# ---------------------------------------------------------------------------
def _main(argv=None):
    ap = argparse.ArgumentParser(
        description="MIX8 多设备二维码解码。control 里的设备号决定连哪些设备。")
    ap.add_argument("control", nargs="?", default="1*2*3*4*5*6*7*8",
                    help="控制字符串，如 1*3*5，缺省全部 1*2*3*4*5*6*7*8")
    ap.add_argument("--config", dest="config_file", default=None,
                    help="设备连接 json 配置路径（可选）")
    ap.add_argument("--file", dest="config_file2", default=None,
                    help="同 --config（兼容参数名）")
    ap.add_argument("--decode-timeout", type=int, default=500,
                    help="barcode.decode 的设备端解码超时(毫秒)，默认 500 -> decode(500)")
    ap.add_argument("--timeout", type=float, default=6.0,
                    help="每台 decode 的本次 RPC 接收超时，秒")
    ap.add_argument("--service", default="barcode")
    ap.add_argument("--method", default="decode")
    ap.add_argument("--quiet", action="store_true",
                    help="不打印逐台结果（仍返回字典）")
    args = ap.parse_args(argv)

    cfg = args.config_file or args.config_file2
    t0 = time.perf_counter()
    result = decode_barcodes(
        control=args.control,
        config_file=cfg,
        service=args.service,
        method=args.method,
        extra_params=(args.decode_timeout,),
        rpc_timeout=args.timeout,
        print_result=not args.quiet,
    )
    t_el = time.perf_counter() - t0
    ok_n = sum(1 for r in result.values() if r.get("ok"))
    print(f"完成：成功 {ok_n}/{len(result)} 台。本次总耗时 {t_el*1000:.0f} ms "
          f"（含 python 侧建线程/打印约几 ms）")
    return result


if __name__ == "__main__":
    _main()
