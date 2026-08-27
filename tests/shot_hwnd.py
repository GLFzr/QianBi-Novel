# -*- coding: utf-8 -*-
"""抓取任意可见窗口（PrintWindow，可后台）"""
import ctypes
import sys
from ctypes import wintypes
import ctypes as C

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def find_window(substr):
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = []
    def cb(hwnd, lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0 and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if substr.lower() in buf.value.lower():
                found.append((hwnd, buf.value))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def capture(hwnd, out, scale=1.0):
    user32.SetProcessDPIAware()
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, C.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        print("bad client size", w, h)
        return False
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT
    saved = False
    if ok:
        from PIL import Image
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biWidth = w
        bmi.biHeight = -h
        data = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mdc, bmp, 0, h, data, ctypes.byref(bmi), 0)
        # GetDIBits 32bpp 返回 BGRA 字节序，需换回 RGB（否则整图 R/B 反转）
        img = Image.frombytes("RGBA", (w, h), data.raw).convert("RGB")
        r, g, b = img.split()
        img = Image.merge("RGB", (b, g, r))
        if scale != 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        img.save(out)
        saved = True
        print("saved", out, img.size)
    else:
        print("PrintWindow failed")
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return saved


if __name__ == "__main__":
    title = sys.argv[1]
    out = sys.argv[2]
    wins = find_window(title)
    if not wins:
        print("window not found:", title)
        sys.exit(1)
    capture(wins[0][0], out)
