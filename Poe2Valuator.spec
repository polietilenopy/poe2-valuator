# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('build_to_filter.py', '.'), ('rune_reward.py', '.')]
binaries = []
hiddenimports = ['build_to_filter', 'rune_reward', 'PIL.ImageGrab', 'PIL.ImageTk', 'winrt.runtime', 'winrt.windows.media.ocr', 'winrt.windows.globalization', 'winrt.windows.graphics.imaging', 'winrt.windows.storage.streams', 'winrt.windows.foundation', 'winrt.windows.foundation.collections', 'winrt.windows.storage']
hiddenimports += collect_submodules('winrt')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('winrt')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['poe2_valuator_overlay.py'],
    pathex=[],
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
    name='Poe2Valuator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
)
