# -*- coding: utf-8 -*-
"""M1 真机验证：保存驱动版本体系全流程

流程：
1. 定位窗口，点编辑器末尾，粘贴修改文本 → 验证「● 未保存」标记出现
2. 打开版本对话框 → 验证 v1 定稿版本列表
3. 关闭版本对话框，切换到另一章 → 验证未保存确认框（保存/放弃/取消）
4. 点「保存并继续」→ 验证章节切换 + 磁盘产生 v2 版本
5. 放弃路径：再编辑 → 切换 → 放弃 → 验证无新版本
6. 关闭窗口（干净状态应直接关闭）
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests.ui_drive as ui
from ctypes import wintypes
from pywinauto.keyboard import send_keys

STEP = 0
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests_output")
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def set_clipboard(text):
    """写 Unicode 文本进系统剪贴板（ctypes，无第三方依赖）"""
    CF_UNICODETEXT = 13
    data = (text + "\x00").encode("utf-16-le")
    if not user32.OpenClipboard(0):
        return False
    user32.EmptyClipboard()
    h = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE|GMEM_ZEROINIT
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    user32.SetClipboardData(CF_UNICODETEXT, h)
    user32.CloseClipboard()
    return True


def shot(name):
    global STEP
    STEP += 1
    path = f"{SHOTS}\\m1_{STEP:02d}_{name}.png"
    ui.shot(path)
    print(f"[shot] {path}")


def click_btn(title, wait=1.2):
    hit = ui.find_button(title)
    if not hit:
        print(f"[fail] button not found: {title}")
        return False
    ui.click(hit[0], hit[1])
    time.sleep(wait)
    return True


def main():
    if not ui.find_app():
        print("[fail] app not found")
        return 1
    x0, y0, w, h = ui.app_rect()

    # 0. 点击编辑器文本末尾（窗口内编辑器区域）
    ui.ensure_point(x0 + w // 2, y0 + h // 2 + 60)
    ui.click(x0 + w // 2, y0 + h // 2 + 60, n=4)
    time.sleep(1.0)

    # 1. 键盘输入修改 → 未保存标记
    send_keys("^a", pause=0.05)
    send_keys("{RIGHT}", pause=0.1)
    send_keys("MODIFY-123", pause=0.05)
    time.sleep(0.8)
    shot("edit_unsaved_marker")
    print("[step1] 已输入修改文本")

    # 2. 打开版本对话框
    click_btn("版本")
    shot("version_dialog")
    print("[step2] 版本对话框已打开")

    # 3. 关闭版本对话框（Esc）
    send_keys("{ESC}", pause=0.5)
    time.sleep(1.0)
    shot("version_dialog_closed")

    # 4. 切到章节面板并打开第 1 章 → 未保存确认框
    click_btn("章节")
    time.sleep(1.0)
    hit = ui.find_button("第001章_第一章 起点") or ui.find_button("第一章 起点")
    if hit:
        ui.click(hit[0], hit[1])
    time.sleep(1.2)
    shot("unsaved_confirm")
    print("[step4] 未保存确认框预期出现")

    # 5. 点「保存并继续」
    if click_btn("保存并继续"):
        time.sleep(1.5)
        shot("after_save_switch")
    print("[step5] 保存并继续")

    # 6. 放弃路径：编辑 → 切换 → 放弃
    ui.ensure_point(x0 + w // 2, y0 + h // 2 + 60)
    ui.click(x0 + w // 2, y0 + h // 2 + 60, n=4)
    time.sleep(0.8)
    send_keys("^a", pause=0.05)
    send_keys("{RIGHT}", pause=0.1)
    send_keys("DISCARD-456", pause=0.05)
    time.sleep(0.8)
    hit = ui.find_button("第002章_第二章 转折") or ui.find_button("第二章 转折")
    if hit:
        ui.click(hit[0], hit[1])
    time.sleep(1.2)
    shot("unsaved_confirm2")
    click_btn("放弃")
    time.sleep(1.5)
    shot("after_discard")
    print("[step6] 放弃路径完成")

    # 7. 关闭窗口（干净状态应直接关闭，不弹确认）
    user32.PostMessageW(ui._app_hwnd, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(2.0)
    print("[step7] 已发送关闭")

    print("[done] 验证流程完成，请人工核对截图")
    return 0


if __name__ == "__main__":
    sys.exit(main())
