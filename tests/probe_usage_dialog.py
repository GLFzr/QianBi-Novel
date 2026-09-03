# -*- coding: utf-8 -*-
"""用量对话框确定性探针：真实用量数据打开 UsageDialog，grabWindow + 断言渲染文本

回归锚（W2）：今日 tokens ≥1,000,000 时必须定点逗号格式（4,248,047），
不得出现科学计数法（4.248047e+06）。同时抓取对话框图像取证。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

import shiboken6
from PySide6.QtCore import QUrl, QTimer, QMetaObject, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests_output", "usage_probe")
os.makedirs(OUT, exist_ok=True)

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

DLG = None


def find_dialog():
    global DLG
    for c in win.findChildren(object):
        if c.objectName() == "usageDialog":
            DLG = c
            return
    raise RuntimeError("usageDialog not found")


def collect_texts(item, out):
    cls = item.metaObject().className()
    if cls.startswith("QQuickText"):
        t = item.property("text")
        if t:
            out.append(str(t))
    for c in item.children():
        collect_texts(c, out)


def step0():
    find_dialog()
    QMetaObject.invokeMethod(DLG, "open")
    QTimer.singleShot(900, step1)


def step1():
    print("opened =", DLG.property("opened"), "visible =", DLG.property("visible"), flush=True)
    d = DLG.property("data")
    print("data keys =", list(d.keys()) if d else None, flush=True)
    QMetaObject.invokeMethod(DLG, "reload")
    QTimer.singleShot(600, step2)


def step2():
    # 先抓取图像取证（grab 会强制求值渲染绑定）
    qw = shiboken6.wrapInstance(shiboken6.getCppPointer(win)[0], QQuickWindow)
    img = qw.grabWindow()
    img.save(os.path.join(OUT, "usage_dialog.png"))
    print("grab usage_dialog.png", img.width(), "x", img.height(), flush=True)
    QTimer.singleShot(400, step3)


def step3():
    texts = []
    collect_texts(DLG, texts)
    print("--- dialog texts ---", flush=True)
    for t in texts:
        print("  >", t, flush=True)
    # ---- 权威 QML 冒烟断言：直接用本引擎求值「修复所用表达式」----
    fmt_fixed = engine.evaluate("Number(4248047).toLocaleString(Qt.locale(),'f',0)").toString()
    fmt_legacy = engine.evaluate("Number(4248047).toLocaleString()").toString()
    print("QML fixed  =", fmt_fixed, flush=True)
    print("QML legacy =", fmt_legacy, flush=True)
    s = b.usageSummary()
    today_total = int(s["today"].get("in", 0)) + int(s["today"].get("out", 0))
    print("today_total =", today_total, flush=True)
    ok = True
    if str(fmt_fixed) != "4,248,047":
        print("FAIL QML 'f',0 未得逗号分隔:", fmt_fixed, flush=True)
        ok = False
    if "e+" not in str(fmt_legacy):
        print("WARN legacy 未复现科学计数法（不影响修复）:", fmt_legacy, flush=True)
    sci = [t for t in texts if re.search(r"[eE]\+\d", t)]
    if sci:
        print("FAIL 对话框渲染文本出现科学计数法:", sci, flush=True)
        ok = False
    if today_total < 1_000_000:
        print("WARN 当前真实今日用量 <100 万，未触发该场景（断言仍按固定值校验）", flush=True)
    if not ok:
        sys.exit(2)
    errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
    print("warnings(filtered):", len(errs), " all:", len(WARN), flush=True)
    for w in WARN[:30]:
        print("  QML>", w, flush=True)
    print("PROBE_OK", flush=True)
    QTimer.singleShot(150, app.quit)


QTimer.singleShot(900, step0)
QTimer.singleShot(30000, app.quit)  # 看门狗
sys.exit(app.exec())
