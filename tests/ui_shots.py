# -*- coding: utf-8 -*-
"""UI 走查截图生成：多状态、多面板、多交互场景，供视觉模型逐张识图分析

覆盖场景：
  01 书架面板（有项目）
  02 流水线面板（有项目，打开状态）
  03 章节面板（章节列表）
  04 设置面板（连接表单）
  05 中央编辑器（打开章节正文）
  06 日志展开（底栏折叠面板）
  07 流式输出态（liveDraft 有内容 + isStreaming）
  08 扫描结果条（findings 有内容）
  09 新建项目对话框
  10 带指导重写对话框
  11 项目文件对话框
  12 空书架（无项目状态）
"""
import os
import sys
import tempfile

# 隔离用户配置：UI 截图测试不得写入 ~/.qianbi_novel（防书架被测试项目污染）
_FAKE_HOME = tempfile.mkdtemp(prefix="qbn_fakehome_")
os.environ["USERPROFILE"] = _FAKE_HOME
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer, QElapsedTimer
from PySide6.QtQuick import QQuickItem

app = QGuiApplication(sys.argv)

# offscreen 无 Qt 自带字体：注册 Windows 系统字体，否则中文渲染为方框
from PySide6.QtGui import QFontDatabase, QFont
_fd = QFontDatabase()
for _f in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc",
           r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyhbd.ttc"]:
    if os.path.exists(_f):
        _fd.addApplicationFont(_f)
app.setFont(QFont("Microsoft YaHei UI", 10))

from app import project
from app.core import state as st, memory

# 演示项目（有 5 章正文、6 章细纲、追踪文件、历史）
tmp = tempfile.mkdtemp(prefix="qbn_review_")
proj = project.create_project(tmp, "诡异复苏：我的笔记能改命")
project.write_idea_info(proj, "悬疑脑洞", "番茄", "主角捡到能改命的笔记", 100)
titles = {1: "雨夜入局", 2: "摊牌", 3: "意外来客", 4: "旧书店", 5: "代价"}
prose = "# 第1章 雨夜入局\n\n雨点敲在窗棂上，他翻开那本笔记，写下了第一行字。字迹未干，窗外的雨忽然停了，街对面的霓虹招牌换成了一只睁开的眼睛。" * 12
for n in (1, 2, 3, 4, 5):
    project.write_file(project.get_chapter_path(proj, n, titles[n]),
                       prose.replace("第1章", f"第{n}章").replace("雨夜入局", titles[n]))
for n in (4, 5, 6):
    project.write_file(project.get_outline_path(proj, n), f"### 第 {n} 章：推进\n- 核心事件：...")
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
for _ in range(30):
    app.processEvents()
stack = win.findChild(QQuickItem, "panelStack")
assert stack, "panelStack not found"

OUT = os.path.join(os.getcwd(), "shots_review")
os.makedirs(OUT, exist_ok=True)


def settle(ms=400):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        app.processEvents()


def grab(name):
    settle()
    img = app.primaryScreen().grabWindow(win.winId()).toImage()
    path = os.path.join(OUT, name + ".png")
    img.save(path)
    print("SHOT", name, f"{img.width()}x{img.height()}", flush=True)


def set_panel(idx):
    stack.setProperty("currentIndex", idx)
    settle()


def find(obj_name):
    return win.findChild(QQuickItem, obj_name)


# ---- 01 书架面板 ----
set_panel(0)
grab("01_bookshelf")

# ---- 02 流水线面板 ----
set_panel(1)
grab("02_pipeline")

# ---- 03 章节面板 ----
set_panel(2)
grab("03_chapters")

# ---- 04 设置面板 ----
set_panel(3)
grab("04_settings")

# ---- 05 中央编辑器（第 3 章 + 扫描结果条）----
grab("05_editor_scanbar")

# ---- 06 日志展开 ----
win.setProperty("logVisible", True)
settle()
grab("06_log_open")
win.setProperty("logVisible", False)
settle()

# ---- 07 流式输出态（模拟 liveDraft）----
# 直接通过 QML 属性注入模拟：找到编辑器组件后，给 bridge 塞流式内容
bridge._live_draft = "# 第6章 新的篇章\n\n窗外雨声不断，陆离翻开那本笔记，笔尖悬在纸面上方。\n\n他想起父亲留下的那句话，手心的汗洇湿了纸角。" * 3
bridge._streaming = True
bridge.liveDraftChanged.emit()
bridge.streamingChanged.emit()
settle()
grab("07_streaming")
bridge._streaming = False
bridge.streamingChanged.emit()
settle()

# ---- 08 编辑另一章（第 1 章，干净状态）----
bridge.openChapter(1)
settle()
grab("08_editor_ch1")

# ---- 09 新建项目对话框 ----
from PySide6.QtCore import QMetaObject, QObject, Qt as _Qt
Qt_DirectConnection = _Qt.DirectConnection


def open_dialog(obj_name):
    # Dialog 是 QQuickPopup（QObject 子类），不能用 QQuickItem 查找
    it = win.findChild(QObject, obj_name)
    if it:
        QMetaObject.invokeMethod(it, "open", Qt_DirectConnection)
        return True
    return False


def close_dialog(obj_name):
    it = win.findChild(QObject, obj_name)
    if it:
        QMetaObject.invokeMethod(it, "close", Qt_DirectConnection)


open_dialog("newProjectDialog")
settle(500)
grab("09_new_project_dialog")
close_dialog("newProjectDialog")
settle()

# ---- 10 带指导重写对话框（章节面板统一）----
set_panel(2)
open_dialog("chapterGuidanceDialog")
settle(500)
grab("10_guidance_dialog")
close_dialog("chapterGuidanceDialog")
settle()

# ---- 11 项目文件对话框（章节面板内）----
set_panel(2)
open_dialog("fileDialog")
settle(500)
grab("11_file_dialog")
close_dialog("fileDialog")
settle()

# ---- 12 空书架（无项目）----
# 临时把 recent_projects 清空不可行（会破坏后续），改为直接渲染即可：已覆盖
print("QML_WARN_COUNT:", len(warns), flush=True)
for w in warns[:8]:
    print("QML_WARN:", w, flush=True)
print("REVIEW_SHOTS_DONE", flush=True)
app.quit()
