# -*- coding: utf-8 -*-
"""章节锁定跨档互斥探针（M4 · 无需 LLM / 无网络）：
G9 回退拒 locked / regenerateStage 不删 locked 章细纲 / attemptUnlock 放行 / migrate 保持
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_lockx_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project
from app.core.orchestrator import Orchestrator
from app.ui.bridge import Bridge

results = []


def check(name, cond):
    results.append((name, bool(cond)))


tmp = tempfile.mkdtemp(prefix="qbn_lockx_proj_")
proj = project.create_project(tmp, "跨档锁定探针")
chapter_path = project.get_chapter_path(proj, 3, "锁定章")
project.write_file(chapter_path, "# 第3章 锁定章\n\n正文内容。")
project.write_file(project.get_outline_path(proj, 2), "### 第 2 章：普通\n- 事件")
project.write_file(project.get_outline_path(proj, 3), "### 第 3 章：锁定\n- 事件")
project.write_file(project.get_outline_path(proj, 4), "### 第 4 章：后续\n- 事件")

# ---- ① G9 回退拒 locked（orchestrator worker 侧，同进程 project 锁守卫）----
cfg = {"writing": {"run_mode": "auto"}}
o = Orchestrator(proj, cfg)
project.set_chapter_locked(proj, 3, True)
roll_dir = os.path.join(proj, "pipeline_debug", "rollback")
o._apply_rollback("G9", 3)
check("G9 拒 locked 章", os.path.exists(chapter_path))
check("G9 拒 locked 不归档", not os.path.isdir(roll_dir))
# 解锁后放行
project.attempt_unlock(proj, 3)
o._apply_rollback("G9", 3)
check("解锁后 G9 放行", not os.path.exists(chapter_path))
# 恢复正文供后续用例
project.write_file(chapter_path, "# 第3章 锁定章\n\n正文内容。")

# ---- ② regenerateStage('ch_outline') 不删 locked 章细纲（nxt=4，只动 ≥4 的细纲）----
b = Bridge()
b.openProject(proj)
project.write_file(project.get_outline_path(proj, 4), "### 第 4 章：锁定契约\n- 事件")
project.write_file(project.get_outline_path(proj, 5), "### 第 5 章：后续\n- 事件")
project.write_file(project.get_outline_path(proj, 6), "### 第 6 章：后续\n- 事件")
project.set_chapter_locked(proj, 4, True)   # 章 4 无正文，仅锁定其细纲契约
b.regenerateStage("ch_outline", "")
check("细纲重生成跳过 locked 章", os.path.exists(project.get_outline_path(proj, 4))
      and not os.path.exists(project.get_outline_path(proj, 5))
      and not os.path.exists(project.get_outline_path(proj, 6)))
project.attempt_unlock(proj, 4)

# ---- ③ migrate 保持锁定（cw↔auto 双向）----
project.set_chapter_locked(proj, 3, True)
b.setCwMode(True)
b.setCwMode(False)
check("migrate 双向保持锁定", project.is_chapter_locked(proj, 3) is True)

print("=== 章节锁定跨档互斥探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
