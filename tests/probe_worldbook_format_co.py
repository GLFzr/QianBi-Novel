# -*- coding: utf-8 -*-
"""共写世界书三 prompt 探针（router 打桩 · 无需 LLM / 无网络）：
① 世界书 Agent 对话 prompt 组装（参考块注入世界书/正则 + grow_* 方向 + 空串回退）
② 世界书总结 prompt 组装（产物结构含「## 正则（逻辑约束规则集）」）
③ grow_block 参考字段：缺字段/无预设占位、有字段注入、不进 genre_block
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_wbfco_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from app import project, prompts
from app.core import co_dialogue
from app.core import state as st

results = []


def check(name, cond):
    results.append((name, bool(cond)))


tmp = tempfile.mkdtemp(prefix="qbn_wbfco_proj_")
proj = project.create_project(tmp, "共写世界书探针")
project.write_file(os.path.join(proj, "设定", "题材定位.md"), "# 题材定位\n\n## 主要角色表\n| 主角 |")
project.write_file(os.path.join(proj, "大纲", "大纲.md"), "# 全书大纲\n\n## 第1章-第30章 开篇单元")
project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n力量体系：对等代价。")
project.write_file(os.path.join(proj, "设定", "正则.md"),
                   "- 规则：改命必须索回代价｜level：must｜scope：全书")

# ---- ① 世界书 Agent 对话 prompt 组装（参考块注入 + grow_* 方向）----
ref = co_dialogue.compose_reference_block(proj, st.STAGE_CW_WORLDBOOK, "cultivation")
check("参考块含现有世界书", "力量体系" in ref)
check("参考块含正则 must", "索回代价" in ref and "must" in ref)
check("参考块含 grow_worldbook_direction", "世界书应覆盖板块" in ref)
check("参考块含 grow_regex_direction", "必须成立约束" in ref)

role = prompts.CO_ROLES[st.STAGE_CW_WORLDBOOK]
prompt1 = prompts.CO_DIALOGUE_PROMPT.format(
    role_desc=role["role"], agent_name=role["agent"],
    handoff="关键事实：力量体系=对等代价",
    reference_block=ref,
    transcript="作者：力量体系再细化",
    user_message="把宗门规则也写进去",
)
check("对话 prompt 组装不抛", "宗门规则" in prompt1 and "世界书 Agent" in prompt1)

# 空串回退：无世界书/正则文件的项目
proj_old = project.create_project(tempfile.mkdtemp(prefix="qbn_wbfco_old_"), "旧项目")
ref_old = co_dialogue.compose_reference_block(proj_old, st.STAGE_CW_WORLDBOOK, "cultivation")
check("空串回退占位", "尚未生成世界书" in ref_old and "尚未生成正则" in ref_old)
prompt_old = prompts.CO_DIALOGUE_PROMPT.format(
    role_desc=role["role"], agent_name=role["agent"], handoff="（无）",
    reference_block=ref_old, transcript="（空）", user_message="hi")
check("旧项目对话组装不抛", "hi" in prompt_old)

# ---- ② 世界书总结 prompt 组装（产物结构强制正则段）----
prompt2 = prompts.CO_SUMMARIZE_PROMPT.format(
    stage_label=st.CW_STAGE_LABELS[st.STAGE_CW_WORLDBOOK],
    product_structure=prompts.CO_PRODUCT_STRUCTURES[st.STAGE_CW_WORLDBOOK],
    transcript="作者：规则定为逻辑约束集",
)
check("总结 prompt 含正则结构", "## 正则（逻辑约束规则集）" in prompt2)
check("总结 prompt 强制交接小节", "→ 下阶段交接" in prompt2)

# ---- ③ grow_block：缺字段/无预设占位、有字段注入、不进 genre_block ----
from app import presets as genre_presets
gb = genre_presets.grow_block("cultivation", "grow_unit_logic")
check("grow 有字段注入", "单元细纲逻辑" in gb and "不得锁定" in gb)
check("grow 缺字段占位", genre_presets.grow_block("cultivation", "grow_xxx") == "（该预设未提供此参考）")
check("grow 无预设占位", "通用流程" in genre_presets.grow_block("", "grow_core_template"))
legacy = {"id": "legacy_old", "name": "旧预设", "style_hint": "x"}
import json
lp = os.path.join(genre_presets.user_dir(), "legacy_old.json")
with open(lp, "w", encoding="utf-8") as f:
    json.dump(legacy, f, ensure_ascii=False)
check("旧 JSON 缺 grow 字段不报错", "未提供此参考" in genre_presets.grow_block("legacy_old", "grow_core_template"))
check("grow 不进 genre_block", "grow_" not in genre_presets.genre_block("cultivation"))

print("=== 共写世界书三 prompt 探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
