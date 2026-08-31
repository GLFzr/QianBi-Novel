# -*- coding: utf-8 -*-
"""设置页四标签确定性截图探针：QQuickWindow.grabWindow（不经合成器），复现真实配置的渲染"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shiboken6
from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests_output", "settings_probe")
os.makedirs(OUT, exist_ok=True)
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj"))

WARN = []


def _cap(mode, ctx, msg):
    WARN.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_cap)

app = QGuiApplication([])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
win = engine.rootObjects()[0]
win.setProperty("width", 1440)
win.setProperty("height", 900)
win.setVisible(True)
b._open_project(PROJ, silent=True)

PANEL = None


def find_panel():
    global PANEL
    for c in win.findChildren(object):
        if c.objectName() == "settingsPanel":
            PANEL = c
            return
    raise RuntimeError("settingsPanel not found")


def grab(name):
    qw = shiboken6.wrapInstance(shiboken6.getCppPointer(win)[0], QQuickWindow)
    img = qw.grabWindow()
    img.save(os.path.join(OUT, name))
    print("grab", name, img.width(), "x", img.height(), flush=True)


def step0():
    win.setProperty("activePanel", "settings")
    QTimer.singleShot(900, step1)


def step1():
    find_panel()
    print("settingsTab =", PANEL.property("settingsTab"), flush=True)
    print("connections =", len(b.connectionOptions()), flush=True)
    for c in b.connectionOptions():
        print("  conn:", c.get("name"), "|", c.get("model"), flush=True)
    grab("tab0_conn.png")
    PANEL.setProperty("settingsTab", 1)
    QTimer.singleShot(600, step2)


def step2():
    grab("tab1_writing.png")
    PANEL.setProperty("settingsTab", 2)
    QTimer.singleShot(600, step3)


def step3():
    grab("tab2_appearance.png")
    PANEL.setProperty("settingsTab", 3)
    QTimer.singleShot(600, step4)


def step4():
    grab("tab3_system.png")
    errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
    print("warnings:", len(errs), flush=True)
    for w in errs[:12]:
        print("  QML>", w, flush=True)
    print("PROBE_DONE", flush=True)
    QTimer.singleShot(150, app.quit)


QTimer.singleShot(900, step0)
QTimer.singleShot(60000, app.quit)  # 看门狗：任何步骤抛异常也不挂死
sys.exit(app.exec())
