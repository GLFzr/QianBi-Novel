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

# ---- 崩溃观测：faulthandler 落独立文件，原生崩溃也能留 Python 层轨迹 ----
import faulthandler  # noqa: E402

_faulthandler_file = None
try:
    from .logger import LOG_DIR as _LOG_DIR
    _faulthandler_file = open(os.path.join(_LOG_DIR, "faulthandler.log"), "a", encoding="utf-8")
    faulthandler.enable(file=_faulthandler_file, all_threads=True)
except Exception:  # noqa: BLE001
    try:
        faulthandler.enable()
    except Exception:  # noqa: BLE001
        _faulthandler_file = None
if _faulthandler_file:
    import datetime as _dt
    _faulthandler_file.write(f"\n--- process start {_dt.datetime.now():%Y-%m-%d %H:%M:%S} "
                             f"v{__version__} pid={os.getpid()}\n")
    _faulthandler_file.flush()


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

    # ---- 内置字体（v1.2）：MiSans 四字重（Regular/Medium/Demibold/Bold 同家族，
    # QML font.weight 直接可用）；注册失败静默回落系统雅黑，不影响功能 ----
    from PySide6.QtGui import QFontDatabase
    _fonts_dir = resource_path(os.path.join("assets", "fonts"))
    try:
        for _fn in sorted(os.listdir(_fonts_dir)):
            if _fn.lower().endswith((".ttf", ".otf")):
                if QFontDatabase.addApplicationFont(os.path.join(_fonts_dir, _fn)) < 0:
                    logger.warning("字体注册失败：%s", _fn)
    except OSError as _e:
        logger.warning("内置字体目录不可用（%s），回落系统字体", _e)

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
    reporter.install()   # N-01（P0）：钩子在 install() 里而全仓从未调用——不装=崩溃零落盘
    cfg = {}
    try:
        from . import config as cfg_mod
        cfg = cfg_mod.load_config()
    except Exception:  # noqa: BLE001
        pass
    # ---- 去 AI 味规则源缓存（lieflat 集成）：启动时一次性读入 vendor 文件并冻结。
    # volume_session 卷级冻结头按字节比对，运行中文件改动/规则源切换 = 会话栈整卷
    # 作废重建（费用损失）——进程生命周期内只读这一份。读不到/解析失败自动回退
    # builtin 并出声告警（见 skill_rules.init_rules_cache）。
    try:
        from .prompts import skill_rules
        skill_rules.init_rules_cache(cfg)
    except Exception as _e:  # noqa: BLE001
        logger.warning("去 AI 味规则源缓存初始化失败，回退内置规则：%s", _e)
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
