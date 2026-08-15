# -*- coding: utf-8 -*-
"""运行日志落盘：~/.qianbi_novel/logs/qianbi.log（滚动，单文件 2MB × 5 份）

- 模块约定：llm 层用 logging.getLogger("qianbi.llm")，core 用 "qianbi.core"
- UI 内存日志（logModel）之外的第二通道，崩溃/异常后仍可回溯
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "logs")
LOG_FILE = os.path.join(LOG_DIR, "qianbi.log")

_configured = False


def setup_logging() -> logging.Logger:
    """初始化根日志（幂等）。返回 "qianbi" 根 logger。"""
    global _configured
    if _configured:
        return logging.getLogger("qianbi")
    _configured = True
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 控制台通道：开发运行时可见；windowed 打包后无控制台，自动失效
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    return logging.getLogger("qianbi")


def log_path() -> str:
    return LOG_FILE
