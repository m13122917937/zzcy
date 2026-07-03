#!/usr/bin/env python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt6 相关隐藏导入
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',

        # 项目导入
        'apple_search_api',

        # 依赖库隐藏导入
        'pandas',
        'pandas.core',
        'pandas.core.frame',
        'pandas.io.formats.excel',
        'pandas.io.formats.format',

        'psutil',
        'requests',
        'aiohttp',
        'openpyxl',

        # curl_cffi 相关
        'curl_cffi',
        'curl_cffi.requests',
        'curl_cffi.requests.cookies',

        # PIL/Pillow 相关
        'PIL',
        'PIL.Image',

        # 系统模块
        'ctypes',
        '_ctypes',
        'struct',
        'json',
        'base64',
        'uuid',
        'datetime',
        'subprocess',
        'sys',
        'os',
        'time',
        'logging',
        'traceback'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthooks/pyi_rth_ctypes_fix.py'],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy',
    ],
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='apple_query',
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
)
