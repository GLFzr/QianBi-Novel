# -*- coding: utf-8 -*-
"""千笔一文 Novel — AI 网文自动写作台

- 立项(人定主题) → 核心设定 → 全书大纲 → 章节细纲 → 章节微循环 ×N → 完本
- 章节微循环：上下文组装 → 草稿 → AI味扫描(本地) → 去味改写(按需) → 审校 → 定稿落库
- 断点续跑（pipeline_state.json），AI 先跑、人随时介入
- 酒馆式连接管理（DeepSeek / OpenAI / 自定义兼容），三槽位任务路由
- PySide6 + QML「深夜编辑部」设计系统
"""
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from . import __version__
from .logger import setup_logging
from .ui.bridge import Bridge

logger = setup_logging()


def resource_path(rel: str) -> str:
    """兼容开发与 PyInstaller 打包路径"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)


def main():
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("QianBiNovel")
    app.setApplicationDisplayName("千笔一文 Novel")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("QianBiNovel")
    logger.info("应用启动 v%s", __version__)

    engine = QQmlApplicationEngine()
    bridge = Bridge()
    engine.rootContext().setContextProperty("bridge", bridge)

    qml_dir = resource_path(os.path.join("app", "ui", "qml"))
    engine.addImportPath(qml_dir)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
