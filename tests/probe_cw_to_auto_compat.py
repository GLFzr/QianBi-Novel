# -*- coding: utf-8 -*-
"""cw→自动档互续兼容探针（方案 §9 · 无需 LLM / 无网络）：
用共写档总结产物（build_handoff 拆分后的 product）喂自动档读取器，断言硬结构依赖不破：
(a) _roster 抽得到主要角色表 (b) _unit_contract 抽得到章节区间块
(c) stage_volume_outline 正常 format (d) planned_chapters 读得出预计总字数
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_c2a_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from app import project, prompts
from app.core import stages
from app.core import co_dialogue
from app.core import state as st

results = []


def check(name, cond):
    results.append((name, bool(cond)))


tmp = tempfile.mkdtemp(prefix="qbn_c2a_proj_")
proj = project.create_project(tmp, "互续探针")

# ---- 模拟 cw 各阶段「确定」产物（经 build_handoff 拆分后落盘）----
core_product, _ = co_dialogue.build_handoff(st.STAGE_CW_CORE, (
    "## 题材定位\n主角捡到能改命的笔记，改写命运需付代价。\n\n"
    "## 主要角色表\n| 角色 | 定位 | 特点 | 关系 | 成长线 |\n"
    "| 沈默 | 主角 | 谨慎 | 与秦岚搭档 | 从改命菜鸟到规则掌控者 |\n\n"
    "## 读者契约\n每次改写必索回代价。\n\n"
    "→ 下阶段交接\n- 关键事实：改命笔记\n"))
project.write_file(os.path.join(proj, "设定", "题材定位.md"), core_product)

outline_product, _ = co_dialogue.build_handoff(st.STAGE_CW_OUTLINE, (
    "## 第1章-第30章 开篇单元：改命初显\n- 主线：沈默学会改命规则\n\n"
    "## 第31章-第60章 单元二\n- 主线：组织浮现\n\n预计总字数：100\n\n"
    "→ 下阶段交接\n- 关键事实：单元二\n"))
project.write_file(os.path.join(proj, "大纲", "大纲.md"), outline_product)

project.write_idea_info(proj, "都市悬疑", "番茄", "主角捡到能改命的笔记", 100)

# (a) 自动档花名册（_roster 正则抽 ## 主要角色表）
roster = stages._roster(proj)
check("_roster 抽得角色表", "沈默" in roster)

# (b) 自动档单元对账（_unit_contract 正则抽章节区间块：30 落在 1-30 单元内）
contract = stages._unit_contract(proj, 30)
check("_unit_contract 抽得章节区间", "第1章-第30章" in contract)
contract2 = stages._unit_contract(proj, 60)
check("_unit_contract 命中后段单元", "第31章-第60章" in contract2)

# (c) 自动档全书大纲 stage 正常 format（读取器组装不抛 KeyError）
volume_prompt = prompts.VOLUME_OUTLINE_PROMPT.format(
    core_setting=project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:4000],
    total_words=100, chapter_words=3000,
    genre_block=stages._genre_block(proj, "outline"))
check("stage_volume_outline format 正常", "100 万字" in volume_prompt)

# (d) 自动档计划章数（planned_chapters 读 预计总字数）
check("planned_chapters 读得字数", project.planned_chapters(proj, 3000) == 333)

# (e) 共写世界书/正则落盘 → 自动档注入块可读（互续链完整）
project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n对等代价体系。")
project.write_file(os.path.join(proj, "设定", "正则.md"),
                   "- 规则：改命必须索回代价｜level：must｜scope：全书")
check("世界书块注入", "对等代价" in project.worldbook_text(proj))
check("正则块注入", "must" in project.regex_block(proj, "logic"))

print("=== cw→自动档互续兼容探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
