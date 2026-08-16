# -*- coding: utf-8 -*-
"""千笔一文 Novel — 真实机器 UI 驱动工具

用途：对运行中的应用窗口做 UIA 感知 + PostMessage 合成点击 + PrintWindow 截图，
绕过窗口遮挡（夸克全屏浏览器）与前台限制，模拟真实用户操作。

用法（PowerShell）：
  @"
  import sys; sys.path.insert(0, r'G:\ai\酒馆\qianbi-novel\.venv\Lib\site-packages')
  import tests.ui_drive as ui
  ui.find_app()
  ui.click(462, 219)
  ui.shot('G:/ai/酒馆/qianbi-novel/tests_output/xxx.png')
  ui.find_button('开始')
  "@ | .venv\Scripts\python.exe -

注意：
- 第一次点击只激活窗口（Windows 行为），第二次才触发；click() 默认连点多次。
- PrintWindow 截图坐标 = 窗口坐标（从窗口左上角起，含标题栏）。
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

APP_TITLE = "千笔一文 Novel"
_app_hwnd = None


# ---------- 窗口 ----------

def find_app(title: str = APP_TITLE):
    """枚举顶层窗口，返回应用 hwnd（缓存）"""
    global _app_hwnd
    found = []

    def cb(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == title:
            found.append(hwnd)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    if found:
        _app_hwnd = found[0]
    return _app_hwnd


def app_rect():
    r = wintypes.RECT()
    user32.GetWindowRect(_app_hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def window_at(sx, sy):
    """屏幕点 (sx,sy) 上最顶层窗口的标题"""
    hwnd = user32.WindowFromPoint(wintypes.POINT(sx, sy))
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or f"(hwnd {hwnd})"


def clear_occluders():
    """清障：最小化夸克/Chrome 系全屏窗口，确保应用可被点击。

    夸克（DSH 宿主）会全屏恢复并盖住应用；其 Chrome_RenderWidgetHostHWND
    渲染子窗口也会拦截鼠标。点击前调用本函数。
    """
    try:
        user32.ShowWindow(199240, 6)  # 夸克主窗（DSH）
    except Exception:
        pass
    user32.ShowWindow(_app_hwnd, 9)  # 应用 restore

    def cb(hwnd, lparam):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == "Chrome_WidgetWin_1" and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left >= 1800 and r.bottom - r.top >= 900:
                user32.ShowWindow(hwnd, 6)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    time.sleep(0.6)


def ensure_point(sx, sy, retries=3):
    """确保屏幕点 (sx,sy) 最顶层是应用窗口；被遮挡时清障重试。返回是否就绪"""
    for _ in range(retries):
        if window_at(sx, sy) == APP_TITLE:
            return True
        clear_occluders()
    return window_at(sx, sy) == APP_TITLE


# ---------- 点击 ----------

def post_click(sx, sy, n=3, gap=0.9):
    """PostMessage 合成点击（绕过遮挡/前台）。坐标 = 屏幕坐标。

    n>=2 时第一次点击用于激活窗口（Qt 在窗口未激活时丢弃首击）。
    """
    for i in range(n):
        p = wintypes.POINT(sx, sy)
        user32.ScreenToClient(_app_hwnd, ctypes.byref(p))
        lparam = (p.y << 16) | (p.x & 0xFFFF)
        user32.PostMessageW(_app_hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
        time.sleep(0.08)
        user32.PostMessageW(_app_hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
        time.sleep(gap)


def click(sx, sy, n=3):
    post_click(sx, sy, n=n)


# ---------- UIA ----------

def _desktop():
    from pywinauto import Desktop
    return Desktop(backend="uia")


def find_button(title):
    """在应用窗口树里找按钮，返回 (center_x, center_y, elem)；找不到返回 None"""
    win = _desktop().window(handle=_app_hwnd)
    try:
        el = win.child_window(title=title, control_type="Button")
        rr = el.rectangle()
        return ((rr.left + rr.right) // 2, (rr.top + rr.bottom) // 2, el)
    except Exception:
        return None


def click_button(title, n=3):
    """找到按钮并点击，返回是否成功"""
    hit = find_button(title)
    if not hit:
        return False
    click(hit[0], hit[1], n=n)
    return True


def dump_buttons():
    """列出窗口内所有按钮（调试用）"""
    win = _desktop().window(handle=_app_hwnd)
    for el in win.descendants(control_type="Button"):
        rr = el.rectangle()
        print(f"Button [{el.window_text()}] ({rr.left},{rr.top})-({rr.right},{rr.bottom})")


# ---------- 截图 ----------

def shot(path, scale=1.0):
    """PrintWindow 截取应用窗口，保存 PNG。返回 (w, h)"""
    from PIL import Image

    x, y, w, h = app_rect()
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    user32.PrintWindow(_app_hwnd, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    if scale != 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img.save(path)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return w, h


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "buttons":
        find_app()
        dump_buttons()
