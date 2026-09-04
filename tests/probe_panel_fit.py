# -*- coding: utf-8 -*-
"""通用面板贴合探针：检测共用功能面板内横向溢出/越界/被压扁的元素
用法: probe_panel_fit.py [WxH]"""
import atexit
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
from PySide6.QtQuick import QQuickItem, QQuickWindow

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app import presets as gp
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj"))
W, H = (1440, 900)
if len(sys.argv) > 1 and "x" in sys.argv[1]:
    W, H = (int(v) for v in sys.argv[1].split("x"))
OUT = os.path.join(ROOT, "tests_output", f"panel_fit_{W}x{H}")
os.makedirs(OUT, exist_ok=True)

# 临时预设（含 P1 两层参数覆盖：阶段档 + 全书采样基线）：预设库面板默认不选中任何预设，只有被选中的预设
# 才会渲染预览区块 —— 没有这个夹具，「参数档区块是否真的显示」就无从验证。
PROBE_PRESET_ID = "probe_p1_ui"
PROBE_PRESET_PATH = os.path.join(gp.user_dir(), PROBE_PRESET_ID + ".json")
with open(PROBE_PRESET_PATH, "w", encoding="utf-8") as _f:
    json.dump({"id": PROBE_PRESET_ID, "name": "P1 参数档探针", "version": 2,
               "description": "探针自动写入，进程退出即删除",
               "stage_hints": {"prose": "探针文风锚（验证 6 阶段区块不受影响）"},
               "stage_params": {
                   "prose": {"temperature": 0.95, "top_p": 0.9, "slot": "writing"},
                   "outline": {"temperature": 0.6},
                   "review": {"temperature": 1.4, "presence_penalty": 0.2}},
               "sampling": {"temperature": 0.8, "thinking": "disabled"}},
              _f, ensure_ascii=False, indent=1)


@atexit.register
def _drop_probe_preset():
    try:
        os.remove(PROBE_PRESET_PATH)
    except OSError:
        pass

WARN = []
FAILS = []          # 渲染断言失败（布局没问题但区块根本没显示出来，同样算 FAIL）


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

STACK = None
REPORT = {}
BLOBS = {}          # panel key -> 渲染出的全部文本（断言「某区块真的显示了出来」用）
PANELS = ["pipeline", "library", "settings", "chapters", "notes", "shelf"]   # library = 预设库面板
CUR = 0


def find_stack():
    global STACK
    for c in win.findChildren(object):
        if c.objectName() == "panelStack":
            STACK = c
            return
    raise RuntimeError("panelStack not found")


def grab(name):
    qw = shiboken6.wrapInstance(shiboken6.getCppPointer(win)[0], QQuickWindow)
    img = qw.grabWindow()
    img.save(os.path.join(OUT, name))
    print("grab", name, img.width(), "x", img.height(), flush=True)


def eff_visible(item):
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


def prop_enum(item, name):
    try:
        engine.globalObject().setProperty("_pj", engine.newQObject(item))
        v = engine.evaluate(f"Number(_pj.{name})")
        try:
            return int(v.toNumber())
        except AttributeError:
            return int(float(v.toString()))
    except Exception:
        return 0


def walk(item, ox, oy, out, hs=False):
    nx = ox + item.property("x")
    ny = oy + item.property("y")
    cn = item.metaObject().className()
    if cn.startswith(("QQuickFlickable", "QQuickListView", "QQuickGridView")):
        try:
            cw = item.property("contentWidth") or 0
            if item.property("clip") and cw > (item.property("width") or 0) + 1:
                hs = True
        except Exception:
            pass
    if eff_visible(item):
        w = item.property("width") or 0
        h = item.property("height") or 0
        if cn.startswith("QQuickText") or cn.startswith("QQuickLabel"):
            # texts 里的 text 截到 30 字（报告体积）；渲染断言要读全文，另存一份不打折的
            out.setdefault("fulls", []).append(item.property("text") or "")
            out.setdefault("texts", []).append({
                "text": (item.property("text") or "")[:30],
                "x": round(nx, 1), "y": round(ny, 1),
                "w": round(w, 1), "h": round(h, 1),
                "iw": round(item.property("implicitWidth"), 1),
                "ih": round(item.property("implicitHeight"), 1),
                "elide": prop_enum(item, "elide"),
                "wrap": prop_enum(item, "wrapMode"),
                "hs": int(hs),
            })
        if cn.startswith("QQuickRectangle") or cn.startswith("QQuickItem"):
            out.setdefault("boxes", []).append({
                "cls": cn.split("_")[0], "x": round(nx, 1), "y": round(ny, 1),
                "w": round(w, 1), "h": round(h, 1), "hs": int(hs),
            })
    try:
        kids = item.childItems()
    except AttributeError:
        kids = []
    for ch in kids:
        walk(ch, nx, ny, out, hs)


