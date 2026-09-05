# -*- coding: utf-8 -*-
"""usage reasoning 口径（app/usage.py）：record 落盘 reasoning 字段 + 聚合计入 + 旧行兼容

不触网、不碰真实用户数据目录：DIR/FILE 重定向到 pytest tmp_path。运行：
    python -m pytest tests/test_usage_reasoning.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import pytest

from app import usage


@pytest.fixture(autouse=True)
def _sandbox_usage(tmp_path, monkeypatch):
    """把用量落点指到临时目录，测试互不影响也不污染 ~/.qianbi_novel"""
    monkeypatch.setattr(usage, "DIR", str(tmp_path))
    monkeypatch.setattr(usage, "FILE", str(tmp_path / "usage.jsonl"))
    usage._cache = None
    yield
    usage._cache = None


def _last_line() -> dict:
    with open(usage.FILE, "r", encoding="utf-8") as f:
        return json.loads(f.read().strip().splitlines()[-1])


def test_record_writes_reasoning_field():
    usage.record({}, "deepseek-v4-pro", "writing", 100, 50, 1.2,
                 hit=30, miss=70, phase="draft", reasoning=123)
    rec = _last_line()
    assert rec["reasoning"] == 123
    # 既有字段原样保留、顺序不受影响
    assert list(rec.keys())[-1] == "reasoning"
    assert rec["in"] == 100 and rec["out"] == 50
    assert rec["hit"] == 30 and rec["miss"] == 70 and rec["phase"] == "draft"


def test_record_default_reasoning_zero():
    usage.record({}, "m", "helper", 10, 5)   # 既有调用不传 reasoning，零破坏
    rec = _last_line()
    assert rec["reasoning"] == 0
    assert "phase" in rec and rec["phase"] == ""


def test_summary_aggregates_reasoning():
    usage.record({}, "m-a", "writing", 100, 10, reasoning=200)
    usage.record({}, "m-a", "writing", 100, 10, reasoning=50)
    usage.record({}, "m-b", "helper", 10, 2, reasoning=25)
    s = usage.summary({})
    assert s["today"]["reasoning"] == 275
    assert s["month"]["reasoning"] == 275
    assert s["all"]["reasoning"] == 275
    assert s["today"]["by_model"]["m-a"]["reasoning"] == 250
    assert s["today"]["by_model"]["m-b"]["reasoning"] == 25
    assert s["today"]["by_slot"]["writing"]["reasoning"] == 250
    assert s["today"]["by_slot"]["helper"]["reasoning"] == 25
    # 既有口径不受影响
    assert s["today"]["calls"] == 3 and s["today"]["in"] == 210


def test_old_line_without_reasoning_key():
    """旧行无 reasoning 键：读取方 .get 容错，不迁移不炸"""
    today = usage._today()
    old = {"ts": today + " 10:00:00", "ymd": today, "model": "old-m", "slot": "review",
           "in": 7, "out": 3, "latency": 0.5, "hit": 1, "miss": 6, "phase": ""}
    with open(usage.FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(old, ensure_ascii=False) + "\n")
    s = usage.summary({})
    assert s["today"]["reasoning"] == 0
    assert s["today"]["calls"] == 1
    # 旧文件基础上再落新记录：两者共存，各算各的
    usage.record({}, "old-m", "review", 5, 1, reasoning=9)
    s2 = usage.summary({})
    assert s2["today"]["reasoning"] == 9
    assert s2["today"]["calls"] == 2
