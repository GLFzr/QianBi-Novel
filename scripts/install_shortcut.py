# -*- coding: utf-8 -*-
"""在桌面创建「千笔一文 Novel」快捷方式（指向 dist/QianBi-Novel.exe）"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "QianBi-Novel.exe")
APP_NAME = "千笔一文 Novel"
APP_DESC = "千笔一文 Novel — AI 网文自动写作台"


def main():
    if not os.path.exists(EXE):
        print("EXE_MISSING", EXE)
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
    sc.TargetPath = EXE
    sc.WorkingDirectory = os.path.dirname(EXE)
    sc.IconLocation = f"{EXE},0"
    sc.Description = APP_DESC
    sc.Save()

    if os.path.exists(lnk_path):
        print("SHORTCUT_OK", lnk_path)
    else:
        print("SHORTCUT_FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
