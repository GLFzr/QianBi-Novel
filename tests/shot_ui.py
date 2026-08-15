# -*- coding: utf-8 -*-
"""离屏渲染各页面并截图，用于 UI 走查（不依赖显示器）"""
import os, sys, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer, QElapsedTimer

app = QGuiApplication(sys.argv)

# ---- 造一个有内容的演示项目 ----
from app import project
from app.core import state as st, memory

tmp = tempfile.mkdtemp(prefix="qbn_shot_")
proj = project.create_project(tmp, "诡异复苏：我的笔记能改命")
project.write_idea_info(proj, "悬疑脑洞", "番茄", "主角捡到能改命的笔记", 100)
prose = "# 第1章 雨夜入局\n\n" + ("雨点敲在窗棂上，他翻开那本笔记，写下了第一行字。字迹未干，窗外的雨忽然停了，街对面的霓虹招牌换成了一只睁开的眼睛。" * 30)
titles = {1: "雨夜入局", 2: "摊牌", 3: "意外来客"}
for n in (1, 2, 3):
    project.write_file(project.get_chapter_path(proj, n, titles[n]), prose.replace("第1章", f"第{n}章").replace("雨夜入局", titles[n]))
for n in (4, 5):
    project.write_file(project.get_outline_path(proj, n), f"### 第 {n} 章：反击序幕\n- 核心事件：...")
stt = st.load_state(proj)
stt["total_chapters"] = 333
stt["stage"] = st.STAGE_PROSE
st.append_history(proj, stt, {"num": 1, "title": "雨夜入局", "words": 3024, "deslop_blocking": 0, "deslop_advisory": 2, "status": "pass"})
st.append_history(proj, stt, {"num": 2, "title": "摊牌", "words": 2981, "deslop_blocking": 0, "deslop_advisory": 1, "status": "pass"})
st.append_history(proj, stt, {"num": 3, "title": "意外来客", "words": 2866, "deslop_blocking": 2, "deslop_advisory": 3, "status": "needs_fix"})
memory.write_global_summary(proj, "主角获得改命笔记，代价未知。")

from app.ui.bridge import Bridge
bridge = Bridge()
bridge.openProject(proj)
bridge.openChapter(3)
bridge.scanChapterText(project.read_file(project.get_chapter_path(proj, 3, "")))

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", bridge)
qml_dir = os.path.join(os.getcwd(), "app", "ui", "qml")
engine.addImportPath(qml_dir)
warns = []
engine.warnings.connect(lambda msgs: warns.extend(m.toString() for m in msgs))
engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
assert engine.rootObjects(), "QML load failed"
win = engine.rootObjects()[0]

os.makedirs("shots", exist_ok=True)
stack = win.findChild(type(win), "mainStack")
if stack is None:
    from PySide6.QtQuick import QQuickItem
    stack = win.findChild(QQuickItem, "mainStack")

pages = [("1_bookshelf", 0), ("2_monitor", 1), ("3_chapter", 2), ("4_connections", 3)]
results = []


def grab_all():
    for name, idx in pages:
        if stack is not None:
            stack.setProperty("currentIndex", idx)
        for _ in range(10):
            app.processEvents()
        t = QElapsedTimer(); t.start()
        while t.elapsed() < 250:
            app.processEvents()
        screen = app.primaryScreen()
        img = screen.grabWindow(win.winId()).toImage()
        path = os.path.join("shots", name + ".png")
        img.save(path)
        results.append((name, img.width(), img.height()))
    for w in warns[:10]:
        print("QML_WARN:", w)
    for r in results:
        print("SHOT", r[0], f"{r[1]}x{r[2]}")
    app.quit()


QTimer.singleShot(800, grab_all)
app.exec()
print("SHOTS_DONE")
