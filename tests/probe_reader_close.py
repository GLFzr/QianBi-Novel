# -*- coding: utf-8 -*-
"""阅读器开/关与抽屉探针（修复 drawer id 回归用）

验证：① openReader 后 opacity=1；② close()（退出按钮同路径）后淡出到 0 且 visible=False；
③ drawerOpened=True 时抽屉真实可见；④ 全程无 ReferenceError 类 QML 警告。
不发任何 LLM 请求。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)

app = QGuiApplication([])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
if not engine.rootObjects():
    print("FAIL: Main.qml 加载失败")
    for w in WARNINGS:
        print("  QML>", w)
    sys.exit(1)
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)


def find_reader():
    for c in win.findChildren(object):
        if "ReaderView" in c.metaObject().className():
            return c
    raise RuntimeError("no reader")


def check(name, ok):
    print(("[OK ] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        check.failed = True


check.failed = False


def step1_open():
    win.setProperty("activePanel", "chapters")
    win.openReader()
    QTimer.singleShot(500, step2_check_open)


def step2_check_open():
    r = find_reader()
    check("打开后 opacity==1", abs(float(r.property("opacity")) - 1.0) < 0.01)
    r.setProperty("drawerOpened", True)
    QTimer.singleShot(300, step3_drawer)


def step3_drawer():
    r = find_reader()
    drawer = None
    for c in r.findChildren(object):
        try:
            if c.objectName() == "" and "QQuickRectangle" in c.metaObject().className() \
               and float(c.property("width") or 0) == 300:
                drawer = c
                break
        except Exception:
            pass
    check("抽屉可见", drawer is not None and bool(drawer.property("visible")))
    r.setProperty("drawerOpened", False)
    r.close()          # 与「退出」按钮同路径
    QTimer.singleShot(500, step4_closed)


def step4_closed():
    r = find_reader()
    check("退出后 opacity==0", abs(float(r.property("opacity"))) < 0.01)
    check("退出后 visible==False", not bool(r.property("visible")))
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_open)
sys.exit(app.exec())