def scan(key):
    pw = STACK.property("width")
    ph = STACK.property("height")
    data = {}
    walk(STACK, 0.0, 0.0, data)
    texts = data.get("texts", [])
    overflow, voverflow, squashed, offside = [], [], [], []
    for t in texts:
        if t["elide"] == 0 and t["wrap"] == 0 and t["iw"] > t["w"] + 0.5:
            overflow.append(t)
        if t["ih"] > t["h"] + 0.5:
            voverflow.append(t)
        if t["w"] <= 1 and t["iw"] > 2:
            squashed.append(t)
        if t["x"] + t["w"] > pw + 1 and not t.get("hs"):
            offside.append(t)
    for bx in data.get("boxes", []):
        if bx["w"] <= 1 and bx["h"] > 30:
            squashed.append(bx)
        if bx["x"] + bx["w"] > pw + 1 and bx["w"] > 1 and not bx.get("hs"):
            offside.append(bx)
    REPORT[key] = {
        "panel_w": pw, "texts": len(texts),
        "h_overflow": overflow, "v_overflow": voverflow,
        "squashed": squashed, "offside": offside,
    }
    BLOBS[key] = "\n".join(data.get("fulls", []))
    n = len(overflow) + len(voverflow) + len(squashed) + len(offside)
    print(f"--- {key}: panel_w={pw} texts={len(texts)} issues={n}", flush=True)
    for t in overflow[:12]:
        print(f"  H-OVF  w={t['w']:>6.1f} iw={t['iw']:>6.1f}  {t['text']}", flush=True)
    for t in voverflow[:8]:
        print(f"  V-OVF  h={t['h']:>6.1f} ih={t['ih']:>6.1f}  {t['text']}", flush=True)
    for t in squashed[:8]:
        print(f"  SQUASH w={t.get('w', 0):>6.1f} iw={t.get('iw', 0):>6.1f}  {t.get('text', t.get('cls', ''))}", flush=True)
    for t in offside[:8]:
        print(f"  OFFSIDE x={t.get('x', 0):>6.1f} w={t.get('w', 0):>6.1f}  {t.get('text', t.get('cls', ''))}", flush=True)


def next_panel():
    global CUR
    if CUR >= len(PANELS):
        finish()
        return
    win.setProperty("activePanel", PANELS[CUR])
    QTimer.singleShot(700, do_scan)


def _select_probe_preset():
    """预设库默认不选中任何预设（预览区空）→ 选中探针预设，预览区块才会真的进场景图"""
    for it in win.findChildren(QQuickItem):
        if it.property("selectedId") is not None and hasattr(it, "refresh"):
            it.setProperty("selectedId", PROBE_PRESET_ID)
            it.refresh()
            return True
    return False


def _arm_conn_delete():
    """让删除按钮的「确认态」进场景图

    删除连接现在连带清掉凭据管理器里的 Key，所以第一次点击后按钮会换成
    「确认删除（含 Key）」——那才是这一行里最宽的文案，溢出只可能出现在这一态。
    从 Python 读 implicitWidth 拿的是没刷新的旧值（实测两态都报 54），
    所以这个态必须由真实渲染来量，而不是在别处塞一条永远为真的宽度断言。
    """
    panel = next((it for it in win.findChildren(QQuickItem)
                  if it.objectName() == "settingsPanel"), None)
    conns = (b.cfg.get("connections") or []) if panel is not None else []
    if panel is None or not conns:
        return False
    panel.setProperty("settingsTab", 0)
    panel.setProperty("isNew", False)
    panel.setProperty("editingId", conns[0].get("id", ""))
    panel.setProperty("armedDelete", True)
    return True


def do_scan():
    global CUR
    if PANELS[CUR] == "library":
        if not _select_probe_preset():
            FAILS.append("预设库面板未找到（selectedId/refresh）")
        QTimer.singleShot(600, finish_scan)
        return
    if PANELS[CUR] == "settings":
        if not _arm_conn_delete():
            FAILS.append("设置面板没进入「确认删除」态：没渲染就量不到，等于漏检")
        QTimer.singleShot(600, finish_scan)
        return
    finish_scan()


def finish_scan():
    global CUR
    key = PANELS[CUR]
    grab(f"panel_{key}.png")
    scan(key)
    CUR += 1
    next_panel()


def finish():
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    blob = BLOBS.get("library", "")
    for needle in ("阶段参数档", "温度=0.95", "温度锁", "全书采样基线", "思考模式=disabled"):
        if needle not in blob:
            FAILS.append(f"预设库面板未渲染参数档：缺「{needle}」")
    bad = sum(len(v["h_overflow"]) + len(v["v_overflow"]) + len(v["squashed"]) + len(v["offside"]) for v in REPORT.values())
    print("TOTAL_ISSUES =", bad, flush=True)
    print("RENDER_FAILS =", len(FAILS), flush=True)
    for m in FAILS:
        print("  FAIL>", m, flush=True)
    if FAILS:
        for line in blob.split("\n"):        # 实际渲染出的参数档区块，区分「没显示」与「显示了一半」
            if any(k in line for k in ("参数档", "基线", "温度", "核采样", "连接槽")):
                print("  BLOB>", line, flush=True)
    errs = [w for w in WARN if "ReferenceError" in w or "TypeError" in w or "Unable to assign" in w]
    print("qml warnings:", len(errs), flush=True)
    for w in errs[:8]:
        print("  QML>", w, flush=True)
    print("PROBE_DONE", "PASS" if not bad and not FAILS and not errs else "FAIL", flush=True)
    QTimer.singleShot(150, app.quit)


def start():
    find_stack()
    next_panel()


QTimer.singleShot(900, start)
QTimer.singleShot(90000, app.quit)
rc = app.exec()
bad = sum(len(v.get("h_overflow", [])) + len(v.get("v_overflow", [])) + len(v.get("squashed", [])) + len(v.get("offside", [])) for v in REPORT.values())
sys.exit(2 if (bad or FAILS) else rc)
