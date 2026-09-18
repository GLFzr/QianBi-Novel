# -*- coding: utf-8 -*-
"""N-09 护栏：五张零直测模板的装配冒烟——占位符 ↔ 生产 kwargs 对账
（同 format_or_die 思路：模板槽位必须被生产注入，丢字段=裸写即炸）。"""
import os
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import prompts


def _fields(tmpl: str) -> set:
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f}


def _kw_source(anchor: str) -> str:
    """取生产调用点 anchor 之前最近的 kwargs 构造段源码"""
    src = open(os.path.join(ROOT, "app", "core", "stages.py"), encoding="utf-8").read()
    i = src.find(anchor)
    assert i > 0, "生产调用点未找到：" + anchor
    j = max(src.rfind("kw = dict(", 0, i), src.rfind("tail_kw = dict(", 0, i))
    assert j >= 0, "kwargs 构造段未找到"
    seg = src[j:i]
    assert "dict(" in seg and len(seg) > 20, \
        "定位到的构造段异常（未真正命中 kwargs 构造，槽位对账会假绿）"
    return seg


def test_deslop_pinned_slots_match_production():
    fields = _fields(prompts.DESLOP_PINNED_PROMPT)
    kw_src = _kw_source("prompts.DESLOP_PINNED_PROMPT.format(**kw)")
    missing = [f for f in fields if (f + "=") not in kw_src]
    assert not missing, "DESLOP_PINNED 槽位未被生产 kwargs 覆盖：%s" % missing


def test_enrich_tail_slots_match_production():
    fields = _fields(prompts.ENRICH_TAIL_PROMPT)
    kw_src = _kw_source("prompts.ENRICH_TAIL_PROMPT.format(**tail_kw)")
    missing = [f for f in fields if (f + "=") not in kw_src]
    assert not missing, "ENRICH_TAIL 槽位未被生产 kwargs 覆盖：%s" % missing


def test_review_compact_protocol_inside_compact_template():
    """紧凑票 = 长文 rubric 前缀（单源派生）+ 转义协议段"""
    from app.prompts import review as _rv
    from app.prompts.review import REVIEW_COMPACT_PROTOCOL
    compact = _rv.FINAL_REVIEW_COMPACT
    marker = _rv.REVIEW_PROTOCOL_MARKER
    prefix = prompts.FINAL_REVIEW_PROMPT[:prompts.FINAL_REVIEW_PROMPT.find(marker)]
    assert compact.startswith(prefix[:80]), "紧凑票未继承长文 rubric 前缀（单源破坏）"
    head = _rv.review_compact_protocol().strip().splitlines()[0]
    flattened = compact.replace(chr(92) + "n", chr(10))
    assert head in flattened, "紧凑票协议标题未进 FINAL_REVIEW_COMPACT"


def test_selection_core_setting_block_slots():
    fields = _fields(prompts.SELECTION_CORE_SETTING_BLOCK)
    assert "core_setting" in fields or not fields


def test_tracking_delta_prompt_consistent_with_full():
    """TRACKING_DELTA：旗标可开的半接线路径——核心槽位必须与全量版一致"""
    fields = _fields(prompts.TRACKING_DELTA_PROMPT)
    full = _fields(prompts.TRACKING_UPDATE_PROMPT)
    for f in ("project_header", "chapter_header"):
        assert f in fields, "TRACKING_DELTA 缺 %s 槽" % f
    extra = fields - full
    assert not extra, "TRACKING_DELTA 出现全量版没有的槽位：%s" % extra
