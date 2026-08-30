# -*- coding: utf-8 -*-
"""打包版冒烟探针（封装计划 T1.3）：对 dist 产物做启动验证

用法：python tests/probe_packaged.py --exe dist/QianBi-Novel/QianBi-Novel.exe
流程：启动 exe → 60s 内出现主窗口（FindWindowW 标题匹配）→ 存活 5s → 终止
门禁：build_release.py 在发版流水线中调用；--skip-probe 仅供调试
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time

TITLE = "千笔一文 Novel"


def find_window() -> int:
    user32 = ctypes.windll.user32
    return user32.FindWindowW(None, TITLE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="打包产物 exe 路径")
    args = ap.parse_args()

    if not os.path.exists(args.exe):
        print(f"[FAIL] 产物不存在: {args.exe}")
        return 1

    print(f"[.. ] 启动打包版: {args.exe}")
    proc = subprocess.Popen([args.exe], cwd=os.path.dirname(args.exe))
    try:
        deadline = time.time() + 60
        hwnd = 0
        while time.time() < deadline:
            hwnd = find_window()
            if hwnd:
                break
            if proc.poll() is not None:
                print(f"[FAIL] 进程提前退出（code={proc.returncode}）")
                return 1
            time.sleep(0.5)
        if not hwnd:
            print("[FAIL] 60s 内未出现主窗口")
            return 1
        print("[OK ] 主窗口出现")

        time.sleep(5)
        if proc.poll() is not None:
            print(f"[FAIL] 启动 5s 内进程退出（code={proc.returncode}）")
            return 1
        print("[OK ] 存活 5s，无崩溃")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
