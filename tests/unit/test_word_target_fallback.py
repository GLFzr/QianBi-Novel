# -*- coding: utf-8 -*-
"""N-07 护栏：细纲字数目标读取失败必须显式告警，且回落原因可区分。

旧实现裸 except: pass —— 细纲损坏/不可读时字数闸门按错阈值判（可误锁/误放）。
阈值语义未动：±50% 偏差防线保持原样。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import gates

import pytest


@pytest.fixture()
def proj(tmp_path):
    p = tmp_path / "书"
    (p / "大纲").mkdir(parents=True)
    return str(p)


def _write_outline(proj, num, text):
    with open(os.path.join(proj, "大纲", f"细纲_第{num:03d}章.md"), "w", encoding="utf-8") as f:
        f.write(text)


def test_outline_target_within_tolerance_wins(proj):
    _write_outline(proj, 1, "# 细纲\n字数目标：2400\n")
    src = []
    assert gates.chapter_word_target(proj, 1, 3000, source=src) == 2400
    assert src == ["outline"]


def test_corrupt_outline_warns_and_falls_back(proj, caplog):
    with open(os.path.join(proj, "大纲", "细纲_第002章.md"), "wb") as f:
        f.write(b"\xff\xfe\x00" + "坏字节".encode("utf-8"))  # 非 utf-8 前缀，解码必炸
    src = []
    with caplog.at_level("WARNING", logger="qianbi.gates"):
        val = gates.chapter_word_target(proj, 2, 3000, source=src)
    assert val == 3000
    assert src == ["config_read_fail"]
    assert any("读取失败" in r.message and "回落" in r.message for r in caplog.records)


def test_missing_outline_reads_as_failure_and_warns(proj, caplog):
    src = []
    with caplog.at_level("WARNING", logger="qianbi.gates"):
        val = gates.chapter_word_target(proj, 3, 3000, source=src)
    assert val == 3000
    assert src == ["config_read_fail"]
    assert any("不存在或为空" in r.message and "回落" in r.message for r in caplog.records)


def test_deviation_target_falls_back_with_distinct_source(proj, caplog):
    _write_outline(proj, 4, "字数目标：300\n")  # 与 3000 偏差 >50%
    src = []
    with caplog.at_level("WARNING", logger="qianbi.gates"):
        val = gates.chapter_word_target(proj, 4, 3000, source=src)
    assert val == 3000
    assert src == ["config_deviation"]
    assert any("偏差过大" in r.message for r in caplog.records)


def test_absent_registration_is_plain_fallback(proj):
    _write_outline(proj, 5, "# 细纲（没有登记字数目标）\n")
    src = []
    assert gates.chapter_word_target(proj, 5, 3000, source=src) == 3000
    assert src == ["config_absent"]


def test_precheck_message_names_the_source(proj):
    _write_outline(proj, 6, "字数目标：2400\n")
    cfg = {"gates": {"word_block_on_review": True, "word_tolerance": 0.1},
           "writing": {"chapter_word_target": 3000}}
    items, blocking, verdict = gates.word_count_precheck(proj, 6, "短", cfg)
    assert verdict == "REJECT" and blocking
    assert "细纲登记" in blocking[0]
    # 回落场景：细纲缺失 → 摘要写明回落
    items, blocking, verdict = gates.word_count_precheck(proj, 99, "短", cfg)
    assert verdict == "REJECT"
    assert "回落" in blocking[0]
