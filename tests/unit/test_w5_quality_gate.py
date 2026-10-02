# -*- coding: utf-8 -*-
"""0.24.0 W5 回归：盲评协议升级 + 质量门（machine 层零成本判据）。"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())


def test_blind_length_normalize():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "qs", os.path.join(os.getcwd(), "tests", "quality_suite.py"))
    qs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qs)
    long_text = "他缓缓抬起头，看了看窗外。" * 400        # ~5200 字
    norm = qs._length_normalize(long_text)
    assert len(norm) <= 3600
    assert norm.endswith(("。", "！", "？")), "句边界截断"
    short = "短稿。"
    assert qs._length_normalize(short) == short          # 过短保留
    assert qs._length_normalize("") == ""


def test_w1_flags_in_default_config():
    """质量门：W1 关键开关进默认表（压缩开/48k/记账脱离/改写闸预算）。"""
    from app import config as cfg_mod
    w = cfg_mod.DEFAULT_CONFIG["writing"]
    assert w["compaction"] is True and w["compaction_token_threshold"] == 48_000
    assert w.get("bookkeeping_off_session", True) is True
    assert w.get("rewrite_budget", 6) == 6
    assert w.get("enrich_para", True) is True
    assert w.get("deslop_cards", True) is True
    assert w.get("opening_bestof", 3) == 3
    assert w.get("directive_intercept", True) is True


def test_w4_modules_wired_into_stages():
    """源码钉：W3/W4 注入块在 _mc_draft 装配链上（防解线）。"""
    src = open(os.path.join(os.getcwd(), "app", "core", "stages.py"),
               encoding="utf-8").read()
    for needle in ("_beat_budget_block(outline, chapter_words)",
                   "_carry_block(proj, num)",
                   "style_anchor.assembly_block(proj)",
                   "_opening_bestof_block(",
                   "hook_carry.record_answer(",
                   "style_anchor.backfill_from_chapter(proj, 1)"):
        assert needle in src, f"装配链解线：{needle}"
    # 三挂点统一（草稿三分支同注入位）
    assert src.count("_style_block + _opening_prefix") == 3
