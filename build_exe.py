# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：生成单文件 exe（千笔一文 Novel）"""
import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",                # 单文件
        "--windowed",               # 无控制台窗口
        "--name", "QianBi-Novel",
        "--icon", os.path.join("assets", "icon.ico"),
        # 运行时资源：QML 界面文件与图标（.py 模块由依赖分析自动收集）
        "--add-data", f"app/ui/qml{os.pathsep}app/ui/qml",
        "--add-data", f"assets{os.pathsep}assets",
        "--hidden-import", "httpx",
        "--hidden-import", "httpcore",
        "--hidden-import", "certifi",
        "--hidden-import", "PySide6.QtQml",
        "--hidden-import", "PySide6.QtQuick",
        "--hidden-import", "PySide6.QtQuickControls2",
        "--collect-submodules", "app",
        "run.py",
    ]
    print("执行:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode == 0:
        exe = os.path.join(ROOT, "dist", "QianBi-Novel.exe")
        print(f"\n打包成功: {exe}")
        if os.path.exists(exe):
            size_mb = os.path.getsize(exe) / 1024 / 1024
            print(f"文件大小: {size_mb:.1f} MB")
    else:
        print("\n打包失败")
        sys.exit(1)


if __name__ == "__main__":
    build()
