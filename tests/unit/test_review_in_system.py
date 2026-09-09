# -*- coding: utf-8 -*-
"""V1-③ 审校指令模板化（writing.review_in_system，缺省关）回归

- 尾段切分：rubric（可进 system）+ 输出协议（必须近场）拼回原尾段，逐字不吞字
- 旗标关（缺省）：system 与审校轮逐字节等于旧行为（S1/S4 现状不惊动）
- 旗标开：①卷会话 system 携带 rubric；②审校轮剥掉 rubric 但**保留输出协议**
- 协议标记位置：六维标记只能在近场用户轮——进 system 会让模型整章回声（2026-09-09 实测）

全内存假件，无真实 API。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_review_in_system_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import prompts
from app.core.stages import REVIEW_PROTOCOL_MARKS, review_vote_structured
from app.prompts.review import (FINAL_REVIEW_PROMPT, review_instruction_tail,
                                review_output_protocol, review_static_tail)


def test_instruction_tail_nonempty_and_placeholder_free():
    tail = review_instruction_tail()
    assert tail and len(tail) > 4000
    assert "{" not in tail and "}" not in tail          # 零占位符 → 渲染后必为逐字节后缀
    assert FINAL_REVIEW_PROMPT.endswith(tail)           # 确为模板尾段


def test_split_is_lossless_rubric_has_no_protocol():
    """切分不能吞字，且 rubric 里必须一个协议标记都没有（否则"进 system"就是空转的成因）"""
    rubric, proto, full = review_static_tail(), review_output_protocol(), review_instruction_tail()
    assert rubric + proto == full                       # 逐字拼回
    assert len(rubric) > 2000 and len(proto) > 1000
    assert not any(m in rubric for m in REVIEW_PROTOCOL_MARKS), "rubric 混入了输出协议"
    for m in ("===A_GOLDEN_OPEN===", "===B_PAYOFF===", "===C_FINGER===", "===D_PLOT===",
              "===E_CHARACTER===", "===F_HOOK===", "===VERDICT==="):
        assert m in proto, f"输出协议缺 {m}"


def test_turn_text_strips_rubric_keeps_protocol_near_field():
    kw = dict(project_header="【H】", chapter_header="【章头】", prose="{prose}",
              worldbook_block="【世界书】", regex_block="【正则】",
              genre_review_extra="【题材专项】", l0_findings="【L0】")
    full = prompts.session_turn_text(FINAL_REVIEW_PROMPT).format(**kw)
    rubric, proto = review_static_tail(), review_output_protocol()
    assert full.endswith(rubric + proto)                # 全尾段是渲染后轮次的逐字节后缀
    # 与 stages 内一致的剥法：只剥 rubric，把输出协议留在近场
    turn = full[:-len(rubric + proto)].rstrip("\n") + "\n\n" + proto
    assert rubric not in turn                           # rubric 剥净（已随 system 载入）
    assert all(m in turn for m in REVIEW_PROTOCOL_MARKS[:6]), "输出协议被剥掉了→审校会空转"
    for block in ("【世界书】", "【正则】", "【题材专项】", "【L0】"):
        assert block in turn                            # 动态块全保留
    assert "最近一条完整的章正文消息" in turn            # 正文历史引用保留


def test_vote_structured_guard():
    """整章回声必须判"未产出协议"，而不是"审过没问题"——v7_long13 的 11/11 空转就漏在这"""
    echo = "周三、四、五，他都来，连着三个凌晨。\n他把单页折好放进口袋。\n" * 3
    assert review_vote_structured(echo) is False
    ok = '===A_GOLDEN_OPEN=== pass 【原文引证：“周三”】\n===TOTAL=== 0'
    assert review_vote_structured(ok) is True
    assert review_vote_structured("") is False and review_vote_structured(None) is False
