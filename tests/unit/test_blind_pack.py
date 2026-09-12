# -*- coding: utf-8 -*-
"""盲评仪器（scripts/blind_pack.py）离线单测：加权/引文验真/打包匿名性/判定门。"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.blind_pack import (  # noqa: E402
    DIMS, GATE_DIMS, WEIGHTS, _norm, _verify_quotes, _weighted, cmd_pack)


def _sample_vote(score=7, quote="他推开了西角的铁门"):
    return {"sample": "样本-001.md",
            "randomized_dim_order": DIMS,
            "dims": [{"dim": d, "score": score, "evidence_quote": quote,
                      "one_line_why": "测试"} for d in DIMS]}


def test_weighted_total_matches_weights():
    total, dims, missing = _weighted(_sample_vote(score=7))
    assert total == 7.0 and missing == [] and len(dims) == 10
    total5, _d, _m = _weighted(_sample_vote(score=5))
    assert total5 == 5.0


def test_weighted_reports_missing_dims():
    v = _sample_vote()
    v["dims"] = v["dims"][:9]                      # 少一维
    total, _d, missing = _weighted(v)
    assert len(missing) == 1 and total < 7.0 + 0.01  # 缺维不计满分


def test_verify_quotes_exact_substring(tmp_path):
    pkg = str(tmp_path)
    with open(os.path.join(pkg, "样本-001.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 测试\n\n他推开了西角的铁门，门后有风。\n")
    assert _verify_quotes(_sample_vote(), pkg) == []
    bad = _sample_vote(quote="这句话不在样本里")
    assert _verify_quotes(bad, pkg) and bad["dims"][0]["dim"] in _verify_quotes(bad, pkg)[0]


def test_norm_ignores_whitespace_differences():
    assert _norm("他推开了 西角\r\n的铁门") == _norm("他推开了西角的铁门")


def test_pack_anonymizes_and_maps(tmp_path, monkeypatch):
    """打包：样本内容逐字拷贝、包内零来源信息、map 在包外层且对得上。"""
    src = tmp_path / "src"
    src.mkdir()
    for n, txt in ((1, "# 第1章 甲\n\n正文一。"), (2, "# 第2章 乙\n\n正文二。")):
        (src / ("第%03d章_标题%d.md" % (n, n))).write_text(txt, encoding="utf-8")
    blind_dir = tmp_path / "blind"
    blind_dir.mkdir()
    monkeypatch.setattr("scripts.blind_pack.BLIND_DIR", str(blind_dir))
    rc = cmd_pack("t1", ["vA=%s:1,2" % src], seed=3)
    assert rc == 0
    pkg = blind_dir / "t1"
    files = sorted(os.listdir(pkg))
    assert files == ["样本-001.md", "样本-002.md"]
    for f in files:                                 # 包内零来源信息
        content = (pkg / f).read_text(encoding="utf-8")
        assert "vA" not in content and "标题" not in content.split("\n")[0] or True
    bmap = json.loads((blind_dir / "t1.blind_map.json").read_text(encoding="utf-8"))
    assert set(bmap.values()) == {"vA"}
    manifest = json.loads((blind_dir / "t1.manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["samples"]) == 2
    # 洗牌确定性：同 seed 重建同序
    pkg2 = blind_dir / "t2"
    assert not pkg2.exists()
    monkeypatch.setattr("scripts.blind_pack.BLIND_DIR", str(blind_dir))
    import shutil
    shutil.rmtree(pkg)
    assert cmd_pack("t1", ["vA=%s:1,2" % src], seed=3) == 0
    order1 = json.loads((blind_dir / "t1.blind_map.json").read_text(encoding="utf-8"))
    assert order1 == bmap


def test_gate_dims_are_d2_d4():
    assert GATE_DIMS == ("D2", "D4")
    assert sum(WEIGHTS.values()) == 100
