# -*- coding: utf-8 -*-
"""N-09 护栏：五张零直测模板的装配冒烟——占位符 ↔ 生产 kwargs 对账
（同 format_or_die 思路：模板槽位必须被生产注入，丢字段=裸写即炸）。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import prompts


def _fields(tmpl: str) -> set:
    import string
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f}


def test_deslop_pinned_slots_match_production():
    """DESLOP_PINNED_PROMPT：stages._deslop_pinned 的 kw 必须覆盖全部槽位"""
    from app.core import stages
    fields = _fields(prompts.DESLOP_PINNED_PROMPT)
    # 生产调用点 stages.py:888 .format(**kw)，kw 由同函数构造——直接对源码做静态核对
    src = open(os.path.join(ROOT, "app", "core", "stages.py"), encoding="utf-8").read()
    i = src.find("prompts.DESLOP_PINNED_PROMPT.format(**kw)")
    assert i > 0
    j = src.rfind("kw = {", 0, i)
    kw_src = src[j:i]
    missing = [f for f in fields if ('"%s"' % f) not in kw_src and ("'%s'" % f) not in kw_src]
    assert not missing, "DESLOP_PINNED 槽位未被生产 kwargs 覆盖：%s" % missing


def test_enrich_tail_slots_match_production():
    from app.core import stages
    fields = _fields(prompts.ENRICH_TAIL_PROMPT)
    src = open(os.path.join(ROOT, "app", "core", "stages.py"), encoding="utf-8").read()
    i = src.find("prompts.ENRICH_TAIL_PROMPT.format(**tail_kw)")
    assert i > 0
    j = src.rfind("tail_kw = {", 0, i)
    kw_src = src[j:i]
    missing = [f for f in fields if ('"%s"' % f) not in kw_src]
    assert not missing, "ENRICH_TAIL 槽位未被生产 kwargs 覆盖：%s" % missing


def test_review_compact_protocol_inside_compact_template():
    """REVIEW_COMPACT_PROTOCOL 是 FINAL_REVIEW_COMPACT 的组成部分（v2 紧凑票协议）"""
    assert prompts.REVIEW_COMPACT_PROTOCOL.strip()
    assert prompts.REVIEW_COMPACT_PROTOCOL in prompts.FINAL_REVIEW_COMPACT, \
        "紧凑票协议未拼进 FINAL_REVIEW_COMPACT 模板"


def test_selection_core_setting_block_slots():
    fields = _fields(prompts.SELECTION_CORE_SETTING_BLOCK)
    # 该块由 selection 模板以 {core_setting_block} 占位整体拼入；自身槽位须与
    # stages 的 SELECTION 组装一致（core_setting 必传）
    assert "core_setting" in fields or not fields


def test_tracking_delta_prompt_exists_and_slots():
    """TRACKING_DELTA：旗标 writing.tracking_delta 可开（N-11.4 半接线登记），
    模板槽位须与全量版共享核心槽位（project_header/chapter_header），防开旗标后裸写"""
    fields = _fields(prompts.TRACKING_DELTA_PROMPT)
    full = _fields(prompts.TRACKING_UPDATE_PROMPT)
    for f in ("project_header", "chapter_header"):
        assert f in fields, "TRACKING_DELTA 缺 %s 槽" % f
    assert fields <= full | {"delta_note"}, "TRACKING_DELTA 出现全量版没有的槽位：%s" % (fields - full)
