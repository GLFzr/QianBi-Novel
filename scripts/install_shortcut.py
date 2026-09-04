# -*- coding: utf-8 -*-
"""在桌面创建「千笔一文 Novel」快捷方式

目标按优先级取第一个存在的：安装版 → onedir 构建 → 旧的单文件构建。
选中的路径与版本号会打印出来——「桌面图标到底启动的是哪一版」不该靠猜。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_NAME = "千笔一文 Novel"
APP_DESC = "千笔一文 Novel — AI 网文自动写作台"


def _candidates():
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    return [
        os.path.join(local, "Programs", "QianBi-Novel", "QianBi-Novel.exe"),   # 安装版
        os.path.join(ROOT, "dist", "QianBi-Novel", "QianBi-Novel.exe"),        # onedir
        os.path.join(ROOT, "dist", "QianBi-Novel.exe"),                        # 旧的单文件
    ]


def resolve_exe():
    for path in _candidates():
        if os.path.isfile(path):
            return path
    return ""


def main():
    exe = resolve_exe()
    if not exe:
        print("EXE_MISSING（三个候选位置都没有 exe）")
        for path in _candidates():
            print("  ", path)
        sys.exit(1)
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):  # OneDrive 桌面等回退
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            desktop = winreg.QueryValueEx(k, "Desktop")[0]
    lnk_path = os.path.join(desktop, f"{APP_NAME}.lnk")

    sc = shell.CreateShortcut(lnk_path)
    sc.TargetPath = exe
    sc.WorkingDirectory = os.path.dirname(exe)
    sc.IconLocation = f"{exe},0"
    sc.Description = APP_DESC
    sc.Save()

    if os.path.exists(lnk_path):
        print("SHORTCUT_OK", lnk_path)
        print("TARGET", exe, "v" + _version_of(exe))
    else:
        print("SHORTCUT_FAIL")
        sys.exit(1)


def _version_of(path):
    import win32api
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return ".".join(str(x) for x in (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF))
    except Exception:  # noqa: BLE001
        return "未知"


if __name__ == "__main__":
    main()
