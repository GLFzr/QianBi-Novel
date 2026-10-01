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

# 凭据后端按平台惰性选择：漏收时导入不报错、行为悄悄退化成 Fail*Keyring（读写全废），
# 所以按平台点名——Windows 是凭据管理器，macOS 是钥匙串，两者不同包。
_KEYRING_BACKEND = {'win32': 'keyring.backends.Windows',
                    'darwin': 'keyring.backends.macOS'}.get(sys.platform)

hiddenimports = [
    'httpx', 'httpcore', 'h11', 'certifi', 'anyio',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickControls2', 'PySide6.QtNetwork',
    *([_KEYRING_BACKEND] if _KEYRING_BACKEND else []),
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
        ('app/vendor/lieflat-less-ai-tone', 'app/vendor/lieflat-less-ai-tone'),
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
    # EXE 只有 Windows 认 icon/version_info；macOS 的图标在下面的 BUNDLE 里给
    icon=[os.path.join('assets', 'icon.ico')] if sys.platform == 'win32' else None,
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

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='QianBi-Novel.app',
        icon=os.path.join('assets', 'icon.icns'),
        bundle_identifier='com.glfzr.qianbinovel',
        version=__version__,
        info_plist={
            'CFBundleShortVersionString': __version__,
            'NSHighResolutionCapable': True,
            'NSPrincipalClass': 'NSApplication',
            'LSMinimumSystemVersion': '12.0',
            'NSHumanReadableCopyright': 'MIT License. Copyright (c) 2026 GLFzr',
        },
    )
