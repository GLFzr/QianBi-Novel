# -*- coding: utf-8 -*-
"""span 级修订输出单测（v0.20 成本战役 E1.1/O1）：annotate / parse_spans / apply_spans / span_stats

- 覆盖工作指南 DoD 的 5 类畸形输入：① 非 JSON ② JSON 截断 ③ para 越界 ④ op 非法 ⑤ replace 缺 text
- 合法 round-trip（annotate → 模拟模型输出 → apply）、未点名段落逐字节保留、标记剥离
- 无 LLM 调用、无网络，纯函数测试
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.span_edit import (
    OUTPUT_CONTRACT,
    SpanEditError,
    annotate,
    apply_spans,
    parse_spans,
    span_stats,
)

# 四段正文（一行一段，网文惯例）
PROSE = ("第一段：少年推开柴门。\n"
         "第二段：山风裹着雪粒扑面而来。\n"
         "第三段：他握紧了手中的剑。\n"
         "第四段：远处山寺的钟声响了。")


# ---- 测试 1：annotate 编号 ----

def test_annotate_numbering_basic():
    """非空行按出现顺序连续编号，标题行同样参与编号"""
    src = "# 第一章 试炼\n\n第一段正文。\n\n第二段正文。"
    lines = annotate(src).split("\n")
    assert lines[0] == "⟦P01⟧ # 第一章 试炼"
    assert lines[1] == ""                       # 空行原样保留、不编号
    assert lines[2] == "⟦P02⟧ 第一段正文。"
    assert lines[3] == ""
    assert lines[4] == "⟦P03⟧ 第二段正文。"
    print("  ✓ annotate: 标题行参与编号，空行跳过且原样保留")


def test_annotate_whitespace_line_not_numbered():
    """全空白行视同空行：不编号、内容逐字节保留"""
    assert annotate("甲。\n   \n乙。") == "⟦P01⟧ 甲。\n   \n⟦P02⟧ 乙。"
    print("  ✓ annotate: 空白行（含空格）不编号")


def test_annotate_empty_prose():
    """空正文/None 安全（返回空串）"""
    assert annotate("") == ""
    assert annotate(None) == ""
    print("  ✓ annotate: 空正文不崩")


# ---- 测试 2：parse_spans 容忍性与 DoD 5 类畸形 ----

def test_parse_tolerates_fence_and_noise():
    """容忍 markdown 围栏与 JSON 前后的解释性文字（取第一个 [ 到最后一个 ]）"""
    raw = '```json\n[{"op": "replace", "para": 2, "text": "新文本"}]\n```'
    assert parse_spans(raw) == [{"op": "replace", "para": 2, "text": "新文本"}]
    raw2 = '好的，以下是修改建议：\n[{"op": "delete", "para": 3}] 以上请审阅。'
    assert parse_spans(raw2) == [{"op": "delete", "para": 3, "text": ""}]
    print("  ✓ parse: 围栏/前后噪声均容忍")


def test_malformed_1_non_json():
    """① 回复非 JSON（正文/解释文字）→ SpanEditError"""
    for bad in ("第三段节奏拖了，建议把冲突提前到第一段。", "", "   "):
        with pytest.raises(SpanEditError):
            parse_spans(bad)
    # 有 [ 但不是合法 JSON 也算畸形
    with pytest.raises(SpanEditError):
        parse_spans("建议如下：[把第二段删掉，第三段合并进第四段]")
    print("  ✓ 畸形①: 非 JSON/纯解释文字 → SpanEditError")


def test_malformed_2_truncated_json():
    """② JSON 截断（有 [ 无 ]）→ SpanEditError"""
    for bad in ('[{"op": "replace", "para": 2, "text": "写到一半断了',
                '[{"op": "delete", "para": 2}',
                '```json\n[{"op": "replace", "para": 1, "text": "截'):
        with pytest.raises(SpanEditError):
            parse_spans(bad)
    print("  ✓ 畸形②: JSON 截断 → SpanEditError")


def test_malformed_3_para_invalid():
    """③ para 越界/非法：0、负数、缺失、非数 → 解析层 SpanEditError；
    para 超出正文段数 → 应用层 SpanEditError"""
    for para in (0, -1, None, "abc", ""):
        raw = json.dumps([{"op": "delete", "para": para}])
        with pytest.raises(SpanEditError):
            parse_spans(raw)
    # 正文只有 4 段，para=5 在解析层合法、应用层越界
    spans = parse_spans('[{"op": "delete", "para": 5}]')
    with pytest.raises(SpanEditError):
        apply_spans(PROSE, spans)
    print("  ✓ 畸形③: para<1 解析层拒绝 / para>总段数应用层拒绝")


def test_malformed_4_op_invalid():
    """④ op 非法（白名单外/缺失）→ SpanEditError"""
    for op in ("rewrite", "insert_before", "REPLACE", "", None):
        raw = json.dumps([{"op": op, "para": 1, "text": "x"}])
        with pytest.raises(SpanEditError):
            parse_spans(raw)
    # 元素非 dict 同样拒绝
    with pytest.raises(SpanEditError):
        parse_spans('["把第二段删了"]')
    print("  ✓ 畸形④: op 非法/元素非对象 → SpanEditError")


def test_malformed_5_replace_missing_text():
    """⑤ replace/insert_after 缺 text（含空白 text）→ SpanEditError"""
    with pytest.raises(SpanEditError):
        parse_spans('[{"op": "replace", "para": 1}]')
    with pytest.raises(SpanEditError):
        parse_spans('[{"op": "insert_after", "para": 1}]')
    with pytest.raises(SpanEditError):
        parse_spans('[{"op": "replace", "para": 1, "text": "   "}]')
    # delete 不需要 text，合法
    assert parse_spans('[{"op": "delete", "para": 1}]') == [
        {"op": "delete", "para": 1, "text": ""}]
    print("  ✓ 畸形⑤: replace/insert_after 缺 text → SpanEditError（delete 免 text）")


# ---- 测试 3：合法 round-trip 与应用语义 ----

def test_roundtrip_annotate_parse_apply():
    """annotate → 模拟模型输出 → parse → apply 得到预期正文"""
    marked = annotate(PROSE)
    assert marked.count("⟦P") == 4
    assert "⟦P02⟧ " + "第二段：山风裹着雪粒扑面而来。" in marked
    raw = json.dumps([
        {"op": "replace", "para": 2, "text": "第二段：改后的山风。"},
        {"op": "delete", "para": 3},
        {"op": "insert_after", "para": 4, "text": "新增的过渡段。"},
    ])
    merged = apply_spans(PROSE, parse_spans(raw))
    assert merged == ("第一段：少年推开柴门。\n"
                      "第二段：改后的山风。\n"
                      "\n"                            # delete 置空行
                      "第四段：远处山寺的钟声响了。\n"
                      "新增的过渡段。")                 # insert_after 在该行后插新行
    print("  ✓ round-trip: replace/delete/insert_after 语义全部正确")


def test_untouched_paras_byte_preserved():
    """未点名段落逐字节保留（构造保证）"""
    spans = parse_spans('[{"op": "replace", "para": 1, "text": "全新的一段"}]')
    merged = apply_spans(PROSE, spans)
    orig, new = PROSE.split("\n"), merged.split("\n")
    assert new[0] == "全新的一段"
    for i in (1, 2, 3):
        assert new[i] == orig[i]
    print("  ✓ 未点名段落逐字节保留")


def test_zero_edits_identity():
    """零编辑列表 → merged 与原文完全一致"""
    assert apply_spans(PROSE, parse_spans("[]")) == PROSE
    assert apply_spans(PROSE, []) == PROSE
    print("  ✓ 零编辑: merged == 原文")


def test_marks_stripped_from_text():
    """replace/insert_after 文本里的 ⟦⟧ 标记剥掉（防御模型复读标记）"""
    raw = json.dumps([
        {"op": "replace", "para": 2, "text": "⟦P01⟧ 复读标记的新文本"},
        {"op": "insert_after", "para": 4, "text": "⟦P09⟧ 插入段"},
    ])
    merged = apply_spans(PROSE, parse_spans(raw))
    assert "⟦" not in merged and "⟧" not in merged
    assert "复读标记的新文本" in merged
    assert "插入段" in merged
    print("  ✓ 标记剥离: text 内 ⟦⟧ 全部剥除")


def test_same_para_edits_apply_in_order():
    """同段多次编辑按列表顺序生效（最后一条为准）"""
    raw = json.dumps([
        {"op": "replace", "para": 1, "text": "第一稿"},
        {"op": "replace", "para": 1, "text": "第二稿"},
    ])
    merged = apply_spans(PROSE, parse_spans(raw))
    assert merged.startswith("第二稿\n")
    print("  ✓ 同段多次编辑按列表顺序生效")


# ---- 测试 4：span_stats 与输出契约 ----

def test_span_stats():
    """ops 计数 / paras_touched 去重排序 / total_paras 按非空行"""
    raw = json.dumps([
        {"op": "replace", "para": 2, "text": "a"},
        {"op": "replace", "para": 2, "text": "b"},
        {"op": "delete", "para": 3},
        {"op": "insert_after", "para": 4, "text": "c"},
    ])
    st = span_stats(PROSE, parse_spans(raw))
    assert st["ops"] == {"replace": 2, "delete": 1, "insert_after": 1}
    assert st["paras_touched"] == [2, 3, 4]
    assert st["total_paras"] == 4
    print("  ✓ span_stats: ops/paras_touched/total_paras 正确")


def test_output_contract_constant():
    """OUTPUT_CONTRACT 契约文本：提及段落标记与 JSON 数组输出"""
    assert isinstance(OUTPUT_CONTRACT, str) and OUTPUT_CONTRACT.strip()
    assert "⟦P" in OUTPUT_CONTRACT
    assert "JSON" in OUTPUT_CONTRACT
    assert "replace" in OUTPUT_CONTRACT and "delete" in OUTPUT_CONTRACT \
        and "insert_after" in OUTPUT_CONTRACT
    print("  ✓ OUTPUT_CONTRACT: 契约文本完整")


# ---- runner ----

if __name__ == "__main__":
    print("== test_span_edit ==")
    test_annotate_numbering_basic()
    test_annotate_whitespace_line_not_numbered()
    test_annotate_empty_prose()
    test_parse_tolerates_fence_and_noise()
    test_malformed_1_non_json()
    test_malformed_2_truncated_json()
    test_malformed_3_para_invalid()
    test_malformed_4_op_invalid()
    test_malformed_5_replace_missing_text()
    test_roundtrip_annotate_parse_apply()
    test_untouched_paras_byte_preserved()
    test_zero_edits_identity()
    test_marks_stripped_from_text()
    test_same_para_edits_apply_in_order()
    test_span_stats()
    test_output_contract_constant()
    print("\n✓ All 16 tests passed")
