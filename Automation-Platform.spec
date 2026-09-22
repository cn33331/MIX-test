# -*- mode: python ; coding: utf-8 -*-

import os
import re
import shutil

current_dir = os.path.dirname(os.path.abspath(SPEC))

# 版本号注入：CI 通过 APP_VERSION 传入（通常是 git tag，如 v0.1.0）。
# Bundle 版本必须是 1~3 段点分数字，这里做一次收敛；本地不传时保持历史行为 0.0.0。
_app_version_raw = os.environ.get('APP_VERSION', '') or ''
_ver_match = re.match(r'\s*v?(\d+(?:\.\d+){0,2})', _app_version_raw)
app_version = _ver_match.group(1) if _ver_match else '0.0.0'
print(f'[Spec] APP_VERSION={_app_version_raw!r} -> CFBundleShortVersionString={app_version}')


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
    ],
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