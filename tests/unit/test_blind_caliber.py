# -*- coding: utf-8 -*-
"""W-5 计量口径：盲区 token 只有一处定义，三个工具必须报同一个数

背景（成本战役）：omen-alpha 33.7% 的调用没回 `prompt_tokens_details`，这批 token
过去被三个工具各算各的——chapter_curve 按 miss 计（账面虚高 2.4 倍）、cost_ledger
干脆不计输入价（虚低）、cost_bench 的 metrics 也不计。同一份数据三个数，任何
"降了多少"的判据都不成立。本文件钉住：口径同源 + 三工具同数 + 盲区不参与 hit%。
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # noqa: E402

from app.usage import blind_spread, cache_caliber  # noqa: E402
from scripts import cost_bench as cb  # noqa: E402
from scripts.chapter_curve import PRICES, _agg, _rows  # noqa: E402
from scripts.cost_ledger import _cost  # noqa: E402

M = "deepseek-v4-flash"
# 三行样本：完整上报 / 完全盲区（什么都没回）/ 部分盲区（1900 里只报了 200 的明细）
ROWS = [
    {"ts": "2026-09-09 20:00:00", "ymd": "2026-09-09", "model": M, "slot": "writing",
     "phase": "prose", "in": 1000, "out": 100, "hit": 800, "miss": 200,
     "reasoning": 0, "latency": 1.0, "ch": 1},
    {"ts": "2026-09-09 20:00:10", "ymd": "2026-09-09", "model": M, "slot": "writing",
     "phase": "review", "in": 500, "out": 50, "hit": 0, "miss": 0,
     "reasoning": 0, "latency": 2.0, "ch": 1},
    {"ts": "2026-09-09 20:00:20", "ymd": "2026-09-09", "model": M, "slot": "writing",
     "phase": "tracking", "in": 400, "out": 20, "hit": 100, "miss": 100,
     "reasoning": 0, "latency": 3.0, "ch": 1},
]


def _home(tmp_path, rows=None):
    """造一个假 home（cost_bench 读 <home>/.qianbi_novel/usage/usage.jsonl）"""
    d = os.path.join(str(tmp_path), ".qianbi_novel", "usage")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "usage.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in (rows if rows is not None else ROWS):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(tmp_path), p


def test_cache_caliber_splits_known_and_blind():
    assert cache_caliber({"in": 1000, "hit": 800, "miss": 200}) == (800, 200, 0)
    assert cache_caliber({"in": 500, "hit": 0, "miss": 0}) == (0, 0, 500)
    assert cache_caliber({"in": 400, "hit": 100, "miss": 100}) == (100, 100, 200)
    assert cache_caliber({"in": 400}) == (0, 0, 400)          # 历史行：无缓存列
    assert cache_caliber({"in": 0, "hit": 0, "miss": 0}) == (0, 0, 0)


def test_blind_spread_uses_channel_own_rate():
    # 已知行命中率 80% ⇒ 500 盲区摊成 400 命中 + 100 未命中
    assert blind_spread(800, 200, 500) == (400, 100)
    assert blind_spread(0, 0, 500) == (0, 500)      # 全盲：只能按 miss 计
    assert blind_spread(900, 300, 0) == (0, 0)


def test_blind_rows_do_not_enter_hit_pct(tmp_path):
    """盲区既不进 hit% 的分子也不进分母：在册口径 = 900/1200 = 75%"""
    _h, p = _home(tmp_path)
    g = _agg(_rows(p), PRICES["ds"])
    assert (g["hit"], g["miss_known"], g["blind_tok"]) == (900, 300, 700)
    assert g["blind"] == 2                              # 两笔没回明细
    assert g["hit_pct_book"] == pytest.approx(75.0)     # 只看已知行
    assert g["hit_pct"] == pytest.approx(900 / 1900 * 100)   # 账面：盲区留在分母
    assert g["miss"] == 1000                            # 账面 miss = 300 + 700
    assert g["blind_by_model"] == {M: 700}


def test_real_cost_is_lower_than_book_cost(tmp_path):
    _h, p = _home(tmp_path)
    g = _agg(_rows(p), PRICES["ds"])
    ph, pm, po = PRICES["ds"]["hit"], PRICES["ds"]["miss"], PRICES["ds"]["out"]
    assert g["cost"] == pytest.approx((900 * ph + 1000 * pm + 170 * po) / 1e6)
    # 真实：700 盲区按本渠道 75% 命中率摊派 → hit 900+525 / miss 300+175
    assert g["cost_real"] == pytest.approx((1425 * ph + 475 * pm + 170 * po) / 1e6)
    assert g["cost_real"] < g["cost"]


def test_three_tools_report_the_same_two_numbers(tmp_path):
    """同一份 usage：metrics / chapter_curve / cost_ledger 必须给出同账同真实

    三张价表本来就是同一组数（flash hit $0.007 / miss $0.22 / out $0.66 每百万），
    所以差异只可能来自口径——这条测试就是 W-5 的验收判据。
    """
    home, p = _home(tmp_path)
    m = cb._metrics(home, "caliber", [], 0.0)
    g = _agg(_rows(p), PRICES["ds"])
    with open(p, encoding="utf-8") as f:
        c = _cost([json.loads(ln) for ln in f if ln.strip()])
    assert m["blind_tok"] == g["blind_tok"] == c["blind_tok"] == 700
    assert m["cost_cny"] == pytest.approx(round(g["cost"], 3), abs=0.002)
    assert m["cost_cny"] == pytest.approx(c["cny"], abs=0.002)
    assert m["cost_cny_real"] == pytest.approx(round(g["cost_real"], 3), abs=0.002)
    assert m["cost_cny_real"] == pytest.approx(c["cny_real"], abs=0.002)
    assert m["input_tok"] == g["in_true"] == c["in_tok"] == 1900
    assert m["blind_pct"] == c["blind_share"] == 36.8


def test_blind_input_is_not_free_any_more(tmp_path):
    """旧 cost_ledger 对没回明细的行只计输出钱（输入当免费）——现在按 miss 记账面"""
    proj = str(tmp_path / "b")
    os.makedirs(os.path.join(proj, ".qianbi_novel", "usage"), exist_ok=True)
    c = _cost([dict(ROWS[1])])                 # 只留那一笔全盲（in=500 / hit=miss=0）
    assert c["blind_tok"] == 500 and c["hit_pct"] == 0.0
    assert c["cny"] > 0                        # 账面：500 tok 按 miss 价
    assert c["cny"] == c["cny_real"]           # 全盲时无从摊派，两口径重合
