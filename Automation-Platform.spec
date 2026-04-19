# -*- mode: python ; coding: utf-8 -*-

import os

# 获取当前目录（项目根目录）
current_dir = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(current_dir, 'main_application.py')],
    pathex=[current_dir],
    binaries=[],
    datas=[
        (os.path.join(current_dir, 'mix'), 'mix'),
        (os.path.join(current_dir, 'uart'), 'uart'),
        (os.path.join(current_dir, 'ui'), 'ui')
    ],
    hiddenimports=['__future__', 'zmq', 'ujson', 'ipaddress', 'uuid', 'serial', 'PyQt6', 'serial', 'zmq'],
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
)