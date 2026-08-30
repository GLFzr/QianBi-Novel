# -*- coding: utf-8 -*-
"""【已废弃】旧 onefile 打包脚本（封装计划 T1.1：onefile 启动慢/杀软误报高，收编为 onedir）

统一入口：python scripts/build_release.py
"""
import os
import subprocess
import sys

print("[已废弃] build_exe.py（onefile）已收编为 onedir 流水线。")
print("统一入口：python scripts/build_release.py")
sys.exit(subprocess.call([sys.executable, os.path.join("scripts", "build_release.py")] + sys.argv[1:]))
