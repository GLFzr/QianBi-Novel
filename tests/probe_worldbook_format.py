# -*- coding: utf-8 -*-
"""世界书格式回归探针（SEV-2 · 无需 LLM / 无网络 / router 打桩）：
断言正文/审校/细纲三段 prompt 的组装期 .format 行为：
① 世界书/正则块注入不抛 KeyError ② 空串回退占位 ③ 缺参抛错对照（证明占位非静默吞 bug）
④ regex_rules 解析（逻辑约束集默认 / 字面正则样本备选）
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_wbf_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from app import project, prompts
from app.prompts import scene_cards
from app.core import stages

results = []


def check(name, cond):
    results.append((name, bool(cond)))


tmp = tempfile.mkdtemp(prefix="qbn_wbf_proj_")
proj = project.create_project(tmp, "世界书格式探针")
project.write_file(os.path.join(proj, "设定", "题材定位.md"),
                   "# 题材定位\n\n## 主要角色表\n| 角色 | 定位 |\n主角 | 改命者 |")
project.write_file(os.path.join(proj, "设定", "世界书.md"),
                   "## 世界书\n\n力量体系：每次改写命运都必须付出对等代价。\n")
project.write_file(os.path.join(proj, "设定", "正则.md"),
                   "# 正则（逻辑约束规则集）\n"
                   "- 规则：每次改命必须有可追溯的代价索回｜level：must｜scope：全书\n"
                   "- 规则：单元案件须有完整结构｜level：should｜scope：单元")

# ---- ① 三段 prompt 组装期 .format（照 stages.py 真实组装参数）----

prose_prompt = prompts.PROSE_WRITING_PROMPT.format(
    chapter_num=1, core_setting="设定", outline="细纲", next_chapter_brief="预告",
    global_summary="摘要", recent_summaries="近三章", character_states="角色状态",
    foreshadows="伏笔", timeline="时间线", previous_excerpt="上文", style_sample="文风",
    user_guidance="指导", user_ideas="想法", word_target=3000,
    tic_blacklist="（无）", used_setpieces="（无）", genre_block="（通用）",
    worldbook_block=project.worldbook_text(proj),
    regex_block=project.regex_block(proj, "logic"),
    craft_block=scene_cards.craft_block(1, 10, "细纲"),
    author_note="每章至少一处可指认的物件反应",
)
check("正文 prompt 注入世界书", "力量体系" in prose_prompt and "世界书" in prose_prompt)
check("正文 prompt 注入工艺路线", "主卡·" in prose_prompt and "本章演法" in prose_prompt)
check("作者按落在正文 prompt 近端",
      prose_prompt.index("作者按") > prose_prompt.index("去 AI 味红线")
      and "可指认的物件反应" in prose_prompt)
check("正文 prompt 注入 must 规则", "必须成立" in prose_prompt or "代价索回" in prose_prompt)

review_prompt = prompts.REVIEW_PROMPT.format(
    chapter_num=1, genre_review_extra="（无专项）", prose="正文", core_setting="设定",
    global_summary="摘要", character_states="状态", foreshadows="伏笔", timeline="时间线",
    worldbook_block=project.worldbook_text(proj),
    regex_block=project.regex_block(proj, "logic"),
)
check("审校 prompt 注入世界书/正则", "力量体系" in review_prompt and "must" in review_prompt)

outline_prompt = prompts.CHAPTER_OUTLINE_PROMPT.format(
    chapter_num=1, volume_outline="卷纲", nearby_outlines="相邻细纲",
    core_setting_brief="设定", start_chapter=1, end_chapter=2, count=2,
    chapter_words=3000, chapter_words_max=3300, next_chapter=2,
    previous_ending="上文结尾", foreshadows="伏笔", unit_contract="单元契约",
    genre_block="（通用）", global_summary="摘要", recent_summaries="近三章",
    character_states="角色状态",
    worldbook_block=project.worldbook_text(proj),
    regex_block=project.regex_block(proj, "logic"),
    user_directive="（无）",
)
check("细纲 prompt 注入世界书/正则", "力量体系" in outline_prompt and "代价索回" in outline_prompt)

# ---- ② 空串回退（旧项目无世界书/正则文件 → 占位不抛 KeyError）----
proj_old = project.create_project(tempfile.mkdtemp(prefix="qbn_wbf_old_"), "旧项目")
check("无文件世界书占位", "尚未生成世界书" in project.worldbook_text(proj_old))
check("无文件正则占位", "尚未生成正则" in project.regex_block(proj_old))
p2 = prompts.PROSE_WRITING_PROMPT.format(
    chapter_num=1, core_setting="", outline="", next_chapter_brief="", global_summary="",
    recent_summaries="", character_states="", foreshadows="", timeline="", previous_excerpt="",
    style_sample="", user_guidance="无特殊指导", user_ideas="（无）", word_target=3000,
    tic_blacklist="（无）", used_setpieces="（无）", genre_block="（通用）",
    worldbook_block=project.worldbook_text(proj_old),
    regex_block=project.regex_block(proj_old, "logic"),
    craft_block=scene_cards.craft_block(1, 0, ""), author_note="（本章无作者按）",
)
check("空串回退组装不抛", "尚未生成世界书" in p2)

# ---- ③ 缺参抛错对照（占位不是静默吞 bug）----
try:
    prompts.PROSE_WRITING_PROMPT.format(
        chapter_num=1, core_setting="", outline="", next_chapter_brief="", global_summary="",
        recent_summaries="", character_states="", foreshadows="", previous_excerpt="",
        style_sample="", user_guidance="", user_ideas="", word_target=3000,
        tic_blacklist="", used_setpieces="", genre_block="",
        # 故意缺 worldbook_block / regex_block
    )
    check("缺参抛错对照", False)
except KeyError as e:
    check("缺参抛错对照", "worldbook_block" in str(e) or "regex_block" in str(e))

# ---- ④ regex_rules 解析（逻辑约束集 / 字面正则样本）----
rules = project.regex_rules(proj, "logic")
check("解析出 2 条规则", len(rules) == 2)
check("must/should 分级", {r["level"] for r in rules} == {"must", "should"})
check("scope 解析", any(r["scope"] == "单元" for r in rules))
check("空文件返回空列表", project.regex_rules(proj_old, "logic") == [])
project.write_file(os.path.join(proj_old, "设定", "正则.md"),
                   "# 字面正则样本\n- 禁止连续三个感叹号：`!{3,}`\n- 数字用全角：`[0-9]`")
rr = project.regex_rules(proj_old, "regex")
check("字面正则样本解析", len(rr) == 2 and rr[0]["rule"] == "!{3,}")

# ---- ⑤ 世界书总结产物拆分（共写确定 → 两文件）----
wb, rg = project.split_worldbook_product(
    "## 世界书\n力量体系…\n\n## 正则（逻辑约束规则集）\n- 规则：X｜level：must｜scope：全书")
check("产物拆分世界书", wb.strip() == "## 世界书\n力量体系…" and "力量体系" in wb)
check("产物拆分正则段", rg.startswith("## 正则") and "must" in rg)
wb2, rg2 = project.split_worldbook_product("## 世界书\n只有世界书")
check("无正则段容错", rg2 == "" and "世界书" in wb2)
# 真机取证：模型常写单井号「# 正则」，只认 ``##`` → 整段约束留在世界书里，regex_rules 恒空
wb3, rg3 = project.split_worldbook_product(
    "# 世界书\n力量体系…\n\n# 正则（逻辑约束规则集）\n- 规则：A｜level：must｜scope：全书")
check("单井号正则段也拆得出", rg3.startswith("# 正则") and "世界书" in wb3 and "正则" not in wb3)
# 节内 ``###`` 子标题属本段：旧的「下一任意级别标题即止」会把子节后面的规则丢掉
wb4, rg4 = project.split_worldbook_product(
    "## 世界书\n力量体系…\n\n## 正则\n- 规则：A｜level：must\n\n### 文风约束\n"
    "- 规则：B｜level：should\n\n## 其他\n收尾")
check("正则节内子标题不截断", "规则：A" in rg4 and "规则：B" in rg4)
check("正则段止于更浅层标题", rg4.splitlines()[-1].startswith("- 规则：B") and "其他" not in rg4)
check("正则段后的小节拼回世界书", "收尾" in wb4 and "其他" in wb4 and "正则" not in wb4)
project.write_file(os.path.join(proj_old, "设定", "正则.md"), rg4)
check("拆出的正则段可被解析", len(project.regex_rules(proj_old, "logic")) == 2)

print("=== 世界书格式回归探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
