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
import time
import traceback

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from PyQt6.QtCore import pyqtSignal, QObject, Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,  # noqa: E402
                             QLabel, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QComboBox, QGroupBox, QHeaderView,
                             QPlainTextEdit)

import hook_base  # noqa: E402
import transports  # noqa: E402

VERSION = 'v1.0'


def _fmt_ops(ops):
    """把动作列表渲染成一行可读的“将下发的指令”，供日志显示。"""
    parts = []
    for op in (ops or []):
        drv = op.get('driver')
        if drv == 'delay':
            parts.append('delay(%sms)' % op.get('ms', 0))
        elif drv in ('rpc', 'rpc-call'):
            args = op.get('args')
            a = ''
            if args:
                a = '(' + ', '.join(str(x) for x in args) + ')'
            parts.append('%s.%s%s' % (op.get('service'), op.get('method'), a))
        else:
            parts.append(str(op.get('cmd') or op))
    return ' -> '.join(parts) if parts else '(无)'


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
        # 停止标志：由 UI 线程 set()，工作线程在每个槽位之间检查一次
        self._stop = threading.Event()

    def request_stop(self):
        """请求停止“扫描全部”：当前这一行扫完就退出，不再往下扫。"""
        self._stop.set()

    @property
    def stopped(self):
        return self._stop.is_set()

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
            # 必须走 execute_ops：mux_ops() 里除真正的切动作外还夹带
            # {'driver':'delay'} 稳定延时，而 delay 由 execute_ops 处理、
            # 不在 TransportRegistry 注册，直接 reg.run() 会报“不支持的 driver”。
            ops = self._hook.mux_ops(slot) or []
            self.emitLog('切 mux 指令: %s' % _fmt_ops(ops))
            raw = hook_base.execute_ops(self._reg, ctx, ops,
                                        log=lambda m: self.emitLog(m))
            for drv, res in raw:
                if drv == 'delay':
                    continue
                self.emitLog('  ← %s 返回: %s' % (drv, transports.fmt_result(res)))
            self.result.emit(slot, '连接 ok，mux 前置已执行 (未做扫描)', None)
        except ConnectionError as e:
            self.emitLog('⚠ %s' % e)
            self.result.emit(slot, '无法连接: %s' % e, e)
        except Exception as e:  # noqa: BLE001
            self.emitLog('✗ mux 失败: %s' % e)
            self.result.emit(slot, 'mux 失败: %s' % e, e)
        finally:
            self.finished.emit()

    # ---- 全部槽位连续扫（连接不通即整组中止，不再往下白扫）----
    def scan_all_of(self, slots):
        try:
            slots = list(slots or [])
            ctx = self._ctx_factory()
            self.emitLog('=== 开始批量扫描：%d 个槽位 ===' % len(slots))
            self.emitLog('  目标 ip=%s  ssh=%s  超时 ssh=%ss rpc=%ss'
                         % (ctx.get('ip'), ctx.get('ssh_username'),
                            ctx.get('ssh_timeout'), ctx.get('rpc_timeout')))
            errors = 0
            done = 0
            first_err_logged = False
            for slot in slots:
                if self._stop.is_set():
                    break
                self.emitLog('  -> DOE%s' % slot)
                try:
                    self._scan_one(ctx, slot)
                except ConnectionError as e:
                    self.emitLog('⚠ 连接失败，中止后续扫描: %s' % e)
                    return
                except Exception as e:  # noqa: BLE001
                    # 关键：把失败原因**打进日志**，否则界面只显示“失败 N”
                    # 而看不到到底为什么失败。
                    self.result.emit(slot, '错误: %s' % e, e)
                    self.emitLog('  ✗ %s 失败: %s: %s'
                                 % (slot, type(e).__name__, e))
                    if not first_err_logged:
                        first_err_logged = True
                        self.emitLog('  —— 首个错误的完整堆栈（用于定位）——')
                        for ln in traceback.format_exc().splitlines():
                            self.emitLog('     %s' % ln)
                    errors += 1
                done += 1
            if self._stop.is_set():
                self.emitLog('■ 已停止：已扫 %d/%d，剩余 %d 个未扫'
                             % (done, len(slots), len(slots) - done))
            else:
                self.emitLog('全部槽位扫描完成（失败 %d / %d）' % (errors, len(slots)))
        finally:
            self.finished.emit()

    def _scan_one(self, ctx, slot):
        # 把停止标志放进 ctx：transports 的地址并发扫描会定期检查，
        # 这样点“停止”不必等整条总线 117 个地址扫完。
        ctx = dict(ctx or {})
        ctx['_cancel'] = self._stop
        t0 = time.time()
        address_list, _ = hook_base.run_slot_workflow(
            self._reg, ctx, self._hook, slot, log=lambda m: self.emitLog(m))
        dt = time.time() - t0
        text = ', '.join(address_list) if address_list else '(空)'
        if self._stop.is_set():
            text += '  (已停止)'
        # 结果也进日志：否则表格显示 “(空)” 时无法区分
        # “扫到了但确实没器件” 和 “根本没扫成功”。
        self.emitLog('  ✓ %s: %s  (%.2fs)' % (slot, text, dt))
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
        # 子线程诊断信息缓冲区（纯 Python，线程安全）。
        # 子线程只往里 append；主线程定时/收到信号后 drain 进日志框。
        # 这样避免子线程直接操作 Qt 控件（会 SIGSEGV）。
        self._dbg_buf = []
        self._dbg_lock = threading.Lock()
        self._dbg_timer = None

        self._build_ui()
        self._reload_projects()
        # 200ms 轮询一次，把子线程攒下的诊断行刷进日志框（主线程执行）
        self._dbg_timer = QTimer(self)
        self._dbg_timer.setInterval(200)
        self._dbg_timer.timeout.connect(self._drain_dbg)
        self._dbg_timer.start()

    # --------------------------------------------------- 跨线程诊断缓冲
    def _dbg_enqueue(self, msg):
        """子线程安全：只 append 到 list，不碰任何 Qt 对象。"""
        with self._dbg_lock:
            if len(self._dbg_buf) < 5000:      # 防爆
                self._dbg_buf.append(str(msg))

    def _drain_dbg(self):
        """主线程调用：把缓冲区内容写进日志框。"""
        if not self._dbg_buf:
            return
        with self._dbg_lock:
            items, self._dbg_buf = self._dbg_buf, []
        for m in items:
            self._log(m)

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        # --- 目标 / 项目（全部压在一行，紧凑）---
        cfg = QGroupBox('目标与扫描驱动')
        cfgL = QHBoxLayout(cfg)
        cfgL.setContentsMargins(8, 4, 8, 4)
        cfgL.setSpacing(6)

        cfgL.addWidget(QLabel('项目'))
        self.cbProject = QComboBox()
        self.cbProject.currentIndexChanged.connect(self._on_project_changed)
        cfgL.addWidget(self.cbProject)

        cfgL.addWidget(QLabel('IP'))
        self.edIp = QLineEdit('127.0.0.1')
        self.edIp.setMaximumWidth(150)
        cfgL.addWidget(self.edIp)

        # 端口不在 UI 上改：由各项目 SLOTS 的 port 字段决定（=工位 7801/7802）
        cfgL.addWidget(QLabel('端口'))
        self.lblPortInfo = QLabel('按项目表')
        self.lblPortInfo.setToolTip(
            '端口由各项目 SLOTS 的 port 字段决定（dut0=7801 / dut1=7802），此处不提供修改')
        self.lblPortInfo.setStyleSheet('color:#8a8a8a;')
        cfgL.addWidget(self.lblPortInfo)

        # SSH 账号/密码不在 UI 上改：直接取自项目文件的
        # default_ssh_user / default_ssh_password（同一份文件里配好，开箱即用）。
        cfgL.addWidget(QLabel('SSH'))
        self.lblSshInfo = QLabel('按项目文件')
        self.lblSshInfo.setToolTip(
            'SSH 账号/密码取自各项目的 default_ssh_user / default_ssh_password，'
            '此处不提供修改；改凭据请改 projects/*.py')
        self.lblSshInfo.setStyleSheet('color:#8a8a8a;')
        cfgL.addWidget(self.lblSshInfo)

        self.btnTest = QPushButton('连接测试')
        self.btnTest.clicked.connect(self._test_connect)
        cfgL.addWidget(self.btnTest)

        cfgL.addStretch(1)
        self.lblDrive = QLabel('空闲')
        cfgL.addWidget(self.lblDrive)
        root.addWidget(cfg)

        # --- 每槽位扫描表 ---
        tbl = QGroupBox('按槽位扫描')
        tl = QVBoxLayout(tbl)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btnScanAll = QPushButton('扫描全部槽位')
        self.btnScanAll.clicked.connect(self._scan_all)
        bar.addWidget(self.btnScanAll)
        self.btnStop = QPushButton('停止')
        self.btnStop.setToolTip('停止“扫描全部”：当前这一行扫完即退出')
        self.btnStop.setEnabled(False)
        self.btnStop.clicked.connect(self._stop_scan)
        bar.addWidget(self.btnStop)
        self.lblProbe = QLabel('当前扫描命令: -')
        bar.addWidget(self.lblProbe, 1)
        tl.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['扫描对象', '切 mux', '扫描', '探测到地址'])
        _hh = self.table.horizontalHeader()
        # 第0列“扫描对象”给足宽度（名字如 “dut0 i2c_8 通道6” 较长），
        # 并留出可拖拽余量；地址列自适应剩余宽度。
        _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 260)
        _hh.setMinimumSectionSize(80)
        _hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        _hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        _hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
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
        """写日志（**只能在主线程调用**）。

        Qt 控件不是线程安全的：在工作线程里 appendPlainText 会让 Qt 在子线程
        做文本排版（Harfbuzz），实测直接 SIGSEGV。这里加一道保护——若不是主线程，
        就转成队列塞进缓冲区，由 QTimer 在主线程刷出，避免再次崩溃。
        """
        if threading.current_thread() is not threading.main_thread():
            self._dbg_enqueue(msg)
            return
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
        # 端口不在 UI 上改：它按槽位写在项目表里。这里只把“本项目的端口”
        # 汇总显示出来，方便一眼确认，不提供编辑。
        self.lblPortInfo.setText(self._ports_hint())
        # SSH 凭据只做展示（实际值由 _make_ctx 从 PROJECT 读取并传给传输层）
        su = self._hook.PROJECT.get('default_ssh_user') or '-'
        sp = self._hook.PROJECT.get('default_ssh_password')
        self.lblSshInfo.setText('%s / %s' % (su, '已配置' if sp else '未配置'))
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
    def _slot_ports(self):
        """扫一遍当前项目的槽位，收集实际用到的 RPC 端口（用于界面提示）。"""
        ports = []
        for s in (getattr(self, 'slots', None) or []):
            try:
                for op in (self._hook.mux_ops(s) or []):
                    p = op.get('port')
                    if p is not None and int(p) not in ports:
                        ports.append(int(p))
            except Exception:
                pass
            try:
                p = (self._hook.probe(s) or {}).get('port')
                if p is not None and int(p) not in ports:
                    ports.append(int(p))
            except Exception:
                pass
        return sorted(ports)

    def _ports_hint(self):
        ports = self._slot_ports()
        if not ports:
            return '按项目表'
        return ' / '.join(str(p) for p in ports)

    def _default_port(self):
        """本项目的“主”端口：仅用于可达性预探测/连接测试的提示。

        真正的每步用哪个端口由槽位的 port 字段决定（见 hook_base 与 transports），
        所以这里取槽位里最小的那个端口作为代表，项目没写就退回 default_port。
        """
        ports = self._slot_ports()
        if ports:
            return ports[0]
        try:
            return int(self._hook.PROJECT.get('default_port'))
        except Exception:
            return 7801

    def _make_ctx(self):
        ip = self.edIp.text().strip()
        # SSH 凭据来自项目文件（不在 UI 上改），开箱即用。
        P = (self._hook.PROJECT if self._hook else {}) or {}
        ctx = {
            'ip': ip,
            # 不含具体端口：每一步动作自带的 port 优先（见 transports._resolve_port）
            'rpc_port': self._default_port(),
            'ssh_username': P.get('default_ssh_user') or 'mixadmin',
            'ssh_password': P.get('default_ssh_password') or '',
            # mux 切换是本地 RPC，正常几十 ms；给 5s 足够，别给 30s 拖死整轮。
            'rpc_timeout': 5,
            # detect_i2c 是在下位机本地扫一条总线，正常几十~几百 ms。
            # 给 3s 上限：超过就说明这条总线/SSH 有问题，早失败早暴露。
            'ssh_timeout': 3,
            # 单个槽位(一条总线)的扫描总预算。
            'scan_deadline': 5.0,
            # —— 调试诊断 ——
            # ssh_debug=True 时 transports 会把 SSH 细节(命令/rc/耗时/stdout)
            # 记录到 ctx['_dbg'] 列表。
            # 注意：**绝不能在子线程里直接碰 Qt 控件**（appendPlainText 会
            # 触发 Qt 文本排版，跨线程调用直接 SIGSEGV —— 实测崩在
            # QTextEngine::shapeTextWithHarfbuzzNG）。所以这里只给一个纯 Python
            # 的收集器，由主线程在收到信号后再写进日志框。
            'ssh_debug': True,
            '_dbg': self._dbg_buf,
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
            rpc = self._default_port()
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
        self.btnStop.setEnabled(True)
        self.lblDrive.setText('运行中...')
        t.start()

    def _stop_scan(self):
        """点“停止”：只置标志，工作线程在下一行开始前退出（不强杀线程）。"""
        wk = getattr(self, '_worker', None)
        if wk is None:
            return
        wk.request_stop()
        self.btnStop.setEnabled(False)
        self.lblDrive.setText('停止中...')
        self._log('■ 已请求停止，当前槽位扫完即结束')

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
        self.btnStop.setEnabled(False)
        wk = getattr(self, '_worker', None)
        self.lblDrive.setText('已停止' if (wk is not None and wk.stopped) else '完成')

    # ---------------------------------------------------------- actions
    def _test_connect(self):
        if not self._hook:
            return
        P = self._hook.PROJECT or {}
        ip = self.edIp.text().strip()
        hints = self._ports_hint()
        self._log('连接参数: ip=%s 端口=%s ssh_user=%s' % (
            ip, hints, P.get('default_ssh_user') or '-'))
        # 探测本项目的 RPC 端点 + SSH(22)
        ports = [int(p) for p in self._slot_ports()] or [self._default_port()]
        self._log(self._reach_report(ip, sorted(set(ports + [22]))))

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
