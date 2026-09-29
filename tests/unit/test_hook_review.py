# -*- coding: utf-8 -*-
"""T2 钩子账本·段2（C34-2）——审校 F 维钩型回写 + supervisor 上章钩子应答核对

三组钉测：
1. 同源：review.py 维 F rubric 与 co_writing supervisor 应答核对节的七型判据，
   逐行逐字来自 hook_vocab.HOOK_TYPE_CRITERIA（import 同源，不复制文本）；
   注入块零 ASCII 花括号（模板整体走 .format()）。
2. 回写解析：parse_hook_writeback（标签/档位/三态/引证锚）+
   apply_hook_writeback（审校裁决覆盖细纲自报值，原行不动，validate 兜底）。
   stages 落账接线为 TODO（B3 领地），本文件钉的是接线方必须遵守的形状。
3. supervisor「上章钩子应答核对」节：三态点名 + 断链顶「需调整」+
   报告「钩子应答」行 + 与 parse_supervisor_report 的派单契约兼容。
"""
import os
import string
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.prompts import review as rv
from app.prompts.co_writing import CO_SUPERVISOR_PROMPT
from app.prompts.hook_vocab import (
    HOOK_TYPE_CRITERIA, HOOK_TYPES, parse_hook_record, validate_hook_row,
)

SAMPLE_OUTLINE = """### 第 21 章：清账夜
- 章节定位：高压
- 章尾钩子：陈更发现当票上多出第三枚指印，怀疑铺子里有内鬼。期待度：强；钩型：悬念缺口；与下一章承接：开查内鬼
"""


# ---------- 1. 判据 import 同源（不复制文本） ----------

def test_f_dim_criteria_same_source():
    """维 F rubric 的七型判据与 hook_vocab 逐字一致（长文 rubric / 紧凑票 / system 尾段）"""
    for t in HOOK_TYPES:
        line = f"- {t}：{HOOK_TYPE_CRITERIA[t]}"
        assert line in rv.FINAL_REVIEW_PROMPT, f"维 F rubric 缺判据：{t}"
        assert line in rv.FINAL_REVIEW_COMPACT, f"紧凑票缺判据：{t}"
        assert line in rv.review_static_tail(), f"system 尾段缺判据：{t}"
    # 判据块本体与模板内出现的一致（单一出处，不是两份手抄）
    assert rv.hook_criteria_block() in rv.FINAL_REVIEW_PROMPT


def test_criteria_block_brace_free():
    """判据块拼接进 .format() 模板：出现 ASCII 花括号即装配隐患"""
    block = rv.hook_criteria_block()
    assert "{" not in block and "}" not in block
    assert [block.index(t) for t in HOOK_TYPES] == \
        sorted(block.index(t) for t in HOOK_TYPES)


def test_f_dim_writeback_instructions():
    """维 F 带三处回写指令与「无型」哨兵；F_HOOK 输出行带回写标签契约"""
    assert "钩型回写" in rv.FINAL_REVIEW_PROMPT
    assert rv.FINAL_REVIEW_PROMPT.count("覆盖细纲自报") >= 3   # 钩型/烈度/事件钩三处
    assert "「无型」" in rv.FINAL_REVIEW_PROMPT
    assert "【钩型：七型之一或无型｜烈度：强/中/弱｜事件钩：是/否】" in rv.FINAL_REVIEW_PROMPT
    # 输出协议 ===F_HOOK=== 行承载回写标签（模型照此输出，解析端才有的解析）
    f_line = [ln for ln in rv.FINAL_REVIEW_PROMPT.splitlines()
              if ln.startswith("===F_HOOK===")]
    assert f_line and "回写标签" in f_line[0] and "钩子账本" in f_line[0]


def test_compact_protocol_writeback_note():
    """紧凑票字段纪律带 F 维回写标签说明（两档协议回写能力一致）"""
    assert "回写标签" in rv.REVIEW_COMPACT_PROTOCOL
    assert "覆盖细纲自报值" in rv.REVIEW_COMPACT_PROTOCOL


# ---------- 2. 回写解析：F 维裁决覆盖细纲自报值 ----------

def test_parse_hook_writeback_full_tag():
    """全标签 + 长文引证：四字段齐全（type 归一/strength 三档/三态/事件锚）"""
    text = ('===F_HOOK=== pass 钩子成立 【钩型：悬念缺口｜烈度：强｜事件钩：是】'
            '【原文引证："他翻到最后一页，第 7 条规则被红笔划掉"】')
    wb = rv.parse_hook_writeback(text)
    assert wb["type"] == "悬念缺口"
    assert wb["strength"] == "强"
    assert wb["is_event_hook"] is True
    assert wb["event_kw"] == "他翻到最后一页，第 7 条规则被红笔划掉"


def test_parse_hook_writeback_variants():
    """半角分隔/「无型」/乱型/缺档/缺标签：封闭归一，非法值一律落空哨兵"""
    wb = rv.parse_hook_writeback("理由 【钩型：危机迫近|烈度：弱|事件钩：否】")
    assert wb == {"type": "危机迫近", "strength": "弱", "is_event_hook": False,
                  "event_kw": ""}
    # 「无型」与乱型 → type=""（不覆盖自报）；非法烈度档 → ""；未标注事件钩 → None
    wb = rv.parse_hook_writeback("【钩型：无型｜烈度：爆｜事件钩：】")
    assert wb["type"] == "" and wb["strength"] == "" and wb["is_event_hook"] is None
    wb = rv.parse_hook_writeback("【钩型：天外飞仙｜烈度：中｜事件钩：是】")
    assert wb["type"] == "" and wb["strength"] == "中" and wb["is_event_hook"] is True
    # 无标签 → 全空（落账侧据此整行保留细纲自报值）
    assert rv.parse_hook_writeback("===F_HOOK=== pass 有钩") == {
        "type": "", "strength": "", "is_event_hook": None, "event_kw": ""}
    assert rv.parse_hook_writeback("")["is_event_hook"] is None


