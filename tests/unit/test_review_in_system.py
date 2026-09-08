# -*- coding: utf-8 -*-
"""V1-③ 审校指令模板化（writing.review_in_system，缺省关）回归

- 尾段提取：零占位符、非空、来自 FINAL_REVIEW_PROMPT 的既定标记之后
- 旗标关（缺省）：system 与审校轮逐字节等于旧行为（S1/S4 现状不惊动）
- 旗标开：①卷会话 system 携带尾段；②审校轮不再重复尾段（动态块保留）；
  ③副本票快照继承带尾段的 system（并行票同样命中）
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
from app.prompts.review import FINAL_REVIEW_PROMPT, review_static_tail


def test_static_tail_nonempty_and_placeholder_free():
    tail = review_static_tail()
    assert tail and len(tail) > 4000
    assert "{" not in tail and "}" not in tail          # 零占位符 → 渲染后必为逐字节后缀
    assert FINAL_REVIEW_PROMPT.endswith(tail)           # 确为模板尾段


def test_turn_text_strips_tail_and_keeps_dynamic_blocks():
    kw = dict(project_header="【H】", chapter_header="【章头】", prose="{prose}",
              worldbook_block="【世界书】", regex_block="【正则】",
              genre_review_extra="【题材专项】", l0_findings="【L0】")
    full = prompts.session_turn_text(FINAL_REVIEW_PROMPT).format(**kw)
    tail = review_static_tail()
    assert full.endswith(tail)                          # 尾段是渲染后轮次的逐字节后缀
    stripped = full[:-len(tail)].rstrip("\n")
    assert tail not in stripped                          # 尾段剥净
    for block in ("【世界书】", "【正则】", "【题材专项】", "【L0】"):
        assert block in stripped                         # 动态块全保留
    # 章头被 session_turn_text 剥离是 S1 既有设计（章头在本章开幕轮里，不在审校轮）
    assert "【章头】" not in stripped
    assert "最近一条完整的章正文消息" in stripped          # 正文历史引用保留
