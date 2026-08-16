# -*- coding: utf-8 -*-
"""布局边界检查：渲染后遍历可见 QQuickItem，报告超出窗口边界的元素

用于验证 UI 重构后无布局溢出（三栏/顶栏/卡片是否越界）。
"""
import os
import sys
import tempfile

# 隔离用户配置：测试不得写入 ~/.qianbi_novel（防书架被污染）
_FH = tempfile.mkdtemp(prefix="qbn_fakehome_")
os.environ["USERPROFILE"] = _FH

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer, QElapsedTimer, QPointF
from PySide6.QtQuick import QQuickItem

app = QGuiApplication(sys.argv)

from app import project
from app.core import state as st, memory

tmp = tempfile.mkdtemp(prefix="qbn_layout_")
proj = project.create_project(tmp, "诡异复苏：我的笔记能改命")
project.write_idea_info(proj, "悬疑脑洞", "番茄", "主角捡到能改命的笔记", 100)
prose = "# 第1章 雨夜入局\n\n" + ("雨点敲在窗棂上，他翻开那本笔记，写下了第一行字。字迹未干，窗外的雨忽然停了。" * 30)
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
# 等待组件树实例化完成
for _ in range(30):
    app.processEvents()
stack = win.findChild(QQuickItem, "panelStack")
print("DEBUG panelStack found:", stack is not None, flush=True)
assert stack, "panelStack not found"

problems = []


def check_page(idx, name):
    stack.setProperty("currentIndex", idx)
    for _ in range(15):
        app.processEvents()
    t = QElapsedTimer(); t.start()
    while t.elapsed() < 300:
        app.processEvents()
    w, h = win.width(), win.height()
    items = win.findChildren(QQuickItem)
    for it in items:
        if not it.isVisible() or it.width() <= 0 or it.height() <= 0:
            continue
        # 场景坐标（offscreen 下即窗口坐标）
        p = it.mapToScene(QPointF(0, 0))
        x, y = p.x(), p.y()
        if x < -2 or y < -2 or x + it.width() > w + 2 or y + it.height() > h + 2:
            # 过滤 StackLayout 内部隐藏页残留与 ListView 裁剪项
            if it.objectName():
                problems.append(f"[{name}] ({x:.0f},{y:.0f}) {it.width():.0f}x{it.height():.0f} window={w}x{h} obj={it.objectName()}")
    # 汇总
    print(f"{name}: window {w}x{h} checked {len(items)} items")


pages = [("1_bookshelf", 0), ("2_monitor", 1), ("3_chapter", 2), ("4_connections", 3)]
for name, idx in pages:
    check_page(idx, name)

for w in warns[:10]:
    print("QML_WARN:", w)
print("边界越界项:", len(problems))
for p in problems[:20]:
    print("  OVERFLOW:", p)
print("LAYOUT_CHECK_DONE")
app.quit()
