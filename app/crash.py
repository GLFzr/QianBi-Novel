# -*- coding: utf-8 -*-
"""全局崩溃处理：未捕获异常 → 脱敏落盘 → 主线程弹对话框

- sys.excepthook + threading.excepthook 双钩子（Qt 槽内异常走 sys.excepthook）
- dump 写 ~/.qianbi_novel/crashes/（经 secrets.redact_text 脱敏）
- 对话框经 Qt 信号排队到主线程弹出（工作线程崩溃安全）
"""
import datetime
import logging
import os
import sys
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from . import secrets

logger = logging.getLogger("qianbi.crash")

CRASH_DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "crashes")


def dump_global(exc: BaseException, thread_name: str = "") -> str:
    """全局崩溃现场落盘（脱敏）。返回 dump 路径（失败返回空串）"""
    tb = traceback.format_exc()
    body = (f"# 应用崩溃\n\n- 时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"- 线程：{thread_name or threading.current_thread().name}\n\n"
            f"```\n{secrets.redact_text(tb)}\n```\n")
    try:
        os.makedirs(CRASH_DIR, exist_ok=True)
        path = os.path.join(CRASH_DIR, f"crash_{datetime.datetime.now():%Y%m%d_%H%M%S}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path
    except Exception:  # noqa: BLE001
        return ""


class CrashReporter(QObject):
    """安装双钩子；crashHappened(summary, dump_path) 信号排队到主线程弹窗"""
    crashHappened = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._installed = False

    def install(self):
        if self._installed:
            return
        self._installed = True
        sys_excepthook = sys.excepthook

        def hook(tp, val, tb):
            if issubclass(tp, KeyboardInterrupt):
                sys_excepthook(tp, val, tb)
                return
            exc = val if isinstance(val, BaseException) else tp(val)
            path = dump_global(exc)
            summary = secrets.redact_text(f"{tp.__name__}: {exc}")[:400]
            logger.error("未捕获异常（dump=%s）: %s", path, summary)
            self.crashHappened.emit(summary, path)

        sys.excepthook = hook

        def thread_hook(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                sys_excepthook(args.exc_type, args.exc_value, args.exc_traceback)
                return
            exc = args.exc_value if isinstance(args.exc_value, BaseException) else args.exc_type(args.exc_value)
            path = dump_global(exc, thread_name=args.thread.name if args.thread else "")
            summary = secrets.redact_text(f"{args.exc_type.__name__}: {exc}")[:400]
            logger.error("工作线程未捕获异常（dump=%s）: %s", path, summary)
            self.crashHappened.emit(summary, path)

        threading.excepthook = thread_hook

