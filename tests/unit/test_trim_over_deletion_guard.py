# -*- coding: utf-8 -*-
"""0.23 实测二测阻断修复回归：压缩过度删减守卫。

实弹：qwen span 压缩把 2572 字压到 45 字直接"达标"收货。根因：
check_word_bounds 的 high_ok 语义是「未超上限」——压残稿必然 high_ok=True，
旧守卫条件 `not high_ok` 恒假（死守卫）。修后条件键在 low_ok（低于下限带）。
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from app.core import gates, stages

STAGES_SRC = os.path.join(os.getcwd(), "app", "core", "stages.py")


def test_check_word_bounds_short_text_semantics():
    """语义钉子：短文本 high_ok=True（未超上限≠达标）——守卫必须键 low_ok。"""
    low_ok, high_ok, actual = gates.check_word_bounds("短短几个字", 2000, 0.1)
    assert actual == len("短短几个字")
    assert low_ok is False, "低于下限带 → low_ok 必须为 False"
    assert high_ok is True, "未超上限 → high_ok 为 True（这正是旧守卫的条件陷阱）"


def test_trim_over_deletion_guard_uses_low_ok():
    """变异守护：过度删减守卫必须键 low_ok；旧死条件不得回潮。"""
    src = open(STAGES_SRC, encoding="utf-8").read()
    assert "if not low_ok and actual < chapter_words * 0.6" in src, (
        "压缩过度删减守卫必须以 low_ok（低于下限带）为键——"
        "high_ok 语义是「未超上限」，压残稿恒为 True，条件会变成死守卫")
    assert "not high_ok and actual < chapter_words * 0.6" not in src, (
        "旧死条件回潮：not high_ok 在压缩语境下恒假（见 test_check_word_bounds_short_text_semantics）")
    # 压缩结果日志必须区分「达标」与「低于下限带」（旧版把 45 字报成"达标"）
    assert 'f"压缩后 {actual} 字，达标"' in src
    assert "低于下限带" in src


def test_deslop_rewrite_min_length_guard():
    """变异守护：去味改写采纳必须有长度骤减守卫（max(300, 原稿×50%)）。"""
    src = open(STAGES_SRC, encoding="utf-8").read()
    assert "_min_keep = max(300, int(len(pre_round_prose) * 0.5))" in src, (
        "去味改写采纳点缺长度骤减守卫——qwen 实测把 2239 字换成 35 字被直接收货")
    assert "改写稿长度骤减" in src
