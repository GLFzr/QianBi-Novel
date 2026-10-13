# -*- coding: utf-8 -*-
"""删除书籍的系统垃圾桶通道（0.20.1 书架删书）。

纪律：应用侧**永不**永久删除用户书稿——目录一律进系统垃圾桶
（Windows 回收站：SHFileOperationW + FOF_ALLOWUNDO；macOS 废纸篓：移入 .Trash），
用户可以在那里自行还原。删错书的最坏后果从「丢稿」降级为「去垃圾桶捞」。

两侧同一条纪律：**失败就抛 OSError，绝不退化成永久删除**——移动没成功，书必须还在原地。
"""
import ctypes
import logging
import os
import shutil
import sys

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


# ---------- macOS 废纸篓 ----------

def _volume_root(path: str) -> str:
    """path 所在卷的根（挂载点）。macOS 每个卷有自己的 .Trash，跨卷要进那个卷的"""
    p = os.path.abspath(path)
    if not os.path.isdir(p):
        p = os.path.dirname(p)
    while not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _trash_dir_for(path: str) -> str:
    """该进哪个废纸篓：默认 ~/.Trash；书稿在别的卷上时用那个卷自己的 .Trash

    卷内 .Trash 不存在或不可写时回落 ~/.Trash（shutil.move 会跨卷搬，
    搬不动就抛错——不搬走也不删，书留在原地才是本模块要保的底线）。
    """
    home = os.path.expanduser("~")
    home_trash = os.path.join(home, ".Trash")
    vol = _volume_root(path)
    if vol and vol != _volume_root(home):
        cand = os.path.join(vol, ".Trash")
        if os.path.isdir(cand) and os.access(cand, os.W_OK):
            return cand
    return home_trash


def _unique_dest(dest: str) -> str:
    """重名不覆盖：废纸篓里同名的东西不能被后来者吃掉（Finder 的做法）"""
    if not os.path.exists(dest):
        return dest
    base, n = dest, 1
    while os.path.exists("%s %d" % (base, n)):
        n += 1
    return "%s %d" % (base, n)


def _mac_trash(path: str) -> None:
    """内核调用点（单测打桩位）。把目录移入废纸篓；失败抛 OSError，绝不永久删除。"""
    full = os.path.abspath(path)
    if not os.path.isdir(full):
        raise OSError(f"目标目录不存在: {full}")
    trash = _trash_dir_for(full)
    if not os.path.isdir(trash):
        raise OSError(f"废纸篓不存在（未接入垃圾桶通道，应用永不永久删除）: {trash}")
    dest = _unique_dest(os.path.join(trash, os.path.basename(full)))
    try:
        shutil.move(full, dest)
    except OSError as e:
        raise OSError(f"移入废纸篓失败（{e}）: {full}") from e
    logger.info("已移入废纸篓: %s -> %s", full, dest)


def _platform_key() -> str:
    """走哪条通道（单测打桩位）：'nt' 走 SHFileOperation，'darwin' 走废纸篓，其余不接"""
    return "nt" if os.name == "nt" else sys.platform


def send_to_recycle(path: str) -> None:
    """把目录移入系统垃圾桶（Windows 回收站 / macOS 废纸篓）。目标必须是存在的目录；失败抛 OSError。"""
    full = os.path.abspath(path)
    if not os.path.isdir(full):
        raise OSError(f"目标目录不存在: {full}")
    key = _platform_key()
    if key == "nt":
        _sh_delete(full)
    elif key == "darwin":
        _mac_trash(full)
    else:
        raise OSError("本平台没有接入系统垃圾桶通道（应用永不永久删除）")
    logger.info("已移入垃圾桶: %s", full)
