# -*- coding: utf-8 -*-
"""V1-V3 三路审核产出问题的回归钉（audit_v1_matrix/audit_v2_quality/audit_v3_discipline）。

- V1：Main.qml rollbackBanner 子级裸引 rb（无 id 解析）→ 启动 ReferenceError ×3，
  打爆零 QML 警告闸门——源钉防复发。
- V2 中危：chapter_microcycle 入口必须清零 ctx.review_v2（ctx 跨章单例残留，
  断路/人工/字数拦截章 finalize 吃上一章 B_PAYOFF 误入账）——源钉 + 解析行为钉。
- V2 低危：parse_supervisor_report 对「部分通过/基本通过」必须 needs_fix=True
  （F3 结论门不得直锁）——纯函数行为钉。
"""
import ast
import io
import os
import re

import pytest

from app.core import co_dialogue

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------- V2 低危：F3 结论门 ----------

def test_parse_supervisor_report_partial_pass_needs_fix():
    needs_fix, _ = co_dialogue.parse_supervisor_report("- 结论：部分通过（2 处待修）")
    assert needs_fix is True


def test_parse_supervisor_report_basic_pass_needs_fix():
    needs_fix, _ = co_dialogue.parse_supervisor_report("- 结论：基本通过")
    assert needs_fix is True


def test_parse_supervisor_report_clean_pass_not_needs_fix():
    needs_fix, directive = co_dialogue.parse_supervisor_report("- 结论：通过")
    assert needs_fix is False and directive == ""


def test_parse_supervisor_report_needs_fix_still_detected():
    needs_fix, _ = co_dialogue.parse_supervisor_report("- 结论：需调整（第 3 段节奏拖）")
    assert needs_fix is True


# ---------- V2 中危：chapter_microcycle 入口清零 review_v2（源钉） ----------

def test_microcycle_entry_resets_stale_review_v2():
    src = open(os.path.join(ROOT, "app", "core", "stages.py"),
               encoding="utf-8").read()
    fn = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "chapter_microcycle"))
    body_head = fn.splitlines()[:12]
    assert any("ctx.review_v2 = None" in ln for ln in body_head), (
        "chapter_microcycle 入口缺少 ctx.review_v2 清零——跨章残留会让"
        "断路/人工/字数拦截章吃到上一章 B_PAYOFF 误入账（audit_v2 中危）")


# ---------- V1：Main.qml rollbackBanner 子级裸引 rb（源钉） ----------

def test_main_qml_rollback_banner_children_use_qualified_rb():
    src = open(os.path.join(ROOT, "app", "ui", "qml", "Main.qml"),
               encoding="utf-8").read()
    banner_start = src.index("id: rollbackBanner")
    banner_end = src.index("backflowStaleBanner", banner_start)
    banner = src[banner_start:banner_end]
    # 子级裸引 rb（非 rollbackBanner.rb、非声明行、非 rb.active 本对象自引）
    bare = [m.group(0) for m in re.finditer(r"(?<!rollbackBanner\.)(?<!\w)rb\.\w+", banner)]
    own = len(re.findall(r"readonly property var rb", banner)) + len(
        re.findall(r"visible: rb\.active", banner))
    assert len(bare) <= own - 1 + 0 or not bare, (
        f"rollbackBanner 子级仍有裸引 rb（QML 子级不可见中间对象属性，启动 ReferenceError）：{bare}")
