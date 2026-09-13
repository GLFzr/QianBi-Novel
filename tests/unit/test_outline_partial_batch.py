# -*- coding: utf-8 -*-
"""细纲批量部分返回治理（v17 前期成本研究·分量 3）单测

P5 实测：模型对 24 章大批次「合法但只回 14 章」不抛异常，原逻辑静默接受 →
缺失章在跑次尾段回退更贵的会话内生成（15.6k miss/章 × 6 章）。
修复：对缺失子集拆半递归补齐。本文件用假 ctx + monkeypatch _stream 钉死
「部分返回必须补齐」与「单章失败仍跳过」两个语义。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_outline_partial_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402

from app.core import stages  # noqa: E402


class FakeCtx:
    def __init__(self, proj):
        self.proj = proj
        self.cfg = {"writing": {"chapter_word_target": 2000}}
        self.logs = []
        self.last_prompt = ""

    def log(self, level, msg):
        self.logs.append((level, msg))

    def checkpoint(self):
        pass

    def consume_gate_idea(self):
        return None


def _outline_text(nums):
    """构造 ===第N章=== 格式的模型输出（parse_outlines 主格式）。"""
    parts = []
    for n in nums:
        parts.append("===第%d章===\n### 第%d章：测试%d\n\n- 拍点：事件%d" % (n, n, n, n))
    return "\n".join(parts)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = str(tmp_path)
    os.makedirs(os.path.join(p, "设定"), exist_ok=True)
    os.makedirs(os.path.join(p, "大纲"), exist_ok=True)
    with open(os.path.join(p, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("都市规则流悬疑。")
    with open(os.path.join(p, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("## 第一卷：测试（第1-10章）")
    # 内存/追踪面：全部走空串路径，避免文件依赖
    monkeypatch.setattr(stages.memory, "read_global_summary", lambda *a, **k: "")
    monkeypatch.setattr(stages.memory, "read_recent_summaries", lambda *a, **k: "")
    monkeypatch.setattr(stages.memory, "unfished_foreshadows", lambda *a, **k: "")
    monkeypatch.setattr(stages, "prev_chapter_pack", lambda *a, **k: ("", ""))
    monkeypatch.setattr(stages, "_worldbook_regex_blocks",
                        lambda *a, **k: ("", "", {"blocks": []}))
    monkeypatch.setattr(stages, "_record_worldbook", lambda *a, **k: None)
    monkeypatch.setattr(stages, "_unit_contract", lambda *a, **k: "")
    monkeypatch.setattr(stages, "_genre_block", lambda *a, **k: "")
    return p


def test_partial_batch_is_completed_by_recursion(proj, monkeypatch):
    """核心语义钉：24 章只回 14（P5 实测形状）→ 缺失 10 章必须被补齐。"""
    todo = list(range(37, 61))                       # 24 章
    first_wave = list(range(37, 51))                 # 模型首轮只回 14 章
    calls = {"n": 0}

    def fake_stream(ctx, slot, prompt, label="", phase="", **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _outline_text(first_wave)         # 部分返回：无异常
        # 递归补齐轮：返回 prompt 里请求不了的固定 10 章（简化：全部缺失章）
        return _outline_text([n for n in todo if n not in first_wave])

    monkeypatch.setattr(stages, "_stream", fake_stream)
    ctx = FakeCtx(proj)
    saved = stages.stage_chapter_outlines(ctx, 37, 60)
    got = sorted(n for n, _t, _c in saved)
    assert got == todo                               # 24 章全部落盘，无静默缺失
    assert calls["n"] >= 2                           # 至少一轮补齐
    assert any("仅返回" in m for _lv, m in ctx.logs)  # 出声告警


def test_full_batch_single_call_unchanged(proj, monkeypatch):
    """全量返回：零额外调用（回归锁——别把好路径搞出多余请求）。"""
    todo = list(range(3, 6))
    calls = {"n": 0}

    def fake_stream(ctx, slot, prompt, label="", phase="", **kw):
        calls["n"] += 1
        return _outline_text(todo)

    monkeypatch.setattr(stages, "_stream", fake_stream)
    saved = stages.stage_chapter_outlines(FakeCtx(proj), 3, 5)
    assert sorted(n for n, _t, _c in saved) == [3, 4, 5]
    assert calls["n"] == 1


def test_single_chapter_failure_still_skips(proj, monkeypatch):
    """单章失败：_generate_outline_batch 保持既有 warn+跳过语义（返回空、不抛）。
    stage_chapter_outlines 对「全批零产出」的 StageError 是另一层既有契约，不在此测。"""
    def fake_stream(ctx, slot, prompt, label="", phase="", **kw):
        return "模型胡言乱语，没有可解析的细纲"

    monkeypatch.setattr(stages, "_stream", fake_stream)
    ctx = FakeCtx(proj)
    saved = stages._generate_outline_batch(ctx, [7], 2000, "设定", "卷纲",
                                           "（无相邻细纲）", "（无）", "（无）")
    assert saved == []
    assert any("细纲生成失败" in m or "失败" in m for _lv, m in ctx.logs)
