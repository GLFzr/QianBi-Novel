# -*- coding: utf-8 -*-
"""逐章曲线切章与判据（scripts/chapter_curve.py）回归

2026-09-09 起 usage.jsonl 可带真章号 `ch`（stages 章循环入口登记）：有 ch 时曲线直接按章分组、
同章多段合并（崩溃重跑/多段拼接不再把 53 章数成 56 段），猜锚点退为兜底路径。故锁：
真章号分组与合并、锚点选择、段数与章数不符必须报警、判据在体量不足时不得下裁决、双口径计价。
"""
from scripts.chapter_curve import PRICES, _agg, _cut, _cut_by_ch, _pick_anchor, _verdict


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


def _rc(ch, phase="prose", hit=100, miss=10):
    r = _r(phase, hit, miss)
    r["ch"] = ch
    return r


def test_cut_by_ch_groups_and_merges_real_chapters():
    """真章号优先：乱序按章号排单调；同章多段（崩溃重跑/多段拼接）合并成一章"""
    rows = [_rc(39), _rc(38, "prose"), _rc(38, "review", hit=50, miss=5),
            _rc(0, "outline"), _rc(40)]
    setup, segs, chnos = _cut_by_ch(rows)
    assert chnos == [38, 39, 40], "章号必须单调且合并同章"
    assert [len(s) for s in segs] == [2, 1, 1]
    assert [r["phase"] for r in setup] == ["outline"], "ch=0 的行归备料段"


def test_cut_by_ch_keeps_row_order_inside_a_chapter():
    """章内顺序保留（相位归因与延迟统计依赖它）"""
    rows = [_rc(7, "review"), _rc(7, "prose"), _rc(7, "tracking")]
    _setup, segs, chnos = _cut_by_ch(rows)
    assert chnos == [7] and [r["phase"] for r in segs[0]] == ["review", "prose", "tracking"]


def test_verdict_blind_rows_get_their_own_column():
    """W-5：盲区行不参与 hit% 分母，但账面/真实两个钱数必须一起报出来"""
    chs = [{"num": 1, "vol": 1, "in": 2000, "hit": 400, "miss_known": 300,
            "miss": 1300, "blind": 1, "blind_tok": 1000,
            "blind_by_model": {"omen-alpha": 1000},
            "hit_pct": 400 / 2000 * 100, "cum_hit_pct": 400 / 2000 * 100,
            "hit_pct_book": 400 / 700 * 100, "cum_hit_pct_book": 400 / 700 * 100,
            "cost": 0.5, "cost_real": 0.2, "lat": 20.0}]
    txt = "\n".join(_verdict(chs, "ds"))
    assert "三段对账" in txt
    assert "盲区 1,000 tok" in txt
    assert "账面 ¥0.50／真实 ¥0.20" in txt
    assert "虚高 2.5 倍" in txt
    assert "盲区按渠道：omen-alpha 1,000 tok" in txt
    assert "在册口径 57.1%" in txt          # 400/700，盲区不进分母


def test_verdict_flags_volume_roll_that_never_reset():
    """W-1 的读数护栏：曲线标出的卷界若在跑次当刻输入没断崖，必须标注并未换栈"""
    def c(num, vol, in_tok):
        return {"num": num, "vol": vol, "in": in_tok, "hit_pct": 96.0,
                "cum_hit_pct": 96.0, "miss": 1000, "cost": 0.3, "lat": 20.0}
    real = "\n".join(_verdict([c(1, 1, 900000), c(2, 2, 267000)], "ds"))
    assert "未见栈重置" not in real
    stale = "\n".join(_verdict([c(1, 2, 3700000), c(2, 3, 3150000)], "ds"))
    assert "未见栈重置" in stale
