# -*- coding: utf-8 -*-
"""雷章召回量具（scripts/mine_replay.py）离线单测：schema/标记纯净度/植入/判定/计划。

全程零 API、零 app 导入（量具模块顶层只依赖雷集与 plant_defects）；
路径校验用 tmp 草稿目录，不依赖 gitignored 的 tests_output 内容。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.mine_replay import (  # noqa: E402
    AUDIT_PROSE_CAP, DEFAULT_MARKS, GATE_DEFECTS, clean_fp_table, gate_regressions,
    load_queue, plan_calls, recall_table, validate_queue)
from scripts.plant_defects import apply_defect  # noqa: E402
from tests.planted_defects import load_defects  # noqa: E402

QUEUE_PATH = os.path.join(ROOT, "tests", "bench_variants", "queue_mine_gate.json")


def _all_defs():
    return {d["id"]: d for d in load_defects()["defects"]}


def _sample_chapter() -> str:
    """任意可植入的样章：有标题行、多段、含中段与末段（位置型四模式全可落）。"""
    paras = ["# 第2章 试金石", "开头一段，陈默推开楼道的门，雨水顺着楼梯往下淌。",
             "中段正文，他数着台阶，一层，两层，声音从楼上传下来。",
             "靠近末尾的一段，他停下来，把手里的纸折了两折。",
             "最后一段，门在身后合上，走廊的灯灭了。"]
    return "\n\n".join(paras) + "\n"


# ---------- 标记串纯净度（量具的量具之一） ----------

def test_gate_defects_are_legacy_four():
    assert GATE_DEFECTS == ["B01", "B02", "C01", "D01"]


def test_all_marks_substring_of_inject_text():
    all_defs = _all_defs()
    for d_id, mark in DEFAULT_MARKS.items():
        assert d_id in all_defs, "标记表里有未知雷 %s" % d_id
        assert mark in all_defs[d_id]["inject"]["text"], \
            "%s 标记串不是 inject.text 子串" % d_id


def test_gate_defects_all_have_marks():
    assert set(GATE_DEFECTS) <= set(DEFAULT_MARKS)


# ---------- 植入助手（apply_defect 内存版） ----------

@pytest.mark.parametrize("d_id", GATE_DEFECTS)
def test_apply_defect_gate_mines_plant_and_mark_visible(d_id):
    content = _sample_chapter()
    mark = DEFAULT_MARKS[d_id]
    assert mark not in content, "样章天然含标记串，用例失效"
    planted, added, replaced = apply_defect(content, _all_defs()[d_id])
    assert mark in planted
    assert added  # 注入串非空
    assert replaced is None or d_id == "A01"   # 门四雷全是位置型注入
    assert planted != content


def test_apply_defect_replace_regex_miss_raises():
    d = {"id": "X", "inject": {"mode": "replace_regex", "anchor": "不存在的锚点.*?",
                               "text": "雷"}}
    with pytest.raises(ValueError):
        apply_defect(_sample_chapter(), d)


def test_apply_defect_four_positional_modes_covered():
    modes = {_all_defs()[d]["inject"]["mode"] for d in GATE_DEFECTS}
    assert modes == {"before_end", "at_end"}


# ---------- 队列 schema 校验 ----------

def test_repo_queue_json_validates_offline():
    """仓库队列文件：schema/雷 id/标记串必须合法；路径存在性跳过（CI 无 tests_output）。"""
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    validated = validate_queue(queue, check_paths=False)
    assert validated["_defects"] == GATE_DEFECTS
    assert validated["_votes"] == 2
    assert set(validated["_channels"]) == {"review", "audit"}
    assert [s["name"] for s in validated["scenarios"]] == \
        ["gate_think_disabled", "control_think_on"]
    # 生产档必须钉 thinking disabled（P1 前置条件：量具先于改动存在）；
    # C7 裁定后走 overrides_by_channel——只关 audit，review 不连坐
    gate_scene = validated["scenarios"][0]
    assert gate_scene["overrides_by_channel"]["audit"].get("thinking") == "disabled"
    assert "review" not in gate_scene["overrides_by_channel"]
    assert not (gate_scene.get("overrides") or {})


def test_validate_queue_rejects_unknown_defect():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["defects"] = ["Z99"]
    with pytest.raises(SystemExit, match="未知雷"):
        validate_queue(queue, check_paths=False)


def test_validate_queue_rejects_bad_channel():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["channels"] = ["prose"]
    with pytest.raises(SystemExit, match="未知通道"):
        validate_queue(queue, check_paths=False)


def test_validate_queue_rejects_mark_not_substring():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["marks"] = {"B01": "根本不在注入文本里的句子"}
    with pytest.raises(SystemExit, match="子串"):
        validate_queue(queue, check_paths=False)


def test_validate_queue_rejects_duplicate_scene_names():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["scenarios"] = [{"name": "s1"}, {"name": "s1"}]
    with pytest.raises(SystemExit, match="重复"):
        validate_queue(queue, check_paths=False)


def test_validate_queue_rejects_missing_source(tmp_path):
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["source_drafts"] = str(tmp_path / "nope")
    with pytest.raises(SystemExit, match="source_drafts"):
        validate_queue(queue, check_paths=True)


def test_load_queue_on_real_file_with_tmp_source(tmp_path):
    """路径校验通路：把章源指到 tmp 造的草稿后整链校验通过。"""
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "第002.md").write_text(_sample_chapter(), encoding="utf-8")
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    queue["source_drafts"] = str(drafts)
    validated = validate_queue(queue, check_paths=True)
    assert validated["_chapter_nums"] == [2]


# ---------- 发车计划（纯离线） ----------

def test_plan_calls_counts():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = validate_queue(json.load(f), check_paths=False)
    plan = plan_calls(queue)
    # 2 场景 ×（4 雷 + 1 干净）× 2 通道 × 2 票 = 40 笔
    assert plan["calls"] == 40
    assert [s["calls"] for s in plan["scenarios"]] == [20, 20]


def test_sample_chapter_within_audit_cap():
    assert len(_sample_chapter()) <= AUDIT_PROSE_CAP


# ---------- 判定逻辑 ----------

def _call(kind, defect, channel, caught, scenario="s1", vote=0):
    return {"scenario": scenario, "kind": kind, "defect": defect, "chapter": 2,
            "channel": channel, "vote": vote, "caught": caught}


def test_recall_table_counts_caught_votes():
    results = {"calls": [
        _call("planted", "B01", "review", ["改日再算"], vote=0),
        _call("planted", "B01", "review", [], vote=1),
        _call("planted", "C01", "audit", ["让父亲在昨夜的高速上活下来"], vote=0),
        _call("planted", "C01", "audit", ["让父亲在昨夜的高速上活下来"], vote=1),
        _call("clean", "", "review", []),
    ]}
    table = recall_table(results)
    assert table["B01/review"][0] == 0.5
    assert table["C01/audit"][0] == 1.0
    assert table["B01/review"][1] == {"caught": 1, "votes": 2}


def test_gate_regressions_detects_drop_only():
    old = {"calls": [
        _call("planted", "B01", "review", ["改日再算"], scenario="old", vote=0),
        _call("planted", "B01", "review", ["改日再算"], scenario="old", vote=1),
        _call("planted", "C01", "audit", ["让父亲在昨夜的高速上活下来"], scenario="old", vote=0),
    ]}
    same = {"calls": [
        _call("planted", "B01", "review", ["改日再算"], vote=0),
        _call("planted", "B01", "review", ["改日再算"], vote=1),
        _call("planted", "C01", "audit", ["让父亲在昨夜的高速上活下来"], vote=0),
    ]}
    assert gate_regressions(same, old) == []
    worse = {"calls": [
        _call("planted", "B01", "review", [], vote=0),
        _call("planted", "B01", "review", ["改日再算"], vote=1),
        _call("planted", "C01", "audit", ["让父亲在昨夜的高速上活下来"], vote=0),
    ]}
    regs = gate_regressions(worse, old)
    assert regs == [{"defect_channel": "B01/review", "old": 1.0, "new": 0.5}]


def test_gate_regressions_flags_new_defect_channel():
    old = {"calls": []}
    new = {"calls": [_call("planted", "D01", "review", [])]}
    regs = gate_regressions(new, old)
    assert regs and regs[0]["defect_channel"] == "D01/review"


def test_clean_fp_table_and_rule():
    no_fp = {"calls": [_call("clean", "", "review", []),
                       _call("clean", "", "audit", [])]}
    assert clean_fp_table(no_fp) == []
    with_fp = {"calls": [_call("clean", "", "review", []),
                         dict(_call("clean", "", "audit", []), fp=True)]}
    fps = clean_fp_table(with_fp)
    assert len(fps) == 1 and fps[0]["channel"] == "audit"


def test_clean_fp_rule_matches_channel_semantics():
    from scripts.mine_replay import _clean_fp
    assert _clean_fp("review", {"n_fail": 1}) is True
    assert _clean_fp("review", {"n_fail": 0, "n_items": 3}) is False
    assert _clean_fp("audit", {"n_violations": 2}) is True
    assert _clean_fp("audit", {"n_violations": 0, "n_pattern": 1}) is False


# ---------- 同跑 A/B 判定（v16 P4 主判定路径） ----------

def test_ab_regressions_compares_scenarios_within_one_run():
    from scripts.mine_replay import ab_regressions
    results = {"calls": [
        _call("planted", "B01", "review", ["改日再算"], scenario="control_think_on", vote=0),
        _call("planted", "B01", "review", ["改日再算"], scenario="control_think_on", vote=1),
        _call("planted", "B01", "review", ["改日再算"], scenario="gate_think_disabled", vote=0),
        _call("planted", "B01", "review", ["改日再算"], scenario="gate_think_disabled", vote=1),
    ]}
    assert ab_regressions(results, "gate_think_disabled", "control_think_on") == []
    worse = {"calls": [dict(c, caught=[]) if c["scenario"] == "gate_think_disabled"
                       and c["vote"] == 1 else c for c in results["calls"]]}
    regs = ab_regressions(worse, "gate_think_disabled", "control_think_on")
    assert regs and regs[0]["defect_channel"] == "B01/review"


def test_ab_verdict_fails_closed_on_empty_tables():
    """假绿防线：门档/对照档零调用（发车失败等）必须判不通过，不许空表对比出「通过」。"""
    from scripts.mine_replay import ab_verdict
    ok, lines = ab_verdict({"calls": []}, "gate_think_disabled", "control_think_on")
    assert ok is False
    assert any("结构失败" in ln for ln in lines)


def test_ab_verdict_passes_with_full_recall_and_no_fp():
    from scripts.mine_replay import ab_verdict
    calls = []
    for scene in ("control_think_on", "gate_think_disabled"):
        for v in (0, 1):
            calls.append(_call("planted", "B01", "review", ["改日再算"], scenario=scene, vote=v))
            calls.append(_call("clean", "", "review", [], scenario=scene, vote=v))
    ok, lines = ab_verdict({"calls": calls}, "gate_think_disabled", "control_think_on")
    assert ok is True and any("通过" in ln for ln in lines)


def test_load_key_reads_real_home_config(tmp_path, monkeypatch):
    """P4a 发车失败定案回归钉：_load_key 读 REAL_HOME 真机配置（凭据库与 home 无关），
    不受 fake home 出厂连接表限制。"""
    import json
    import scripts.cost_bench as cb
    real_home = tmp_path / "realhome"
    (real_home / ".qianbi_novel").mkdir(parents=True)
    cfg = {"connections": [
        {"id": "ds-official-flash", "model": "deepseek-flash",
         "base_url": "https://api.deepseek.com", "api_key": "", "key_ref": "keyring"},
        {"id": "nokey", "model": "m", "base_url": "https://x.invalid"},
    ]}
    (real_home / ".qianbi_novel" / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cb, "REAL_HOME", str(real_home))
    import app.secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "get_secret",
                        lambda cid: "sk-test-123" if cid == "ds-official-flash" else "")
    flash, pro = cb._load_key(prefer_id="ds-official-flash")
    assert flash["key"] == "sk-test-123" and flash["model"] == "deepseek-flash"
    assert pro is None
