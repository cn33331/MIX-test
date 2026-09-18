#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""B610（DFU 站）项目 —— 纯数据 + 通用表驱动框架。

核心框架(切/扫/出结果)在 hook_base.make_table_hook，本项目只声明两样就好：
  1) PROJECT   运行信息（IP/端口/切 mux 后稳定延时…）
  2) SLOTS     一行=一个想扫的 I2C 目标：
        scan     'i2c_N'           要扫的总线(RPC 软件地址遍历，免 SSH)
        mux      是否先切、切哪个通道：
                 - 不带 mux = 直接扫、不需要切
                 - mux: [op, ...]  本板有两级 mux，须逐行指明调哪一级：
                       * array-mux-* 行 → i2c_mux_array
                       * base-mux-*  行 → i2c_mux_base
                 - mux: 0/1/2...   仅当本项目只调一级 mux 时，用 MUX_PROTO 切一次
        label / expected           展示与人工比对用(可选)

  换/加项目：照抄本文件，改成你的 PROJECT + SLOTS + MUX_PROTO 即可，不用改插件。
  DOE 通道与物理设备的严格对应、expected 请按你实机检校后填。
"""

import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
from hook_base import make_table_hook  # noqa: E402

PROJECT = {
    'name': 'b610',
    'title': 'B610-DFU-7801',
    'default_ip': '192.168.99.34',
    'default_port': 7801,
    'default_ssh_user': 'mixadmin',
    'settle_ms': 250,
}

# 本板有“两级” mux，服务名不同，不能只留一个 MUX_PROTO（后者会覆盖前者）：
#   i2c_mux_array -> array-mux-* 行（扫 i2c_0）
#   i2c_mux_base  -> base-mux-*  行（扫 i2c_2）
# 因此下面每个槽位用 mux: [op] 明确写清“切哪一级”。MUX_PROTO 仅作单级 mux
# 项目的默认模板保留；本项目所有带 mux 的行都已显式给 op，不依赖它。
MUX_SVC_ARRAY = 'i2c_mux_array'
MUX_SVC_BASE = 'i2c_mux_base'
MUX_METHOD = 'set_channel_state_doe'


def _mux_op(service, channel):
    """切一级 mux 到指定通道的动作 op（rpc-call 原样下发 int）。"""
    return {'driver': 'rpc-call', 'service': service,
            'method': MUX_METHOD, 'args': [int(channel)]}


MUX_PROTO = _mux_op(MUX_SVC_BASE, 0)  # 单级 mux 项目的默认模板（本项目不依赖）

# 默认扫法：rpc（软件扫，免 SSH）。设成 'ssh' 则走板端 detect_i2c。
SCAN_MODE = os.environ.get('I2C_SCAN_MODE', 'rpc').lower()
SSH_TPL = 'sudo /mix/addon/detect_i2c -y {bus}'

SLOTS = [
    # ---------- 直接扫（不需要切 mux） ----------
    {'key': 'TRIG-I2C4',    'label': 'Trigger板 I2C4', 'scan': 'i2c_4',
     'expected': []},
    {'key': 'WIB-I2C6',     'label': 'WIB板 I2C6', 'scan': 'i2c_6',
     'expected': []},
    # ---------- 先切 array mux(i2c_mux_array) 再扫 i2c_0 ----------
    {'key': 'array-mux-0', 'label': 'array_i2c_0 通道0', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 0)], 'expected': []},
    {'key': 'array-mux-1', 'label': 'array_i2c_0 通道1', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 1)], 'expected': []},
    {'key': 'array-mux-2', 'label': 'array_i2c_0 通道2', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 2)], 'expected': []},
    {'key': 'array-mux-4', 'label': 'array_i2c_0 通道4', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 4)], 'expected': []},
    {'key': 'array-mux-5', 'label': 'array_i2c_0 通道5', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 5)], 'expected': []},
    {'key': 'array-mux-6', 'label': 'array_i2c_0 通道6', 'scan': 'i2c_0',
     'mux': [_mux_op(MUX_SVC_ARRAY, 6)], 'expected': []},
    # ---------- 先切 base mux(i2c_mux_base) 再扫 i2c_2 ----------
    {'key': 'base-mux-0', 'label': 'Base_i2c_2 通道0', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 0)], 'expected': []},
    {'key': 'base-mux-1', 'label': 'Base_i2c_2 通道1', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 1)], 'expected': []},
    {'key': 'base-mux-2', 'label': 'Base_i2c_2 通道2', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 2)], 'expected': []},
    {'key': 'base-mux-4', 'label': 'Base_i2c_2 通道4', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 4)], 'expected': []},
    {'key': 'base-mux-5', 'label': 'Base_i2c_2 通道5', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 5)], 'expected': []},
    {'key': 'base-mux-6', 'label': 'Base_i2c_2 通道6', 'scan': 'i2c_2',
     'mux': [_mux_op(MUX_SVC_BASE, 6)], 'expected': []},
]


# 按 SCAN_MODE 把 scan 翻译成“RPC 软件扫 / 板端 SSH 扫”；mux 前置已在各行显式给出
def _hook_rows():
    out = []
    for r in SLOTS:
        rr = dict(r)
        if not SCAN_MODE.startswith('rpc'):
            num = str(r.get('scan') or '').rsplit('_', 1)[-1]
            try:
                bus = int(num)
            except Exception:
                bus = 0
            rr['scan'] = {'kind': 'ssh-scan', 'cmd': SSH_TPL.format(bus=bus)}
        out.append(rr)
    return out


_hook = make_table_hook(PROJECT, _hook_rows(),
                        settle_ms=PROJECT.get('settle_ms', 250),
                        mux_proto=MUX_PROTO)


# —— 只做转发，让加载器/插件用的是同一份“表驱动结构” ——
PROJECT = _hook.PROJECT


def slots():
    return _hook.slots()


def mux_ops(slot):
    return _hook.mux_ops(slot)


def probe(slot):
    return _hook.probe(slot)


def release_ops(slot):
    return []


def settle_ms():
    return PROJECT.get('settle_ms', 250)


def label_for(key):
    return _hook.label_for(key)


def expected_for(key):
    return _hook.expected_for(key)


def needs_mux(key):
    return _hook.needs_mux(key)


def scan_hint(key):
    return _hook.scan_hint(key)
