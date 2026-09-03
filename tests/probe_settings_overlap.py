# -*- coding: utf-8 -*-
"""设置页文字重叠确定性探针：逐 Text 测量 height vs implicitHeight，并做两两矩形相交检测"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

import shiboken6
from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
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
OUT = os.path.join(ROOT, "tests_output", f"settings_overlap_{W}x{H}")
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

PANEL = None
REPORT = {}


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


def eff_visible(item):
    """StackLayout 隐藏页几何仍占据同区域，必须按有效可见性过滤"""
    cur = item
    while cur is not None:
        try:
            if not cur.property("visible"):
                return False
        except Exception:
            pass
        try:
            cur = cur.parentItem()
        except AttributeError:
            cur = None
    return True


def collect_texts(root):
    """遍历 root 子树，收集所有 Text/Label 在面板坐标系下的几何"""
    out = []
    rects = []

    def walk(item, ox, oy):
        nx = ox + item.property("x")
        ny = oy + item.property("y")
        cn = item.metaObject().className()
        vis = eff_visible(item)
        if vis and cn.startswith("QQuickRectangle"):
            rects.append({
                "x": round(nx, 1), "y": round(ny, 1),
                "w": round(item.property("width"), 1),
                "h": round(item.property("height"), 1),
            })
        if vis and (cn.startswith("QQuickText") or cn.startswith("QQuickLabel")):
            t = item.property("text") or ""
            w = item.property("width")
            h = item.property("height")
            ih = item.property("implicitHeight")
            out.append({
                "text": t[:34],
                "x": round(nx, 1), "y": round(ny, 1),
                "w": round(w, 1), "h": round(h, 1),
                "iw": round(item.property("implicitWidth"), 1),
                "ih": round(ih, 1),
                "clipped": bool(ih > h + 0.5),
            })
        try:
            kids = item.childItems()
        except AttributeError:
            kids = []
        for ch in kids:
            walk(ch, nx, ny)

    walk(root, 0.0, 0.0)
    return out, rects


def overlaps(items):
    """视觉矩形（高度取 max(h, ih)）两两相交检测"""
    hits = []
    for i in range(len(items)):
        a = items[i]
        ax0, ay0 = a["x"], a["y"]
        ax1, ay1 = ax0 + a["w"], ay0 + max(a["h"], a["ih"])
        for j in range(i + 1, len(items)):
            c = items[j]
            bx0, by0 = c["x"], c["y"]
            bx1, by1 = bx0 + c["w"], by0 + c["h"]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 2 and oy > 2:
                hits.append({"a": a["text"], "b": c["text"], "area": round(ox * oy, 0)})
    return hits


def scan(tab):
    items, rects = collect_texts(PANEL)
    clipped = [it for it in items if it["clipped"]]
    hits = overlaps(items)
    REPORT[f"tab{tab}"] = {"texts": len(items), "items": items, "rects": rects, "clipped": clipped, "overlaps": hits}
    print(f"--- tab{tab}: texts={len(items)} clipped={len(clipped)} overlaps={len(hits)}", flush=True)
    for it in clipped:
        print(f"  CLIP  h={it['h']:>5.1f} ih={it['ih']:>5.1f} y={it['y']:>6.1f}  {it['text']}", flush=True)
    for hpair in hits[:20]:
        print(f"  OVRP  area={hpair['area']}  [{hpair['a']}] × [{hpair['b']}]", flush=True)


def step0():
    win.setProperty("activePanel", "settings")
    QTimer.singleShot(900, step1)


def step1():
    find_panel()
    grab("tab0_conn.png")
    scan(0)
    PANEL.setProperty("settingsTab", 1)
    QTimer.singleShot(600, step2)


def step2():
    grab("tab1_writing.png")
    scan(1)
    PANEL.setProperty("settingsTab", 2)
    QTimer.singleShot(600, step3)


def step3():
    grab("tab2_appearance.png")
    scan(2)
    PANEL.setProperty("settingsTab", 3)
    QTimer.singleShot(600, step4)


def step4():
    grab("tab3_system.png")
    scan(3)
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    bad = sum(len(v["clipped"]) + len(v["overlaps"]) for v in REPORT.values())
    print("TOTAL_ISSUES =", bad, flush=True)
    errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
    print("qml warnings:", len(errs), flush=True)
    print("PROBE_DONE", flush=True)
    QTimer.singleShot(150, app.quit)


QTimer.singleShot(900, step0)
QTimer.singleShot(60000, app.quit)
rc = app.exec()
bad = sum(len(v.get("clipped", [])) + len(v.get("overlaps", [])) for v in REPORT.values())
sys.exit(2 if bad else rc)
