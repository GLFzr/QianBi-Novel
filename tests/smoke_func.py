# -*- coding: utf-8 -*-
"""功能冒烟测试：不触网，验证 Bridge/项目/状态机/队列模型"""
import os, sys, shutil, tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer

app = QGuiApplication(sys.argv)

from app.ui.bridge import Bridge
from app import project
from app.core import state as st
from app.core.orchestrator import Orchestrator

bridge = Bridge()

# 1. 新建项目
tmp = os.path.join(os.getcwd(), "smoke_tmp")
if os.path.exists(tmp):
    shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
ok = bridge.newProject(tmp, "冒烟测试书", "悬疑脑洞", "番茄", 100, "主角捡到能改命的笔记")
assert ok and bridge.hasProject, "newProject failed"
proj = os.path.join(tmp, "冒烟测试书")
assert project.is_project(proj), "project structure missing"
assert os.path.exists(os.path.join(proj, "追踪", "全局摘要.md")), "memory template missing"
print("1 newProject OK ->", proj)

# 2. 队列模型（空项目应为空列表）
bridge.refreshQueue()
print("2 queue rows =", bridge.chapterModel.rowCount())

# 3. 细纲与正文伪造成员 → 队列状态判定
project.write_file(project.get_outline_path(proj, 1), "### 第 1 章：雨夜入局\n- 核心事件：...")
project.write_file(project.get_outline_path(proj, 2), "### 第 2 章：摊牌\n- 核心事件：...")
project.write_file(project.get_chapter_path(proj, 1, "雨夜入局"), "# 第1章 雨夜入局\n\n雨点敲在窗棂上。" * 50)
state = st.load_state(proj)
state["total_chapters"] = 333
st.append_history(proj, state, {"num": 1, "title": "雨夜入局", "words": 700,
                                "deslop_blocking": 0, "deslop_advisory": 2, "status": "pass"})
bridge.refreshQueue()
# StateRole = Qt.UserRole + 3（用 roleNames 反查，避免硬编码魔法数字）
state_role = next(r for r, name in bridge.chapterModel.roleNames().items() if name == b"state")
rows = [bridge.chapterModel.data(bridge.chapterModel.index(i), state_role) for i in range(bridge.chapterModel.rowCount())]
print("3 queue states =", rows)
assert rows[0] == "pass" and rows[1] == "outline_ready", rows
print("3 progress =", bridge.progressText)

# 4. 摘要链读写
from app.core import memory
memory.append_chapter_summary(proj, 1, "雨夜入局", "主角雨夜捡到笔记，写下第一行改命文字")
memory.write_global_summary(proj, "主角获得改命笔记，代价未知。")
assert "雨夜" in memory.read_recent_summaries(proj, 2, 3)
assert "改命笔记" in memory.read_global_summary(proj)
print("4 memory chain OK")

# 5. Orchestrator 可实例化（不启动）
orch = Orchestrator(proj, bridge.cfg)
orch.pause(); assert orch.paused
orch.resume(); assert not orch.paused
print("5 orchestrator control OK")

# 6. 连接模型与槽位
assert bridge.connectionModel.rowCount() >= 2
opts = bridge.connectionOptions()
assert opts[0]["boundSlots"], opts
print("6 connections =", bridge.connectionModel.rowCount(), "slots =", opts[0]["boundSlots"])

# 7. 打开章节 + 扫描
bridge.openChapter(1)
assert "雨点" in bridge.chapterText
bridge.scanChapterText(bridge.chapterText + "——他的眼神不是愤怒，而是冷漠")
assert len(bridge.chapterFindings) > 0, "deslop should catch blocking pattern"
print("7 chapter open + deslop scan OK, findings =", len(bridge.chapterFindings))

shutil.rmtree(tmp, ignore_errors=True)
print("ALL_FUNC_OK")
QTimer.singleShot(100, app.quit)
app.exec()
