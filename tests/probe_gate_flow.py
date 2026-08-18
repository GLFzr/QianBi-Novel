# -*- coding: utf-8 -*-
"""Step Gates 门机制三用例回归：禁用自动过 / 带想法继续 / 回退归档+想法携带（无需 API Key）"""
import os, sys, tempfile, threading

# 隔离用户配置
_FH = tempfile.mkdtemp(prefix="qbn_gateflow_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project
from app.core import orchestrator as orch

# ---- 造一个临时项目：含大纲与一章正文 ----
tmp = tempfile.mkdtemp(prefix="qbn_gateflow_proj_")
proj = project.create_project(tmp, "门流测试")
os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
project.write_file(os.path.join(proj, "大纲", "大纲.md"), "# 全书大纲\n\n阶段总览…")
project.write_file(project.get_outline_path(proj, 1), "### 第 1 章：开场\n- 核心事件…")
chapter_path = project.get_chapter_path(proj, 1, "开场")
project.write_file(chapter_path, "# 第1章 开场\n\n正文内容。")

results = []

def case_auto_skip():
    cfg = {"writing": {"run_mode": "auto", "gate_hard": ["G2", "G5L", "G9"],
                       "gate_soft": ["G1", "G3", "G4", "G6", "G7", "G8"]}}
    o = orch.Orchestrator(proj, cfg)
    r = o.gate("G2", "大纲已生成")
    return r == ""  # 禁用 → 不阻塞直接返回空

def case_next_with_idea():
    cfg = {"writing": {"run_mode": "border", "gate_hard": ["G2"], "gate_soft": []}}
    o = orch.Orchestrator(proj, cfg)
    got = {}
    threading.Timer(0.3, lambda: got.update(ok=o.resolve_gate("next", "多加雨夜氛围"))).start()
    r = o.gate("G2", "大纲已生成", 1)
    return r == "多加雨夜氛围" and got.get("ok") is True

def case_return_archives_and_carries():
    cfg = {"writing": {"run_mode": "border", "gate_hard": ["G9"], "gate_soft": []}}
    o = orch.Orchestrator(proj, cfg)
    threading.Timer(0.3, lambda: o.resolve_gate("return", "重写本章")).start()
    r = o.gate("G9", "第 1 章已定稿", 1)
    # 回退 → 返回 None + 章节已归档删除 + 想法写入 carry
    chapter_gone = not os.path.exists(chapter_path)
    roll_dir = os.path.join(proj, "pipeline_debug", "rollback")
    archived = os.path.isdir(roll_dir) and any(os.listdir(roll_dir))
    carry = o.consume_gate_idea()
    return r is None and chapter_gone and archived and carry == "重写本章"

def case_soft_gate_blocks_in_border():
    cfg = {"writing": {"run_mode": "border", "gate_hard": ["G9"], "gate_soft": ["G3"]}}
    o = orch.Orchestrator(proj, cfg)
    threading.Timer(0.3, lambda: o.resolve_gate("next", "")).start()
    r = o.gate("G3", "细纲批完成", 1)
    return r == ""  # 软门在 border 模式下也等待（轻提示，回车继续）

# 送回退损坏的项目部件
project.write_file(os.path.join(proj, "大纲", "大纲.md"), "# 全书大纲\n\n阶段总览…")
project.write_file(project.get_outline_path(proj, 1), "### 第 1 章：开场\n- 核心事件…")

results.append(("auto 模式全门跳过", case_auto_skip()))
results.append(("border 模式 G2 硬停+带想法继续", case_next_with_idea()))
results.append(("step 模式 G9 回退归档+想法携带", case_return_archives_and_carries()))
results.append(("border 模式 G3 软门等待", case_soft_gate_blocks_in_border()))

print("=== Step Gate 流回归 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)