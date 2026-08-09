# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

app_dir = Path(SPECPATH).resolve()
repo_dir = app_dir.parent
entrypoint = app_dir / 'kindle_sender.py'
icon_path = app_dir / 'build-assets' / 'kindle-book-sender.ico'
shared_key = repo_dir / 'Handoff' / 'keys' / 'kindle_handoff_rsa'
datas = [(str(shared_key), 'Handoff/keys')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('paramiko')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(entrypoint)],
    pathex=[str(app_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='Kindle Book Sender',
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
    icon=[str(icon_path)],
)
