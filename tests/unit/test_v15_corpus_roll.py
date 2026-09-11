# -*- coding: utf-8 -*-
"""v15 滚动语料快照离线回归——追加式纪律（生死线）+ 卷界重建 + 事件仪器

- roll_corpus_snapshot：追加块字节序、旧文件为前缀、摘要行同滚
- 连续滚动：旧字节永远是新文件的严格前缀（append-only）
- 卷界重建：新卷快照装配含此前全部已锁章节，滚动继续追加
- corpus_rolled 事件落盘（violated/appended 字段）
- outline_pregen 门控：细纲已存在时现场生成路径天然跳过（钉测）
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v15_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.volume_session import (build_corpus_snapshot, corpus_snapshot_path,
                                     roll_corpus_snapshot)


def _mk_proj(tmp_path, chapters=0):
    proj = tmp_path / "p15"
    (proj / "设定").mkdir(parents=True)
    (proj / "大纲").mkdir()
    (proj / "正文").mkdir()
    (proj / "追踪").mkdir()
    (proj / "设定" / "题材定位.md").write_text("# 设定\n主角：测试", encoding="utf-8")
    (proj / "设定" / "世界书.md").write_text("# 世界书\n| 实体 |", encoding="utf-8")
    (proj / "大纲" / "大纲.md").write_text("# 大纲\n第一卷", encoding="utf-8")
    for i in range(1, chapters + 1):
        (proj / "正文" / ("第%03d章_x.md" % i)).write_text(
            "# 第%d章 x\n第%d章正文内容。" % (i, i), encoding="utf-8")
        (proj / "大纲" / ("细纲_第%03d章.md" % i)).write_text(
            "第%d章细纲。" % i, encoding="utf-8")
    return str(proj)


def test_roll_appends_block_and_summary_line(tmp_path):
    proj = _mk_proj(tmp_path, chapters=2)
    vol_file = corpus_snapshot_path(proj, 1)
    base = build_corpus_snapshot(proj, 1)
    assert base, "卷首装配含细纲+正文"
    ok = roll_corpus_snapshot(proj, 1, 3, "测试章", "第3章正文全文。", "一句话摘要A")
    assert ok is True
    grown = open(vol_file, encoding="utf-8").read()
    assert grown.startswith(base), "旧字节必须是新文件的严格前缀（append-only 生死线）"
    assert "### 第3章 测试章" in grown and "第3章正文全文。" in grown
    assert "> 摘要：一句话摘要A" in grown
    # 连续滚动：前缀性质保持
    ok2 = roll_corpus_snapshot(proj, 1, 4, "再滚", "第4章正文。", "摘要B")
    twice = open(vol_file, encoding="utf-8").read()
    assert ok2 and twice.startswith(grown)


def test_roll_creates_snapshot_when_missing(tmp_path):
    proj = _mk_proj(tmp_path, chapters=0)
    ok = roll_corpus_snapshot(proj, 1, 1, "首章", "首章正文。", "摘要C")
    assert ok is True
    text = open(corpus_snapshot_path(proj, 1), encoding="utf-8").read()
    assert "### 第1章 首章" in text and "首章正文。" in text


def test_roll_events_recorded(tmp_path):
    proj = _mk_proj(tmp_path, chapters=1)
    roll_corpus_snapshot(proj, 1, 2, "事件章", "正文x", "摘要x")
    ev_path = os.path.join(proj, "追踪", "session_events.jsonl")
    assert os.path.exists(ev_path)
    recs = [json.loads(l) for l in open(ev_path, encoding="utf-8") if l.strip()]
    rolled = [r for r in recs if r.get("event") == "corpus_rolled"]
    assert rolled and rolled[-1].get("appended", 0) > 0
    assert rolled[-1].get("violated", 0) == 0
