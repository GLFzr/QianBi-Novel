# -*- coding: utf-8 -*-
"""人工审校模式（gates.review_mode=manual）：作者填阻断问题 → AI 修复 → 作者复验"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import project
from app.core import stages


class _FakeClient:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def chat_stream(self, prompt, on_chunk=None, temperature=None, **kw):
        self.calls.append(prompt)
        return self.scripts.pop(0) if self.scripts else "# 第2章 修复稿\n" + "正文修复。" * 300


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _FakeCtx:
    def __init__(self, proj, client, gates_answers):
        self.proj = proj
        self.cfg = {"gates": {"review_enabled": True, "review_mode": "manual",
                              "review_max_rounds": 3, "word_tolerance": 0.1},
                    "writing": {"regex_semantics": "logic", "chapter_session": False},
                    "connections": [{"id": "t-review", "name": "审校", "api_key": "k"}],
                    "slots": {"review": "t-review"}}
        self.router = _FakeRouter(client)
        self.last_prompt = ""
        self.review_raw = None
        self.review_v2 = None
        self.stopped = False
        self.logs = []
        self._answers = list(gates_answers)

    def stream_chunk(self, t):
        pass

    def stream_reasoning(self, t):
        pass

    def stream_stage(self, label):
        pass

    def log(self, level, msg):
        self.logs.append((level, msg))

    def gate(self, key, summary="", chapter=0):
        return self._answers.pop(0) if self._answers else ""


def _make_proj(tmp_path, words=2600):
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, "大纲", "细纲_第002章.md"), "核心事件：反击")
    prose = "他推门进去，把当票拍在柜台上。" * words
    return proj, prose


def test_manual_pass_no_llm(tmp_path):
    """作者留空放行：零审校/修复 LLM 调用，记录 AUTHOR_PASS"""
    proj, prose = _make_proj(tmp_path)
    client = _FakeClient([])
    ctx = _FakeCtx(proj, client, gates_answers=[""])   # 作者直接放行
    blocking, advisory, verdict, out_prose = stages._author_review_entry(ctx, 2, prose)
    assert verdict == "AUTHOR_PASS" and blocking == []
    assert out_prose == prose
    assert client.calls == []                          # 没花一分钱


def test_manual_issues_fixed_then_pass(tmp_path):
    """作者填 2 条问题 → AI 修复一次 → 作者复验放行"""
    proj, prose = _make_proj(tmp_path)
    client = _FakeClient(["# 第2章 修复稿\n" + "他推门进去，把当票拍在柜台上。" * 2600])
    ctx = _FakeCtx(proj, client, gates_answers=["液渍前后不一致\n外卖单来源缺失", ""])
    blocking, advisory, verdict, out_prose = stages._author_review_entry(ctx, 2, prose)
    assert verdict == "AUTHOR_PASS" and blocking == []
    assert out_prose != prose                          # 修复稿已采纳
    assert len(client.calls) == 1                      # 只花一次修复调用
    assert "液渍前后不一致" in client.calls[0]          # 作者问题进修复 prompt
    assert any("人工审校 2 条阻断" in m for _l, m in ctx.logs)


def test_manual_rollback_restores_prose(tmp_path):
    """作者回退 → 保留人工审校开始前的原稿（verdict AUTHOR_PASS、零调用）"""
    proj, prose = _make_proj(tmp_path)
    client = _FakeClient([])
    ctx = _FakeCtx(proj, client, gates_answers=[None])  # gate 返回 None = 回退
    blocking, advisory, verdict, fixed_prose = stages._author_review_entry(ctx, 2, prose)
    assert verdict == "AUTHOR_PASS" and fixed_prose == prose
    assert client.calls == []
