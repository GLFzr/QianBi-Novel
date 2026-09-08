# -*- coding: utf-8 -*-
"""评委子代理盲评聚合器（quality_score --blind-aggregate）仪器回归

盲评是"能力不下降"的唯一裁决仪器（《测试接手指南_v1.md》§5.5、§8），故锁住四条：
1. evidence_quote 未逐字出现在样本正文 → 该维计 1 分并记评委违规；
2. 加权分一律由程序按 rubric 权重重算，评委自报的 total 不采信；缺维同样计 1 分；
3. 双评委收敛取均值、分歧取中位数（2 票的中位数即均值，不得退化成取高分）；
4. 回归判定按 S 轮在册口径：Δ基线 ≥ -0.5 且最大单维跌幅 ≤ 1.5；单章地板 <7.0 只作观察。
运行：python -m pytest tests/unit/test_blind_aggregate.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

import quality_score as qs

RUBRIC = {"dimensions": [
    {"id": "D1", "name": "甲", "weight": 6, "anchors": {"1": "差", "10": "好"}},
    {"id": "D2", "name": "乙", "weight": 4, "anchors": {"1": "差", "10": "好"}},
]}
QUOTE = "灯焰由金转灰，他数到第四段。"


def _home(tmp_path, samples):
    """样本包 + 映射 + 票文件（全部落在 tmp_path，不碰 tests_output）"""
    sdir = tmp_path / "blind"
    sdir.mkdir()
    blind_map = {}
    for sid, text in samples.items():
        (sdir / sid).write_text(text, encoding="utf-8")
        blind_map[sid] = {"variant": "arm_a" if "甲" in sid else "arm_b", "chapter": 1}
    (sdir / "blind_map.json").write_text(json.dumps(blind_map, ensure_ascii=False),
                                         encoding="utf-8")
    return str(sdir), blind_map


def _vote(sample, scores, self_report=9.9, quote=QUOTE):
    return {"sample": sample, "judge_id": "J-x", "total_weighted_score": self_report,
            "dimensions": [{"dim": d, "score": s, "evidence_quote": quote,
                            "one_line_why": "可数特征"} for d, s in scores.items()]}


def _run(tmp_path, samples, votes, baseline="arm_a"):
    sdir, blind_map = _home(tmp_path, samples)
    vp = tmp_path / "votes.json"
    vp.write_text(json.dumps(votes, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    report = qs._blind_aggregate([str(vp)], sdir, blind_map, RUBRIC, baseline,
                                 out_dir=str(out))
    rows = json.loads((out / list(os.listdir(out))[-1]).with_suffix(".json").read_text(
        encoding="utf-8"))["samples"]
    return report, {r["sample"]: r for r in rows}


def test_fake_quote_drops_dim_to_one_and_flags_violation(tmp_path):
    """引文不实＝该维 1 分 + 违规记录；总分按重算而非评委自报"""
    votes = [_vote("样本-甲001.md", {"D1": 9, "D2": 9}, quote="这句正文里根本没有"),
             _vote("样本-甲001.md", {"D1": 9, "D2": 9}, quote="这句正文里根本没有")]
    _, rows = _run(tmp_path, {"样本-甲001.md": QUOTE * 3}, votes)
    row = rows["样本-甲001.md"]
    assert "引文不实" in row["violations"]
    assert row["total"] == 1.0                      # 两维都被压到 1，自报 9.9 作废


def test_missing_dim_counts_as_one(tmp_path):
    """缺维＝结构不完整＝不可信票，按 1 分计入加权"""
    votes = [_vote("样本-甲001.md", {"D1": 10}), _vote("样本-甲001.md", {"D1": 10})]
    _, rows = _run(tmp_path, {"样本-甲001.md": QUOTE * 3}, votes)
    assert rows["样本-甲001.md"]["total"] == round((6 * 10 + 4 * 1) / 10, 2)


def test_two_divergent_votes_take_median_not_max(tmp_path):
    """分歧时 2 票的中位数即均值（回归：旧实现按索引取到了高分票）"""
    votes = [_vote("样本-甲001.md", {"D1": 10, "D2": 10}),
             _vote("样本-甲001.md", {"D1": 2, "D2": 2})]
    _, rows = _run(tmp_path, {"样本-甲001.md": QUOTE * 3}, votes)
    assert rows["样本-甲001.md"]["divergent"] is True
    assert rows["样本-甲001.md"]["total"] == 6.0


def test_converged_votes_average(tmp_path):
    votes = [_vote("样本-甲001.md", {"D1": 8, "D2": 8}),
             _vote("样本-甲001.md", {"D1": 7, "D2": 7})]
    _, rows = _run(tmp_path, {"样本-甲001.md": QUOTE * 3}, votes)
    assert rows["样本-甲001.md"]["divergent"] is False
    assert rows["样本-甲001.md"]["total"] == 7.5


def _two_arms(tmp_path, b_d1):
    """arm_a 各章恒 D1=8/D2=8；arm_b 各章 D2=8、D1 按 b_d1 逐章给定（加权分 = (6·D1+4·8)/10）"""
    samples, votes = {}, []
    for i, (arm, d1) in enumerate([("arm_a", 8)] * len(b_d1) +
                                  [("arm_b", d) for d in b_d1], 1):
        sid = "样本-%03d.md" % i
        line = "第%d章的锚定句。" % i
        samples[sid] = line * 2
        votes += [_vote(sid, {"D1": d1, "D2": 8}, quote=line) for _ in range(2)]
    sdir = tmp_path / "blind"
    sdir.mkdir()
    blind_map = {}
    for sid, text in samples.items():
        (sdir / sid).write_text(text, encoding="utf-8")
        n = int(sid.split("-")[1].split(".")[0])
        blind_map[sid] = {"variant": "arm_a" if n <= len(b_d1) else "arm_b", "chapter": n}
    vp = tmp_path / "votes.json"
    vp.write_text(json.dumps(votes, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    report = qs._blind_aggregate([str(vp)], str(sdir), blind_map, RUBRIC, "arm_a",
                                 out_dir=str(out))
    md = next(out.glob("quality_report_blind_*.md")).read_text(encoding="utf-8")
    return report, md


def test_gate_rejects_drift_beyond_half_point(tmp_path):
    report, md = _two_arms(tmp_path, [3, 8, 8])       # 单章塌到 5.0 → 变体 7.0
    assert report["arm_a"]["variant_total"] == 8.0
    assert report["arm_b"]["variant_total"] < report["arm_a"]["variant_total"] - 0.5
    assert "❌ 未过" in md


def test_gate_floor_below_seven_is_observation_only(tmp_path):
    """S 轮在册口径：地板 <7.0 出观察标注，但不单独否决（Δ 与单维跌幅才是闸门）"""
    report, md = _two_arms(tmp_path, [8, 8, 6])       # 章分 8.0/8.0/6.8 → 变体 7.6
    assert report["arm_b"]["floor"] == 6.8
    assert report["arm_b"]["variant_total"] == 7.6
    assert "（<7.0 观察）" in md and "✅ 通过" in md


# --- 付费路径护栏 ---------------------------------------------------------------
# main() 无子命令时的默认路径会真实调用评委 API、逐笔写进用户真实台账
# usage.jsonl（phase=quality_judge，《测试接手指南_v1.md》§9.1 红线）。
# 2026-09-07 事故：`quality_score.py --help` 因 --help 不被识别而掉进该路径，
# 起了两个评委进程（及时发现终止，台账未增）。此后未识别参数一律拒执行。

def test_typo_flag_is_reported_as_unknown():
    assert qs._unknown_args(["--targts", "s1_volume"]) == ["--targts"]
    assert qs._unknown_args(["--help"]) == []
    assert qs._unknown_args(["blind_eval/x.md"]) == []      # 位置参数不误报


def test_value_flags_swallow_their_arguments():
    assert qs._unknown_args(["--blind-aggregate", "--votes", "a.json,b.json",
                             "--baseline", "anchor_baseline", "--per", "20",
                             "--qid", "instrument_check"]) == []
    # 值本身长得像旗标也不误吞（--votes 后面那一位是值位）
    assert qs._unknown_args(["--votes", "--baseline"]) == []


def _fail_to_load_key(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("未识别参数不该走到取 Key / 调评委 API 的路径")
    monkeypatch.setattr(qs, "_load_key", _boom)


def test_main_refuses_unknown_flag_without_touching_api(monkeypatch):
    _fail_to_load_key(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["quality_score.py", "--targts", "s1_volume"])
    try:
        qs.main()
    except SystemExit as e:
        assert "未识别的参数：--targts" in str(e.code)
        return
    raise AssertionError("未知参数被放行，会掉进付费路径")


def test_main_help_short_circuits_without_touching_api(monkeypatch):
    _fail_to_load_key(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["quality_score.py", "--help"])
    qs.main()                                             # 打印 docstring 即返回
