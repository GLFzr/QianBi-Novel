# -*- coding: utf-8 -*-
"""V0.9.9 全功能真机走查：驾驶舱/笔记/设置四页/阅读器/标注/导出预览 + 截图"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests_output")
PROJ = os.path.abspath(os.path.join(OUT, "m1_proj"))

app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
bridge = Bridge()
engine.rootContext().setContextProperty("bridge", bridge)
qml_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ui", "qml")
engine.addImportPath(qml_dir)
engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
if not engine.rootObjects():
    print("MAIN_LOAD_FAIL")
    sys.exit(1)
win = engine.rootObjects()[0]

# ---- 数据注入（走查有内容可看）----
bridge._open_project(PROJ, silent=True)
from app.core import state as st
state = st.load_state(PROJ)
st.add_idea(PROJ, state, "下一章让女主先拒绝一次，再给出理由", "next")
st.add_idea(PROJ, state, "反派的名字换成更冷感的两字名", "5")
st.add_idea(PROJ, state, "[第2章·阅读灵感] 这里可以埋一条旧照片伏笔", "next")
st.add_idea(PROJ, state, "已应用的历史想法（测试状态显示）", "next")
ideas = st.norm_ideas(state)
ideas[3]["status"] = "applied"
state["pending_ideas"] = ideas
st.save_state(PROJ, state)


def by_name(name):
    for c in win.findChildren(object):
        if c.objectName() == name:
            return c
    raise RuntimeError(f"objectName {name} not found")


def find_reader():
    for c in win.findChildren(object):
        if "ReaderView" in c.metaObject().className():
            return c
    raise RuntimeError("ReaderView not found")


def qprop(obj, name):
    return obj.property(name)


def qcall(obj, method, *args):
    """调用 QML 函数（无返回值场景）"""
    from PySide6.QtCore import Qt, QMetaObject, Q_ARG
    if not args:
        ok = QMetaObject.invokeMethod(obj, method, Qt.DirectConnection)
    else:
        types = []
        vals = []
        for a in args:
            if isinstance(a, bool):
                types.append("bool"); vals.append(Q_ARG(bool, a))
            elif isinstance(a, int):
                types.append("int"); vals.append(Q_ARG(int, a))
            elif isinstance(a, float):
                types.append("qreal"); vals.append(Q_ARG(float, a))
            else:
                types.append("QString"); vals.append(Q_ARG(str, a))
        ok = QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *vals)
    if not ok:
        raise RuntimeError(f"invokeMethod {method} failed")


ACTIONS = []


def shot(name):
    win = app.allWindows()[0]
    # DWM 缓存兜底：切换可见性强制重新合成，确保截到当前状态
    win.setVisible(False)
    win.setVisible(True)
    def do_grab():
        img = app.primaryScreen().grabWindow(win.winId())
        p = os.path.join(OUT, f"v099_{name}.png")
        img.save(p)
        print(f"shot {name} {img.width()}x{img.height()}", flush=True)
    QTimer.singleShot(150, do_grab)


def at(name, fn=None, wait=450):
    def run():
        err = None
        if fn:
            try:
                fn()
            except Exception as e:
                err = e

        def finish():
            try:
                shot(name)
            except Exception as e:
                print(f"shot fail {name}: {e}")
            print(f"STEP {name} {'ERR: ' + str(err) if err else 'OK'}", flush=True)
            nxt()

        QTimer.singleShot(wait, finish)
    ACTIONS.append(run)


def nxt():
    ACTIONS.pop(0)
    if ACTIONS:
        ACTIONS[0]()
    else:
        print("WALK_DONE")
        QTimer.singleShot(200, app.quit)


def nav(key):
    win.setProperty("activePanel", key)


# ---- 走查序列 ----
at("01_cockpit", lambda: nav("pipeline"))
at("02_notes", lambda: nav("notes"))
at("03_settings_conn", lambda: nav("settings"))
at("04_settings_writing", lambda: by_name("settingsPanel").setProperty("settingsTab", 1))
at("05_settings_appearance", lambda: by_name("settingsPanel").setProperty("settingsTab", 2))
at("06_settings_system", lambda: by_name("settingsPanel").setProperty("settingsTab", 3))
at("07_chapters", lambda: nav("chapters"))
at("08_reader_night", lambda: win.openReader(), 650)
at("09_reader_toc", lambda: (find_reader().setProperty("drawerTab", "toc"),
                             find_reader().setProperty("drawerOpened", True)))
at("10_reader_ann_add", lambda: (
    bridge.addAnnotation(qprop(find_reader(), "curNum"), "highlight_yellow", "这是第二章的内容", "", 0.1),
    bridge.addAnnotation(qprop(find_reader(), "curNum"), "comment", "剧情推进", "这里节奏太拖，定稿前压缩", 0.4),
    bridge.addBookmark(qprop(find_reader(), "curNum"), 0.55, "中段书签"),
    qcall(find_reader(), "refreshStore"),
    qcall(find_reader(), "render"),
    find_reader().setProperty("drawerTab", "marks"),
    find_reader().setProperty("drawerOpened", True)))
at("11_reader_bigfont", lambda: (
    bridge.setReaderPref("fontScale", 1.35),
    bridge.setReaderPref("lineHeight", 2.2),
    find_reader().setProperty("prefs", bridge.readerPrefs()),
    find_reader().setProperty("drawerOpened", False)))
at("12_reader_parchment", lambda: (
    bridge.setReaderPref("theme", "parchment"),
    find_reader().setProperty("prefs", bridge.readerPrefs())))
at("13_reader_white", lambda: (
    bridge.setReaderPref("theme", "white"),
    find_reader().setProperty("prefs", bridge.readerPrefs())))
at("14_reader_close", lambda: (qcall(find_reader(), "close"), win.setProperty("activePanel", "pipeline")))
at("15_export_preview", lambda: (by_name("exportDialog").refreshPreview(), by_name("exportDialog").open()))
at("16_done", lambda: (by_name("exportDialog").close(), nav("pipeline")))

QTimer.singleShot(900, ACTIONS[0])
sys.exit(app.exec())
