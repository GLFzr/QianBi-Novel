# -*- coding: utf-8 -*-
"""千笔一文 Novel — AI 网文自动写作台

- 立项(人定主题) → 核心设定 → 全书大纲 → 章节细纲 → 章节微循环 ×N → 完本
- 章节微循环：上下文组装 → 草稿 → AI味扫描(本地) → 去味改写(按需) → 审校 → 定稿落库
- 断点续跑（pipeline_state.json），AI 先跑、人随时介入
- 酒馆式连接管理（DeepSeek / OpenAI / 自定义兼容），三槽位任务路由
- PySide6 + QML「深夜编辑部」设计系统
- 商业级运行时：单实例锁 / 全局崩溃处理（脱敏落盘+对话框）/ QML 加载兜底
"""
import os
import sys

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from . import __version__, telemetry
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
    app.setWindowIcon(QIcon(resource_path(os.path.join("assets", "icon.ico"))))
    logger.info("应用启动 v%s", __version__)

    # ---- 单实例锁（T3.1）：二次启动唤起既有窗口并退出，防多开写坏配置 ----
    from .singleinstance import SingleInstance
    def _raise_window():
        pass  # 主窗口创建后替换（见下）
    single = SingleInstance(on_raise=_raise_window)
    if not single.acquire():
        logger.info("已有实例在运行，唤起后退出")
        return 0

    # ---- 全局崩溃处理（T3.2）：未捕获异常脱敏落盘 + 主线程对话框 ----
    from .crash import CrashReporter
    reporter = CrashReporter()
    cfg = {}
    try:
        from . import config as cfg_mod
        cfg = cfg_mod.load_config()
    except Exception:  # noqa: BLE001
        pass
    telemetry.record(cfg, "app_start", version=__version__)

    engine = QQmlApplicationEngine()
    bridge = Bridge()
    reporter.crashHappened.connect(
        lambda summary, path: bridge.emitCrash(summary, path), Qt.QueuedConnection)
    engine.rootContext().setContextProperty("bridge", bridge)

    qml_dir = resource_path(os.path.join("app", "ui", "qml"))
    engine.addImportPath(qml_dir)
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if not engine.rootObjects():
        # QML 加载失败兜底（T3.6）：原生错误窗替代静默崩溃
        logger.error("QML 加载失败")
        try:
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("千笔一文 Novel — 启动失败")
            msg.setText("界面文件加载失败，可能是安装不完整或显卡驱动问题。")
            msg.setDetailedText("\n".join(
                f"- {w.toString()}" for w in engine.warnings()[-10:]) +
                f"\n\n日志目录：{os.path.join(os.path.expanduser('~'), '.qianbi_novel', 'logs')}")
            msg.exec()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)

    win = engine.rootObjects()[0]
    single._on_raise = lambda: (_raise_window_impl(win))
    bridge.mainWindowReady.emit()

    telemetry.record(cfg, "version", version=__version__)
    sys.exit(app.exec())


def _raise_window_impl(win):
    """把既有实例的主窗口提到前台（Windows）"""
    try:
        import ctypes
        hwnd = int(win.winId())
        ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception as e:  # noqa: BLE001
        win.raise_()
        win.requestActivate()
        logger.debug("SetForegroundWindow 失败（降级 Qt raise）: %s", e)


if __name__ == "__main__":
    main()
