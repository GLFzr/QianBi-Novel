# -*- coding: utf-8 -*-
"""逐章曲线切章与判据（scripts/chapter_curve.py）回归

usage.jsonl 不带章号，曲线全靠"每章恰调用一次"的相位作锚点切分——切错就会把 T1 的
头号产出（hit% 随章数爬升）做成假证据。故锁：锚点选择、段数与章数不符必须报警、
判据在体量不足时不得下裁决、以及双口径计价。
"""
from scripts.chapter_curve import PRICES, _agg, _cut, _pick_anchor, _verdict


def _r(phase, hit=0, miss=0, out=0, lat=1.0):
    return {"phase": phase, "slot": "", "hit": hit, "miss": miss, "in": hit + miss,
            "out": out, "lat": lat, "ts": ""}


ROWS = [_r("enrich", 100, 400)] + [
    x for n in (1, 2, 3) for x in (_r("prose", 100 * n, 400), _r("review", 200, 100),
                                   _r("tracking", 50, 50))]


def test_cut_anchors_at_once_per_chapter_phase():
    setup, segs = _cut(ROWS, "prose")
    assert len(setup) == 1 and setup[0]["phase"] == "enrich"
    assert [len(s) for s in segs] == [3, 3, 3]


def test_pick_anchor_prefers_segment_count_matching_chapters():
    anchor, setup, segs, warn = _pick_anchor(ROWS, 3)
    assert anchor == "prose" and len(segs) == 3 and warn == ""


def test_pick_anchor_warns_instead_of_guessing():
    _a, _s, segs, warn = _pick_anchor(ROWS, 20)
    assert len(segs) == 3 and "≠ 章数 20" in warn


def test_agg_hit_pct_and_two_price_lenses():
    g = _agg([_r("prose", hit=900, miss=100, out=50)], PRICES["ds"])
    assert g["hit_pct"] == 90.0
    ds = g["cost"]
    tr = _agg([_r("prose", hit=900, miss=100, out=50)], PRICES["tr"])["cost"]
    assert ds > 0 and abs(tr - (900 * 0.20 + 100 * 1.00 + 50 * 2.00) / 1e6) < 1e-12


def test_rows_without_cache_detail_count_as_miss():
    """网关没回 prompt_tokens_details 的行不得从分母里溜走：未证明命中＝miss"""
    r = _r("prose", hit=0, miss=0, out=10)
    r["in"] = 1000
    g = _agg([r], PRICES["ds"])
    assert (g["blind"], g["miss"], g["in"], g["in_true"]) == (1, 1000, 1000, 1000)
    assert g["hit_pct"] == 0.0
    mixed = _agg([_r("prose", hit=800, miss=200), r], PRICES["ds"])
    assert mixed["hit_pct"] == 40.0 and mixed["blind"] == 1


def test_verdict_refuses_ruling_below_twenty_chapters():
    chs = [{"num": i, "hit_pct": 90.0, "cum_hit_pct": 90.0, "miss": 1000,
            "cost": 0.1, "lat": 20.0} for i in (1, 2, 3)]
    txt = "\n".join(_verdict(chs, "ds"))
    assert "不作裁决" in txt and "第 10 章" not in txt


def test_verdict_rules_at_twenty_chapters():
    chs = [{"num": i, "hit_pct": 99.0 if i >= 10 else 90.0,
            "cum_hit_pct": 97.5 if i == 20 else 96.0, "miss": 12000,
            "cost": 0.2, "lat": 20.0} for i in range(1, 21)]
    txt = "\n".join(_verdict(chs, "ds"))
    assert "✅" in txt and "第 10 章起单章 hit% 最低 99.0%" in txt


def test_verdict_reports_volume_roll():
    """换卷＝新会话＝历史全 miss：这条断裂才是 99% 的结构性上限，必须写进判据"""
    chs = [{"num": 1, "vol": 1, "in": 900000, "hit_pct": 96.9, "cum_hit_pct": 96.2,
            "miss": 83757, "cost": 0.404, "lat": 38.0},
           {"num": 2, "vol": 2, "in": 267000, "hit_pct": 84.7, "cum_hit_pct": 95.0,
            "miss": 40870, "cost": 0.268, "lat": 35.0}]
    txt = "\n".join(_verdict(chs, "ds"))
    assert "卷界 @第2章（卷 1→2）" in txt and "换卷税" in txt
