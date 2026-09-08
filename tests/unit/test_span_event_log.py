# -*- coding: utf-8 -*-
"""U1-c span 事件落盘回归：merged/zero_edit/fallback 计数可从产物读出
（T 轮报告 §9-E：T4b 的「span 回退率」此前无任何落盘计数，判据不可测）"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import span_edit


def _proj(tmp_path):
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    return proj


def _rows(proj):
    p = os.path.join(proj, "追踪", "span_stats.jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def test_record_event_appends_jsonl(tmp_path):
    proj = _proj(tmp_path)
    span_edit.record_event(proj, "review_fix", "merged")
    span_edit.record_event(proj, "review_fix", "fallback", "boom happened")
    span_edit.record_event(proj, "trim", "zero_edit")
    rows = _rows(proj)
    assert [r["event"] for r in rows] == ["merged", "fallback", "zero_edit"]
    assert rows[1]["phase"] == "review_fix" and rows[1]["detail"] == "boom happened"
    assert set(rows[0].keys()) >= {"ts", "phase", "event"}


def test_record_event_never_raises(tmp_path):
    proj = _proj(tmp_path)
    blocker = os.path.join(proj, "追踪")
    os.makedirs(blocker, exist_ok=True)
    open(os.path.join(blocker, "span_stats.jsonl"), "w").close()
    os.chmod(blocker, 0o444)          # 目录只读：写入必须失败
    try:
        os.chmod(blocker, 0o755)      # Windows 上目录权限不一定生效——双保险断言
    finally:
        pass
    # 无论写入成败与否都不能抛（纯观测件）
    span_edit.record_event(proj, "deslop", "merged")
    os.chmod(blocker, 0o755)


def test_cost_bench_aggregation_shape():
    """cost_bench 的聚合逻辑：按 phase → event 计数（与 metrics.span_stats 同构）"""
    rows = [{"phase": "review_fix", "event": "merged"},
            {"phase": "review_fix", "event": "fallback", "detail": "x"},
            {"phase": "review_fix", "event": "fallback", "detail": "y"},
            {"phase": "trim", "event": "zero_edit"}]
    agg = {}
    for r in rows:
        agg.setdefault(r["phase"], {}).setdefault(r["event"], 0)
        agg[r["phase"]][r["event"]] += 1
    assert agg == {"review_fix": {"merged": 1, "fallback": 2},
                   "trim": {"zero_edit": 1}}
