# -*- coding: utf-8 -*-
"""删除书籍的回收站通道（0.20.1 书架删书）。

纪律：应用侧**永不**永久删除用户书稿——目录一律进 Windows 回收站
（SHFileOperationW + FOF_ALLOWUNDO），用户可以在回收站自行还原。
删错书的最坏后果从「丢稿」降级为「去回收站捞」。
"""
import ctypes
import logging
import os

logger = logging.getLogger("qianbi.trash")


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


FO_DELETE = 3
FOF_ALLOWUNDO = 0x40        # 进回收站（而不是永久删除）——本模块的立身之本
FOF_NOCONFIRMATION = 0x10   # 应用外已做两步确认，不再弹系统确认框
FOF_SILENT = 0x4
FOF_NOERRORUI = 0x400


def _sh_delete(path: str) -> None:
    """内核调用点（单测打桩位）。失败抛 OSError，绝不退化为永久删除。"""
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    # SHFileOperation 的路径表以双 NUL 结尾
    op.pFrom = path + "\x00"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    code = int(ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)))
    if code != 0 or op.fAnyOperationsAborted:
        raise OSError(
            f"移入回收站失败（SHFileOperationW code={code}, aborted={bool(op.fAnyOperationsAborted)}）: {path}")


def send_to_recycle(path: str) -> None:
    """把目录移入 Windows 回收站。目标必须是存在的目录；失败抛 OSError。"""
    if os.name != "nt":
        raise OSError("回收站删除仅支持 Windows")
    full = os.path.abspath(path)
    if not os.path.isdir(full):
        raise OSError(f"目标目录不存在: {full}")
    _sh_delete(full)
    logger.info("已移入回收站: %s", full)
