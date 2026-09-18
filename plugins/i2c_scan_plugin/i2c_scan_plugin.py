#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""I2C 板卡扫描插件 — 插卡自检 / 切 mux 逐个扫 I2C 地址。

用途：板卡插入后程序起不来，常因 I2C（尤其 mux 门控后的地址）无法找到。
本插件把一个调试动作组织成“按槽位（DOE 通道 / mux 通道）逐个切 mux -> 扫地址
-> 列表呈现”，并用“项目钩子”（纯函数）把“切法/扫描命令”抽成可随时改的配置，
让不同的板卡/项目无需改本插件即可复用。

两种通道都支持（按钩子动作里的 driver 自动选）：
- MIX JSON-RPC：调设备端方法（如 i2c_mux_base.set_channel_state_doe）。
- SSH：在板卡 shell 执行 detect_i2c / i2cdetect 等并解析地址。

依赖：PyQt6。SSH 底层复用 rsync_plugin/ssh_manager.py。
"""

import os
import sys
import threading

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from PyQt6.QtCore import pyqtSignal, QObject, Qt  # noqa: E402
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,  # noqa: E402
                             QGridLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QComboBox, QGroupBox, QHeaderView,
                             QPlainTextEdit)

import hook_base  # noqa: E402
import transports  # noqa: E402

VERSION = 'v1.0'


class _Worker(QObject):
    """后台执行槽位工作流的载体（信号驱动更新 UI，所有界面更新经信号回主线程）。"""

    log = pyqtSignal(str)
    finished = pyqtSignal()
    result = pyqtSignal(object, str, object)   # (slot, 文本结果, 错误)

    def __init__(self, hook, reg, ctx_factory):
        super().__init__()
        self._hook = hook
        self._reg = reg
        self._ctx_factory = ctx_factory
        self.slots = []

    def set_slots(self, slots):
        self.slots = list(slots or [])

    def emitLog(self, msg):
        self.log.emit(str(msg))

    # ---- 单槽：完整扫（切 mux+探地址；先一步做可达核验）----
    def scan_one(self, slot):
        try:
            ctx = self._ctx_factory()
            self._scan_one(ctx, slot)
        except ConnectionError as e:
            self.emitLog('⚠ %s' % e)
            self.result.emit(slot, '无法连接: %s' % e, e)
        except Exception as e:  # noqa: BLE001
            self.result.emit(slot, '错误: %s' % e, e)
        finally:
            self.finished.emit()

    # ---- 单槽：只切 mux 不探（仍先 ping 可达才动手）----
    def run_mux_only(self, slot):
        try:
            ctx = self._ctx_factory()
            # 先一步 ping 可达；不通 rpc 后什么都不做
            hook_base.preflight_reachable(ctx, needs_rpc=True,
                                          log=lambda m: self.emitLog(m))
            for op in (self._hook.mux_ops(slot) or []):
                self._reg.run(ctx, op)
            self.result.emit(slot, '连接 ok，mux 前置已执行 (未做扫描)', None)
        except ConnectionError as e:
            self.emitLog('⚠ %s' % e)
            self.result.emit(slot, '无法连接: %s' % e, e)
        except Exception as e:  # noqa: BLE001
            self.result.emit(slot, 'mux 失败: %s' % e, e)
        finally:
            self.finished.emit()

    # ---- 全部槽位连续扫（连接不通即整组中止，不再往下白扫）----
    def scan_all_of(self, slots):
        try:
            ctx = self._ctx_factory()
            errors = 0
            for slot in slots:
                self.emitLog('  -> DOE%s' % slot)
                try:
                    self._scan_one(ctx, slot)
                except ConnectionError as e:
                    self.emitLog('⚠ 连接失败，中止后续扫描: %s' % e)
                    return
                except Exception as e:  # noqa: BLE001
                    self.result.emit(slot, '错误: %s' % e, e)
                    errors += 1
            self.emitLog('全部槽位扫描完成（失败 %d）' % errors)
        finally:
            self.finished.emit()

    def _scan_one(self, ctx, slot):
        address_list, _ = hook_base.run_slot_workflow(
            self._reg, ctx, self._hook, slot, log=lambda m: self.emitLog(m))
        text = ', '.join(address_list) if address_list else '(空)'
        self.result.emit(slot, text, None)


class I2cScanPlugin(QWidget):
    """I2C 板卡扫描插件主面板。"""

    def __init__(self):
        super().__init__()
        self.version = VERSION
        self.setWindowTitle('I2C-Scan %s' % VERSION)

        self._hook = None
        self._project_name = None
        self._thread = None
        self._worker = None

        self._build_ui()
        self._reload_projects()

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        # --- 目标 / 项目 ---
        cfg = QGroupBox('目标与扫描驱动')
        cfgL = QGridLayout(cfg)
        cfgL.addWidget(QLabel('项目'), 0, 0)
        self.cbProject = QComboBox()
        self.cbProject.currentIndexChanged.connect(self._on_project_changed)
        cfgL.addWidget(self.cbProject, 0, 1)

        cfgL.addWidget(QLabel('IP'), 0, 2)
        self.edIp = QLineEdit('127.0.0.1')
        cfgL.addWidget(self.edIp, 0, 3)

        cfgL.addWidget(QLabel('RPC 端口'), 0, 4)
        self.edRpcPort = QLineEdit('7801')
        cfgL.addWidget(self.edRpcPort, 0, 5)

        cfgL.addWidget(QLabel('SSH 用户'), 1, 0)
        self.edSshUser = QLineEdit('mixadmin')
        self.edSshUser.setToolTip('除本地假连接外，切 mux 若走 SSH 命令需填')
        cfgL.addWidget(self.edSshUser, 1, 1)
        self.edSshPass = QLineEdit('')
        self.edSshPass.setEchoMode(QLineEdit.EchoMode.Password)
        self.edSshPass.setPlaceholderText('SSH 密码')
        cfgL.addWidget(self.edSshPass, 1, 2)

        self.btnTest = QPushButton('连接测试')
        self.btnTest.clicked.connect(self._test_connect)
        cfgL.addWidget(self.btnTest, 1, 4)

        self.lblDrive = QLabel('空闲')
        cfgL.addWidget(self.lblDrive, 1, 5)
        root.addWidget(cfg)

        # --- 每槽位扫描表 ---
        tbl = QGroupBox('按槽位扫描')
        tl = QVBoxLayout(tbl)
        bar = QHBoxLayout()
        self.btnScanAll = QPushButton('扫描全部槽位')
        self.btnScanAll.clicked.connect(self._scan_all)
        bar.addWidget(self.btnScanAll)
        self.lblProbe = QLabel('当前扫描命令: -')
        bar.addWidget(self.lblProbe, 1)
        tl.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['扫描对象', '切 mux', '扫描', '探测到地址'])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tl.addWidget(self.table)
        root.addWidget(tbl, 1)

        # --- 日志 ---
        grp = QGroupBox('调试日志')
        g2 = QVBoxLayout()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        g2.addWidget(self.log)
        grp.setLayout(g2)
        root.addWidget(grp)
        self._log('I2C 扫描插件 %s 就绪。加载项目下拉以选择切法/扫描模板。' % VERSION)

    # ------------------------------------------------------------- helpers
    def _log(self, msg):
        self.log.appendPlainText(str(msg))
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ----------------------------------------------------------- project
    def _reload_projects(self):
        self.cbProject.blockSignals(True)
        self.cbProject.clear()
        for title, name in hook_base.project_list():
            self.cbProject.addItem(title, userData=name)
        self.cbProject.blockSignals(False)
        if self.cbProject.count():
            self._on_project_changed(0)

    def _on_project_changed(self, _):
        name = self.cbProject.currentData()
        if not name:
            return
        try:
            self._hook = hook_base.load_project_module(name)
        except Exception as e:
            self._log('加载项目失败: %s' % e)
            return
        self._project_name = name
        dft = self._hook.PROJECT.get('default_ip')
        if dft:
            self.edIp.setText(dft)
        p = dft_port = self._hook.PROJECT.get('default_port')
        if p is not None:
            self.edRpcPort.setText(str(p))
        su = self._hook.PROJECT.get('default_ssh_user')
        if su:
            self.edSshUser.setText(su)
        slots = hook_base.slot_list(self._hook)
        self._rebuild_slot_rows(slots)

    def _rebuild_slot_rows(self, slots):
        self.table.setRowCount(0)
        self.slots = list(slots or [])
        for i, s in enumerate(self.slots):
            self.table.insertRow(i)
            # 第1列：名称（有 label 用 label 展示，原名放 tooltip）
            self.table.setItem(i, 0, QTableWidgetItem(str(s)))
            show = str(s)
            try:
                fn = getattr(self._hook, 'label_for', None)
                if callable(fn):
                    show = fn(s) or str(s)
            except Exception:
                pass
            if show != str(s):
                self.table.item(i, 0).setToolTip(str(s))
            self.table.item(i, 0).setText(show)

            needs = bool(self._hook_mux_needed(s))
            if needs:
                b = QPushButton('切 mux')
                b.clicked.connect(lambda _chk, si=s: self._do_mux_only(si))
                self.table.setCellWidget(i, 1, b)
            else:
                # 不需要切 mux —— 直接提示，不诱导用户去点“切 mux”
                lb = QLabel('不需要切 mux')
                lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lb.setStyleSheet('color:#8a8a8a; font-size:11px;')
                self.table.setCellWidget(i, 1, lb)

            b_scan = QPushButton('扫描')
            b_scan.clicked.connect(lambda _chk, si=s: self._do_slot(si))
            self.table.setCellWidget(i, 2, b_scan)
            self.table.setItem(i, 3, QTableWidgetItem(''))

    def _hook_mux_needed(self, slot):
        """查询该行是否需要先切 mux（展示用；优先级 hook 显式接口 > mux_ops 非空）。"""
        try:
            fn = getattr(self._hook, 'needs_mux', None)
            if callable(fn):
                return bool(fn(slot))
        except Exception:
            pass
        try:
            if callable(getattr(self._hook, 'mux_ops', None)):
                return bool(self._hook.mux_ops(slot))
        except Exception:
            pass
        return False

    # -------------------------------------------------------------- ctx
    def _make_ctx(self):
        ip = self.edIp.text().strip()
        ctx = {
            'ip': ip,
            'rpc_port': (self.edRpcPort.text().strip() or '7801'),
            'ssh_username': self.edSshUser.text().strip() or None,
            'ssh_password': self.edSshPass.text().strip() or None,
            'rpc_timeout': 30,
            'ssh_timeout': 40,
        }
        fake = getattr(self, '_fake_rpc', None)
        if fake is not None:
            # 透传给 registry（见 _registry），此处无需再写回 ctx
            pass
        return ctx

    def _registry(self):
        fake = getattr(self, '_fake_rpc', None)
        if fake is not None:
            return transports.default_registry(fake=fake)
        return transports.default_registry()

    # ------- 子线程执行封装（threading.Thread + Qt 信号回主线程）--------
    def _run_job(self, job_fn):
        """在专用线程跑 job_fn(worker)。

        业务结果经 worker 的 log/result 信号回主线程（跨线程发射自动走队列，
        保证 UI 只被主线程改动）。worker.probe 之下的 SSH/RPC 真实收发都在子线程，
        不阻塞界面。
        """
        busy = self._thread is not None and self._thread.is_alive()
        if busy:
            self._log('仍在运行上一任务，请稍候完成后再试。')
            return
        # 先知会用户目标是否可达（前台短探测，失败也不阻塞）
        try:
            ip = self.edIp.text().strip()
            rpc = int(self.edRpcPort.text().strip() or 7801)
            if ip and not self._tcp_reachable(ip, rpc, timeout=1.5):
                self._log('⚠ 目标 %s:%s RPC 不可达 —— 大概率网络不通或平台没起，后台仍会尝试。' % (ip, rpc))
        except Exception:
            pass
        wk = _Worker(self._hook, self._registry(), self._make_ctx)
        wk.set_slots(list(self.slots))
        wk.log.connect(self._log)
        wk.result.connect(self._on_worker_result)
        wk.finished.connect(self._on_worker_finished)
        self._worker = wk

        t = threading.Thread(target=lambda: self._worker_target(wk, job_fn), daemon=True)
        self._thread = t
        self.btnScanAll.setEnabled(False)
        self.lblDrive.setText('运行中...')
        t.start()

    def _worker_target(self, wk, job_fn):
        try:
            job_fn(wk)
        except Exception as e:  # noqa: BLE001
            wk.emitLog('任务异常: %s' % e)
            wk.finished.emit()

    def _on_worker_result(self, slot, text, error):
        msg = text
        if error is not None:
            msg = '错误: %s' % error
        self._slot_result(slot, msg)

    def _on_worker_finished(self):
        self.btnScanAll.setEnabled(True)
        self.lblDrive.setText('完成')

    # ---------------------------------------------------------- actions
    def _test_connect(self):
        if not self._hook:
            return
        ip = self.edIp.text().strip()
        rpc_port = (self.edRpcPort.text().strip() or '7801')
        self._log('连接参数: ip=%s rpc_port=%s ssh_user=%s' % (
            ip, rpc_port, self.edSshUser.text().strip()))
        self._log(self._reach_report(ip, [int(rpc_port), 22]))

    @staticmethod
    def _tcp_reachable(ip, port, timeout=2.0):
        """用裸 TCP socket 探测 ip:port（不发业务，不需 PTY，纯网络判断）。"""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip, int(port)))
            return True
        except Exception:
            return False
        finally:
            s.close()

    def _reach_report(self, ip, ports):
        """把 ip 的若干端口可达性汇总成一行中文诊断。"""
        parts = ['网络诊断 %s :' % ip]
        for p in sorted(set(int(x) for x in ports)):
            ok = self._tcp_reachable(ip, p)
            label = 'RPC' if p == 7801 else ('SSH' if p == 22 else ('端口%s' % p))
            parts.append('%s=%s' % (label, '通' if ok else '不通'))
            if not ok:
                parts.append(' → 请检查网线/网关/%s 平台进程是否在跑' % ip)
                break
        return '\n'.join(parts)

    def _do_mux_only(self, slot):
        if not self._hook:
            return
        self._set_probe_preview_slot(slot)
        self._log('开始切 mux -> DOE%s' % slot)
        self._run_job(lambda wk: wk.run_mux_only(slot))

    def _do_slot(self, slot):
        if not self._hook:
            return
        self._set_probe_preview_slot(slot)
        self._log('开始扫描槽位 DOE%s' % slot)
        self._run_job(lambda wk: wk.scan_one(str(slot)))

    def _scan_all(self):
        if not self._hook:
            return
        if self._thread is not None and self._thread.is_alive():
            self._log('仍在运行上一任务，请先完成再扫全部。')
            return
        self._set_probe_preview_slot(self.slots[0] if self.slots else None)
        self._log('开始扫描全部 %d 个槽位...' % len(self.slots))
        self._run_job(lambda wk: wk.scan_all_of(list(self.slots)))

    def _slot_result(self, slot, text):
        for i, s in enumerate(self.slots):
            if str(s) == str(slot):
                self.table.item(i, 3).setText(str(text))
                self.table.item(i, 3).setToolTip(str(text))
                return
        self.lblDrive.setText(str(text))

    def _set_probe_preview_slot(self, slot):
        if slot is None or not self._hook:
            self._set_probe_preview('(空)')
            return
        try:
            probe = self._hook.probe(slot)
        except Exception:  # noqa: BLE001
            probe = None
        if probe and probe.get('kind') in ('ssh-scan', 'ssh'):
            self._set_probe_preview(probe.get('cmd', ''))
        else:
            self._set_probe_preview('(rpc / 仅切 mux)')

    def _set_probe_preview(self, text):
        self.lblProbe.setText('当前扫描命令: %s' % text)

    # ------------------------------------------------------- framework
    def get_widget(self):
        return self

    def get_name(self):
        return 'I2C-Scan %s' % self.version
