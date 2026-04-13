# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/gdlocal/Desktop/myCode/myAPP/MIX-test/main_application.py'],
    pathex=['/Users/gdlocal/Desktop/myCode/myAPP/MIX-test'],
    binaries=[],
    datas=[
        ('/Users/gdlocal/Desktop/myCode/myAPP/MIX-test/mix', 'mix'),
        ('/Users/gdlocal/Desktop/myCode/myAPP/MIX-test/uart', 'uart')
    ],
    hiddenimports=['__future__', 'zmq', 'ujson', 'ipaddress', 'uuid', 'serial'],
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
    icon=['/Users/gdlocal/Desktop/myCode/myAPP/MIX-test/static/sword.icns'],
)
app = BUNDLE(
    exe,
    name='Automation-Platform.app',
    icon='/Users/gdlocal/Desktop/myCode/myAPP/MIX-test/static/sword.icns',
    bundle_identifier=None,
)