def test_apply_hook_writeback_overrides_self_report():
    """核心语义：审校裁决覆盖细纲自报值——自报强/悬念缺口/事件钩被回写改判"""
    row = parse_hook_record(21, SAMPLE_OUTLINE).to_row()
    assert row["type"] == "悬念缺口" and row["strength"] == "强"
    wb = rv.parse_hook_writeback(
        '===F_HOOK=== marginal 纯氛围定格 【钩型：意象异变｜烈度：弱｜事件钩：否】'
        '【原文引证："夜色压下来，谁也没说话"】')
    new = rv.apply_hook_writeback(row, wb)
    assert new["type"] == "意象异变" and new["strength"] == "弱"
    assert new["is_event_hook"] is False and new["event_kw"] == ""   # 裁否同步清引文
    assert validate_hook_row(new) == []
    assert row["type"] == "悬念缺口" and row["strength"] == "强"     # 原行不动


def test_apply_hook_writeback_noop_on_empty():
    """空回写 = 整行保留自报值（dict 级无变化）"""
    row = parse_hook_record(21, SAMPLE_OUTLINE).to_row()
    assert rv.apply_hook_writeback(row, {}) == row
    assert rv.apply_hook_writeback(
        row, rv.parse_hook_writeback("===F_HOOK=== pass 有钩")) == row


def test_apply_hook_writeback_event_yes_backfills_quote_kw():
    """裁「是」而自报无事件词 → 从审校引证补事件锚，账本一致性不被破坏"""
    outline = ("### 第 5 章\n- 章节定位：推进\n"
               "- 章尾钩子：门外传来叩门声，三长两短。期待度：中；钩型：危机迫近\n")
    row = parse_hook_record(5, outline).to_row()
    assert row["event_kw"] == "" and row["is_event_hook"] is False
    wb = rv.parse_hook_writeback(
        '===F_HOOK=== pass 期限压迫 【钩型：危机迫近｜烈度：中｜事件钩：是】'
        '【原文引证："门外传来叩门声"】')
    new = rv.apply_hook_writeback(row, wb)
    assert new["is_event_hook"] is True and new["event_kw"] == "门外传来叩门声"
    assert validate_hook_row(new) == []


# ---------- 3. supervisor「上章钩子应答核对」节 ----------

def test_supervisor_hook_answer_section():
    """节在场 + 三态点名 + 上章无钩 + 断链顶到「需调整」结论（派单契约消费结论行）"""
    assert "上章钩子应答核对" in CO_SUPERVISOR_PROMPT
    for state in ("已承接", "显式延后", "无应答", "上章无钩"):
        assert state in CO_SUPERVISOR_PROMPT, f"应答三态缺 {state}"
    assert "断链" in CO_SUPERVISOR_PROMPT and "需调整" in CO_SUPERVISOR_PROMPT
    # 报告体新增「钩子应答」行（parse_supervisor_report 只认结论/改写指令行，不冲突）
    assert "- 钩子应答：" in CO_SUPERVISOR_PROMPT


def test_supervisor_criteria_same_source_and_brace_free():
    """supervisor 判据与 hook_vocab 逐字同源；注入块零 ASCII 花括号且装配不炸"""
    m = CO_SUPERVISOR_PROMPT.index("上章钩子应答核对")
    m = CO_SUPERVISOR_PROMPT.index("## 报告范围", m)
    section = CO_SUPERVISOR_PROMPT[CO_SUPERVISOR_PROMPT.index("### 上章钩子应答核对"):m]
    assert "{" not in section and "}" not in section
    for t in HOOK_TYPES:
        assert f"- {t}：{HOOK_TYPE_CRITERIA[t]}" in section, f"supervisor 缺判据：{t}"
    # 既有占位符不丢（test_barrier_removal 钉值的同口径复述）+ format 冒烟
    for ph in ("{chapter_num}", "{chapter_outline}", "{previous_ending}",
               "{chapter_text}", "{next_outline_brief}"):
        assert ph in CO_SUPERVISOR_PROMPT
    names = {f for _, f, _, _ in string.Formatter().parse(CO_SUPERVISOR_PROMPT) if f}
    rendered = CO_SUPERVISOR_PROMPT.format(**{n: "占位" for n in names})
    assert "上章钩子应答核对" in rendered and "- 钩子应答：" in rendered


def test_supervisor_report_with_hook_line_still_parses():
    """带「钩子应答」行的报告仍走派单契约解析（结论/改写指令不受新行干扰）"""
    from app.core import co_dialogue
    text = ("### 主 Agent 报告\n- 衔接：OK\n"
            "- 钩子应答：无应答（上章末钩「第三枚指印」悬空）·上章末钩钩型：意象异变\n"
            "- 范围：未越界\n- 结论：需调整（钩子断链）\n"
            "- 【改写指令】开篇先接住第三枚指印的追问，再进入本章主线。")
    assert co_dialogue.supervisor_report_has_conclusion(text)
    needs_fix, directive = co_dialogue.parse_supervisor_report(text)
    assert needs_fix is True
    assert "第三枚指印" in directive
