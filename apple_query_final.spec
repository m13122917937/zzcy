#!/usr/bin/env python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt6 核心模块
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',

        # 项目主模块
        'apple_search_api',
        'environment_config',

        # curl_cffi (关键模块)
        'curl_cffi',
        'curl_cffi._wrapper',
        'curl_cffi._constants',
        'curl_cffi._platform',
        'curl_cffi._version',
        'curl_cffi.constants',
        'curl_cffi.errors',
        'curl_cffi.cookies',
        'curl_cffi.models',
        'curl_cffi.requests',
        'curl_cffi.requests.errors',

        # pandas 和 Excel 处理
        'pandas',
        'pandas._libs.tslibs.timedeltas',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.skiplist',
        'pandas._libs.algos',
        'pandas._libs.hashtable',
        'pandas._libs.tslibs.conversion',
        'pandas._libs.lib',
        'pandas._libs.parsers',
        'openpyxl',
        'openpyxl.cell._writer',

        # PIL/Pillow
        'PIL.Image',
        'PIL._imaging',
        'PIL._tkinter_finder',

        # 网络库
        'requests',
        'aiohttp',
        'aiohttp.helpers',
        'aiohttp.http_exceptions',
        'aiohttp.abc',
        'multidict._multidict_py',
        'async_timeout',
        'charset_normalizer',

        # 其他依赖
        'psutil',
        'psutil._common',
        'psutil._psutil_windows',

        # 系统模块 (关键)
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
        'traceback',
        'threading',
        'concurrent',
        'concurrent.futures',
        'multiprocessing',

        # BeautifulSoup 和 lxml
        'bs4',
        'lxml',
        'lxml._elementpath',
        'lxml.etree',

        # pytz
        'pytz',
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
    a.zipfiles,
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
    icon='honor_logo.ico'
)
