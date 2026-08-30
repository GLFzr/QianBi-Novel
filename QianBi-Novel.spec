# -*- mode: python ; coding: utf-8 -*-
# 千笔一文 Novel — PyInstaller 打包规格（onedir + 安装器/便携包路线，封装计划 T1.1）
#
# 约定：
# - 版本单一来源 app/__init__.py: __version__，version_info.txt 由 scripts/build_release.py 生成
# - upx 必须为 False（杀软误报首要来源，见计划 §4）
# - 数据资产：QML 界面 / assets 图标 / presets 题材 JSON（应用运行必需）
import os
import sys

sys.path.insert(0, os.getcwd())   # 让 spec 能读取 app.__version__

from PyInstaller.utils.hooks import collect_submodules  # noqa: E402
from app import __version__  # noqa: E402

hiddenimports = [
    'httpx', 'httpcore', 'h11', 'certifi', 'anyio',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickControls2', 'PySide6.QtNetwork',
    'keyring.backends.Windows',
]
hiddenimports += collect_submodules('app')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/ui/qml', 'app/ui/qml'),
        ('assets', 'assets'),
        ('app/presets', 'app/presets'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',            # 未使用（PySide6 应用）
        'matplotlib', 'numpy', 'pandas',  # 未使用的重依赖（防未来误装被吸入）
        'IPython', 'jedi',
        'pydoc_data',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,               # onedir：二进制放 COLLECT
    name='QianBi-Novel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                           # 封装计划 §4：杀软误报
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
    version='version_info.txt' if os.path.exists('version_info.txt') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='QianBi-Novel',
)
