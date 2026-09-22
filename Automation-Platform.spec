# -*- mode: python ; coding: utf-8 -*-

import os
import re
import shutil
import sys

current_dir = os.path.dirname(os.path.abspath(SPEC))

# 版本号注入：CI 通过 APP_VERSION 传入（通常是 git tag，如 v0.1.0）。
# Bundle 版本必须是 1~3 段点分数字，这里做一次收敛；本地不传时保持历史行为 0.0.0。
_app_version_raw = os.environ.get('APP_VERSION', '') or ''
_ver_match = re.match(r'\s*v?(\d+(?:\.\d+){0,2})', _app_version_raw)
app_version = _ver_match.group(1) if _ver_match else '0.0.0'
print(f'[Spec] APP_VERSION={_app_version_raw!r} -> CFBundleShortVersionString={app_version}')

# 插件依赖注入：plugins/ 是在打包「完成之后」以普通文件复制进 .app 的（见下方
# post_build_copy_plugins），不参与 PyInstaller 的导入分析。插件用到而主程序没用到的
# 模块，若不明式声明为 hiddenimports，是否随包就取决于构建环境的偶然因素。
# 真实事故：i2c_scan_plugin/transports.py 顶层 import concurrent.futures，主程序不用
# concurrent；x86_64 runner 的依赖图恰好把它带了进来，arm64 runner 没有，于是 arm64
# 产物一打开就报「插件缺少 concurrent」。这里按插件入口做可达性扫描，自动补齐。
sys.path.insert(0, current_dir)
from plugin_deps import external_modules as _plugin_external_modules  # noqa: E402

_plugin_hiddenimports = _plugin_external_modules(current_dir)
print(f'[Spec] 插件可达外部依赖 {len(_plugin_hiddenimports)} 个: '
      f'{", ".join(_plugin_hiddenimports)}')


def post_build_copy_plugins():
    """
    打包完成后自动复制 plugins 目录到 app 包内的 MacOS 目录下
    """
    # 目标路径：app包内的 MacOS/plugins
    dist_dir = os.path.join(current_dir, 'dist')
    app_path = os.path.join(dist_dir, 'Automation-Platform.app')
    macos_dir = os.path.join(app_path, 'Contents', 'MacOS')
    plugins_src = os.path.join(current_dir, 'plugins')
    plugins_dst = os.path.join(macos_dir, 'plugins')
    
    # 删除旧的 plugins 目录（如果存在）
    if os.path.exists(plugins_dst):
        shutil.rmtree(plugins_dst)
    
    # 复制 plugins 目录
    shutil.copytree(plugins_src, plugins_dst)
    print(f"[Post-Build] 已复制 plugins 目录到: {plugins_dst}")

a = Analysis(
    [os.path.join(current_dir, 'main_application.py')],
    pathex=[current_dir],
    binaries=[],
    datas=[],
    hiddenimports=[
        '__future__',
        'zmq',
        'ujson',
        'ipaddress',
        'uuid',
        'serial',
        'serial.tools.list_ports',
        'PyQt6.uic',
        'PyQt6.uic.load_ui',
        'PyQt6.uic.uiparser',
        'PyQt6.uic.ui_file',
        'PyQt6.uic.Loader',
        'PyQt6.uic.Loader.loader',
        'logging',
        'logging.handlers',
        'tty',
        'termios',
    ] + [m for m in _plugin_hiddenimports if m not in {
        '__future__', 'zmq', 'ujson', 'ipaddress', 'uuid', 'serial',
        'logging', 'tty', 'termios',
    }],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Automation-Platform',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(current_dir, 'static', 'sword.icns')],
)
app = BUNDLE(
    exe,
    name='Automation-Platform.app',
    icon=os.path.join(current_dir, 'static', 'sword.icns'),
    bundle_identifier=None,
    info_plist={
        'CFBundleShortVersionString': app_version,
        'CFBundleVersion': app_version,
    },
)

# 打包完成后自动复制 plugins 目录
post_build_copy_plugins()