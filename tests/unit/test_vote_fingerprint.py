# -*- coding: utf-8 -*-
"""W-6 前置仪器：票指纹落盘与同构率聚合（不装仪器不许降票）

审校是 `review_temperature=0.2` + `thinking:disabled` + TEMP_LOCKED_PHASES ⇒ 三票近乎
确定性，代码注释里的"票间必不同构"只在思考模式下成立；但票原文从不落盘，
"3 票里有多少是真独立信息"就无从测量——而降票省的是最贵的输出钱。
本文件钉住：指纹字段齐全（sha1/等级向量/回声/未产出协议），以及聚合口径正确。
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.stages import _record_vote_fingerprints  # noqa: E402
from scripts.cost_bench import _agg_vote_iso  # noqa: E402

V1 = "===A_GOLDEN_OPEN=== pass\n===B_PAYOFF=== fail\n===TOTAL===\n- fail 项数：1"
V2 = "===A_GOLDEN_OPEN=== marginal\n===B_PAYOFF=== fail\n===TOTAL===\n- fail 项数：1"
ECHO = "# 第7章 旧纸\n\n（整章回声：模型把正文抄了一遍，一个协议标记都没有）"
# parsed 项＝指纹器实际消费的形状（真实解析在 parse_final_review_v2）
P1 = {"items": [{"dim": "A_GOLDEN_OPEN", "level": "pass"},
                {"dim": "B_PAYOFF", "level": "fail"}], "unstructured": False}
P2 = {"items": [{"dim": "A_GOLDEN_OPEN", "level": "marginal"},
                {"dim": "B_PAYOFF", "level": "fail"}], "unstructured": False}
P3 = {"items": [], "unstructured": True}


def _read(proj):
    p = os.path.join(proj, "追踪", "vote_fingerprints.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def test_fingerprints_one_line_per_vote_with_fields(tmp_path):
    proj = str(tmp_path)
    _record_vote_fingerprints(proj, 7, [V1, V2, ECHO], [P1, P2, P3])
    rows = _read(proj)
    assert [r["i"] for r in rows] == [1, 2, 3] and all(r["ch"] == 7 for r in rows)
    assert len({r["sha1"] for r in rows}) == 3, "不同票必须不同 hash"
    assert rows[0]["levels"] == {"A_GOLDEN_OPEN": "pass", "B_PAYOFF": "fail"}
    assert rows[0]["fail"] == 1 and rows[0]["marginal"] == 0
    assert rows[1]["marginal"] == 1
    assert rows[2]["echo"] is True and rows[2]["unstructured"] is True
    assert rows[2]["levels"] == {} and rows[0]["echo"] is False
    assert rows[0]["han"] > 0


def test_iso_rate_counts_pairs(tmp_path):
    proj = str(tmp_path)
    _record_vote_fingerprints(proj, 1, [V1, V1, V1], [P1, P1, P1])     # 三票全同
    _record_vote_fingerprints(proj, 2, [V1, V2, ECHO], [P1, P2, P3])   # 各判各的
    g = _agg_vote_iso(os.path.join(proj, "追踪", "vote_fingerprints.jsonl"))
    assert g["chapters"] == 2 and g["pairs"] == 6          # 每章 C(3,2)=3 对
    assert g["identical_bytes"] == 3                       # 只有第 1 章逐字相同
    assert g["identical_levels"] == 3                      # 等级向量相同的也只有第 1 章
    assert g["iso_pct"] == 50.0
    assert g["echo_votes"] == 1


def test_iso_empty_when_single_vote(tmp_path):
    proj = str(tmp_path)
    _record_vote_fingerprints(proj, 1, [V1], [P1])
    assert _agg_vote_iso(os.path.join(proj, "追踪", "vote_fingerprints.jsonl")) == {}
    assert _agg_vote_iso(os.path.join(proj, "没有这个文件.jsonl")) == {}
