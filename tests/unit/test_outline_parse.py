# -*- coding: utf-8 -*-
"""细纲批解析：===第N章=== 主格式、空格变体与 markdown 降级格式"""
from app.core.stages import parse_outlines


def test_parse_main_format():
    text = "===第3章===\n第三章内容大纲。\n===第4章===\n第四章内容大纲。"
    result = parse_outlines(text)
    assert [(n, c) for n, _, c in result] == [(3, "第三章内容大纲。"), (4, "第四章内容大纲。")]


def test_parse_handles_spaces_in_delimiter():
    text = "=== 第 3 章 ===\n内容甲。\n=== 第 5 章 ===\n内容乙。"
    result = parse_outlines(text)
    assert [n for n, _, _ in result] == [3, 5]


def test_parse_title_from_inner_header():
    text = "===第7章===\n### 第7章：夜访\n正文大纲。"
    result = parse_outlines(text)
    assert result[0][0] == 7
    assert result[0][1] == "夜访"


def test_parse_markdown_fallback_without_delimiters():
    text = "## 第1章：开局被退婚\n退婚现场。\n## 第2章：觉醒\n金手指出现。"
    result = parse_outlines(text)
    assert [n for n, _, _ in result] == [1, 2]
    assert "退婚现场。" in result[0][2]


def test_parse_garbage_returns_empty():
    assert parse_outlines("") == []
    assert parse_outlines("这是一段没有任何分隔符的闲聊。") == []
