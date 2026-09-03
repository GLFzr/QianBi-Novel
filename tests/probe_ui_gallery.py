# -*- coding: utf-8 -*-
"""UI 图库探针：逐面板 + 逐 Dialog + 三主题自动截图，供视觉验收使用。

产物：tests_output/ui_gallery/*.png（约 25 张）
断言只做「渲染层健康」：QML ReferenceError/TypeError/Unable-to-assign 计数为 0，
布局与观感由视觉验收流程（对截图逐张评审）承担，本探针不做像素断言。
用法：python tests/probe_ui_gallery.py [WxH]（默认 1440x900）
"""
import atexit
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

import shiboken6
from PySide6.QtCore import QMetaObject, Qt, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj"))
W, H = (1440, 900)
if len(sys.argv) > 1 and "x" in sys.argv[1]:
    W, H = (int(v) for v in sys.argv[1].split("x"))
OUT = os.path.join(ROOT, "tests_output", "ui_gallery")
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
win.setProperty("width", W)
win.setProperty("height", H)
win.setVisible(True)
b._open_project(PROJ, silent=True)

QW = None
PANELS = ["shelf", "pipeline", "chapters", "contract", "notes", "library", "settings"]
DIALOG_STEPS = []       # (name, prepare) —— prepare 在 open 前对 root window 注入状态
CUR_PANEL = 0
CUR_DIALOG = 0
DIALOGS = []
THEMES = [("qianbi_parchment", "theme_parchment"), ("qianbi_plain", "theme_plain")]


def wrap():
    global QW
    if QW is None:
        QW = shiboken6.wrapInstance(shiboken6.getCppPointer(win)[0], QQuickWindow)
    return QW


def grab(name):
    img = wrap().grabWindow()
    img.save(os.path.join(OUT, name + ".png"))
    print("grab", name, img.width(), "x", img.height(), flush=True)


def find_dialogs():
    """收集真正可 open() 的 QML Dialog。
    类名形如 Dialog_QMLTYPE_* / XxxDialog_QMLTYPE_*；要求 metaobject 上确实有
    open() 槽（排除 CwDialogueDock 这类「名字含 Dialog 但不是弹窗」的假阳性，
    以及 FileDialog/FolderDialog——原生对话框会阻塞进程）。"""
    found = []
    for c in win.findChildren(object):
        try:
            cn = c.metaObject().className()
            has_open = c.metaObject().indexOfMethod("open()") >= 0
        except Exception:
            continue
        if "Dialog" not in cn or "Dialogue" in cn:
            continue
        if not has_open:
            continue
        if cn.startswith(("QQuickFileDialog", "QQuickFolderDialog")):
            continue
        found.append(c)
    return found


def _prep_force_lock():
    win.setProperty("lockBlockNum", 3)
    win.setProperty("lockBlockActual", 1180)
    win.setProperty("lockBlockTarget", 2000)
    win.setProperty("lockBlockKind", "word")
    win.setProperty("lockBlockReason", "探针注入：模拟字数未达标的强锁确认文案（校验 header 换行与不重叠）")


def _prep_export():
    try:
        _invoke(win, "refreshPreview")   # 不存在也不阻塞——导出对话框打开即刷新
    except Exception:
        pass


def _invoke(obj, name):
    QMetaObject.invokeMethod(obj, name)


def next_panel():
    global CUR_PANEL
    if CUR_PANEL >= len(PANELS):
        QTimer.singleShot(300, start_dialogs)
        return
    win.setProperty("activePanel", PANELS[CUR_PANEL])
    QTimer.singleShot(650, grab_panel)


def grab_panel():
    global CUR_PANEL
    grab(f"panel_{PANELS[CUR_PANEL]}")
    CUR_PANEL += 1
    next_panel()


def start_dialogs():
    global DIALOGS
    DIALOGS = find_dialogs()
    print("dialogs found:", len(DIALOGS), flush=True)
    QTimer.singleShot(200, next_dialog)


def next_dialog():
    global CUR_DIALOG
    if CUR_DIALOG >= len(DIALOGS):
        QTimer.singleShot(300, theme_shots)
        return
    dlg = DIALOGS[CUR_DIALOG]
    name = dlg.objectName() or f"dialog_{CUR_DIALOG}"
    try:
        if name == "forceLockDialog":
            _prep_force_lock()
        _invoke(dlg, "open")
    except Exception as e:
        print("open fail", name, e, flush=True)
    QTimer.singleShot(500, lambda d=dlg, n=name: grab_dialog(d, n))


def grab_dialog(dlg, name):
    global CUR_DIALOG
    grab(f"dialog_{name}")
    try:
        _invoke(dlg, "close")
    except Exception:
        pass
    CUR_DIALOG += 1
    QTimer.singleShot(350, next_dialog)


def theme_shots():
    win.setProperty("activePanel", "pipeline")
    QTimer.singleShot(400, next_theme)


def next_theme():
    global THEMES
    if not THEMES:
        finish()
        return
    key, shot = THEMES[0]
    THEMES = THEMES[1:]
    try:
        b.setTheme(key)
    except Exception as e:
        print("theme fail", key, e, flush=True)
    QTimer.singleShot(600, lambda k=key, s=shot: grab_theme(k, s))


def grab_theme(key, shot):
    grab(shot)
    QTimer.singleShot(200, next_theme)


def finish():
    errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
    with open(os.path.join(OUT, "gallery.json"), "w", encoding="utf-8") as f:
        json.dump({"panels": PANELS, "dialogs": len(DIALOGS), "warn": errs}, f, ensure_ascii=False, indent=1)
    print("qml warnings:", len(errs), flush=True)
    for w in errs[:8]:
        print("  QML>", w, flush=True)
    print("PROBE_DONE", "PASS" if not errs else "FAIL", flush=True)
    QTimer.singleShot(150, app.quit)


def start():
    try:
        b.setTheme("qianbi_night")
    except Exception:
        pass
    next_panel()


QTimer.singleShot(900, start)
QTimer.singleShot(120000, app.quit)
rc = app.exec()
errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
sys.exit(2 if errs else rc)
