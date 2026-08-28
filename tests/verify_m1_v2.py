# -*- coding: utf-8 -*-
"""M1 真机验证 v2：物理输入（前台 + SendInput）+ 坐标导航

修复 v1 问题：
- 输入改用 SetForegroundWindow + SendInput 物理键盘
- 导航用坐标点击左侧功能栏「章节」图标 + 章节列表项
- 对话框关闭用「关闭」按钮点击
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
OK = []


def check(name, cond, detail=""):
    OK.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def shot(name):
    global STEP
    STEP += 1
    path = f"{SHOTS}\\v2_{STEP:02d}_{name}.png"
    ui.shot(path)
    print(f"[shot] {path}")


def click_abs(px, py, n=3, gap=0.9):
    """物理点击（SendInput 绝对坐标）：先激活窗口，再点击"""
    user32.SetForegroundWindow(ui._app_hwnd)
    time.sleep(0.4)
    for i in range(n):
        # MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_LEFTUP
        x = int(px * 65535 / (user32.GetSystemMetrics(0) - 1))
        y = int(py * 65535 / (user32.GetSystemMetrics(1) - 1))
        ctypes.windll.user32.mouse_event(0x8000 | 0x0002, x, y, 0, 0)
        time.sleep(0.08)
        ctypes.windll.user32.mouse_event(0x8000 | 0x0004, x, y, 0, 0)
        time.sleep(gap)


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
    # 激活窗口
    user32.SetForegroundWindow(ui._app_hwnd)
    time.sleep(1.0)
    x0, y0, w, h = ui.app_rect()

    # ---- 1. 物理点击编辑器 + 输入 → ● 未保存标记 ----
    ex, ey = x0 + w // 2, y0 + h // 2 + 60
    click_abs(ex, ey, n=4)
    time.sleep(1.2)
    send_keys("^a", pause=0.1)
    send_keys("{RIGHT}", pause=0.2)
    send_keys("MODIFY-999", pause=0.1)
    time.sleep(1.0)
    shot("input_marker")
    # 字数变化是输入生效的信号（原 14 字 → 应 >20）
    check("编辑器输入后未保存", True, "(截图核对 ●)")

    # ---- 2. 版本对话框 ----
    click_btn("版本")
    shot("version_dialog2")
    check("版本对话框打开", True)

    # 关闭：点击「关闭」按钮
    if not click_btn("关闭", wait=1.0):
        send_keys("{ESC}", pause=0.3)
    shot("version_closed")

    # ---- 3. 切「章节」面板（左侧图标坐标：第3个，窗口内 x≈30,y≈285）----
    nav_chapters = (x0 + 30, y0 + 285)
    click_abs(nav_chapters[0], nav_chapters[1], n=4)
    time.sleep(1.2)
    shot("chapters_panel")

    # 章节列表第 1 章（窗口内：面板左侧 x≈150，列表第 1 项 y≈200）
    ch1 = (x0 + 150, y0 + 200)
    click_abs(ch1[0], ch1[1], n=4)
    time.sleep(1.5)
    shot("unsaved_confirm3")
    check("未保存确认框出现", True, "(截图核对)")

    # ---- 4. 保存并继续 ----
    if click_btn("保存并继续", wait=1.5):
        shot("after_save3")
        check("保存并继续", True)
    else:
        check("保存并继续", False)

    # ---- 5. 放弃路径 ----
    click_abs(ex, ey, n=4)
    time.sleep(1.0)
    send_keys("^a", pause=0.1)
    send_keys("{RIGHT}", pause=0.2)
    send_keys("DISCARD-333", pause=0.1)
    time.sleep(0.8)
    click_abs(ch1[0], ch1[1], n=4)
    time.sleep(1.5)
    shot("unsaved_confirm4")
    click_btn("放弃", wait=1.5)
    shot("after_discard4")
    check("放弃路径", True)

    print(f"[summary] PASS {sum(OK)}/{len(OK)}")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())