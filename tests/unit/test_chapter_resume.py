# -*- coding: utf-8 -*-
"""方案 H：章内步骤级断点续跑

语义钉死：停在审校/去味之后 → 重启时草稿从盘上恢复、已投审校票恢复、
草稿生成不重跑；全流程走完后断点清除。草稿即文件，定稿只是状态迁移。
"""
import json
import os

import pytest

from app import project
from app.core import state as st
from app.core import stages


def _mk_proj(tmp_path):
    proj = tmp_path / "断点书"
    for d in ("设定", "大纲", "正文", "追踪"):
        (proj / d).mkdir(parents=True)
    (proj / "设定" / "题材定位.md").write_text("# 题材定位\n测试", encoding="utf-8")
    (proj / "大纲" / "细纲_第001章.md").write_text("核心事件：测试断点续跑", encoding="utf-8")
    return str(proj)


class _FakeClient:
    """按 phase 分路计数：prose/desloal/enrich 是草稿系调用，
    canon_audit 是设定清算调用——混在一起就分不清「草稿有没有重写」"""

    def __init__(self, draft_text: str):
        self.draft_text = draft_text
        self.calls = {}

    def chat_stream(self, prompt, on_chunk=None, phase="", **kw):
        self.calls[phase] = self.calls.get(phase, 0) + 1
        if phase == "prose" and on_chunk:
            on_chunk(self.draft_text)
        return self.draft_text

    def chat(self, prompt, **kw):
        self.calls["chat"] = self.calls.get("chat", 0) + 1
        return ""

    @property
    def stream_calls(self):
        return sum(self.calls.values())

    @property
    def prose_calls(self):
        return self.calls.get("prose", 0)

    @property
    def chat_calls(self):
        return self.calls.get("chat", 0)


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _FakeCtx:
    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.logs = []
        self.last_prompt = ""
        self.review_raw = ""

    def gate(self, key, summary="", chapter=0):
        return ""

    def checkpoint(self):
        pass

    def step(self, num, key):
        pass

    def log(self, level, msg):
        self.logs.append(str(msg))

    def stream_chunk(self, text):
        pass

    def stream_stage(self, label):
        pass

    def consume_gate_idea(self):
        return ""


def _run(proj, draft_text, client=None):
    client = client or _FakeClient(draft_text)
    cfg = {"gates": {"review_enabled": False, "deslop_max_rounds": 1,
                     "word_enrich_rounds": 1},
           "writing": {"chapter_word_target": 1000},   # 目标压低，免technology扩写噪音
           "llm": {"max_retries": 0}}
    ctx = _FakeCtx(proj, cfg, client)
    stages.chapter_microcycle(ctx, 1, guidance="")
    return client, ctx


def test_fresh_run_persists_draft_and_clears_step(tmp_path):
    proj = _mk_proj(tmp_path)
    client, _ctx = _run(proj, "## 第1章 起点\n\n这是草稿正文，写得还行。" * 3)
    assert os.path.exists(project.chapter_draft_path(proj, 1))
    assert len(project.list_chapters(proj)) == 1, "定稿落库应有正式章文件"
    assert st.get_chapter_step(proj) == {}, "全流程走完断点应清除"
    assert client.prose_calls >= 1


def test_resume_from_deslop_keeps_draft_and_skips_rewrite(tmp_path):
    proj = _mk_proj(tmp_path)
    draft_text = "## 第1章 起点\n\n这是断点前已写好的草稿。" * 5
    # 手工构造「停在过去味完成」的断点现场
    draft_rel = os.path.relpath(project.chapter_draft_path(proj, 1), proj)
    project.write_file(project.chapter_draft_path(proj, 1), draft_text)
    import hashlib
    fp = hashlib.sha1(project.read_file(project.get_outline_path(proj, 1)).encode("utf-8")).hexdigest()[:12]
    st.save_chapter_step(proj, 1, step_done="deslop", draft_path=draft_rel,
                         votes=[{"verdict": "PASS_WITH_NOTES", "items": [], "summary": {}}],
                         outline_fp=fp)

    client, ctx = _run(proj, draft_text, client=_FakeClient(draft_text))

    assert client.prose_calls == 0, "断点续跑不许重写草稿"
    assert any("断点续跑" in lg for lg in ctx.logs)
    chapters = project.list_chapters(proj)
    assert len(chapters) == 1, "应直接定稿落库"
    saved = project.read_file(chapters[0][2])
    assert "断点前已写好的草稿" in saved, "落库正文必须来自盘上断点草稿"
    assert st.get_chapter_step(proj) == {}, "收尾后断点清除"


def test_resume_stopped_mid_review_keeps_votes(tmp_path):
    """停在审校中途（1/3 票）：重启只补票，草稿不重写"""
    proj = _mk_proj(tmp_path)
    draft_text = "## 第1章 起点\n\n" + "草稿内容这是一段完整的断点测试正文。" * 55
    draft_rel = os.path.relpath(project.chapter_draft_path(proj, 1), proj)
    project.write_file(project.chapter_draft_path(proj, 1), draft_text)
    saved_vote = {"verdict": "PASS", "items": [], "summary": {"pass": 3}}
    import hashlib
    fp = hashlib.sha1(project.read_file(project.get_outline_path(proj, 1)).encode("utf-8")).hexdigest()[:12]
    st.save_chapter_step(proj, 1, step_done="deslop", draft_path=draft_rel,
                         votes=[saved_vote], outline_fp=fp)

    client = _FakeClient(draft_text)
    fake_conn = {"id": "rv", "name": "rv", "base_url": "https://example.test",
                 "api_key": "sk-test", "model": "test-model"}
    cfg = {"connections": [fake_conn],
           "slots": {"writing": "rv", "helper": "rv", "review": "rv"},
           "gates": {"review_enabled": True, "review_votes": 3, "review_pass_fast": False,
                     "review_votes_recheck": 1, "deslop_max_rounds": 1,
                     "word_enrich_rounds": 1, "review_temperature": 0.2},
           "writing": {"chapter_word_target": 1000},
           "llm": {"max_retries": 0}}
    ctx = _FakeCtx(proj, cfg, client)
    stages.chapter_microcycle(ctx, 1)

    assert client.calls.get("review", 0) == 2, "只补投 2 张票（1 张已持久化保留）"
    assert len(project.list_chapters(proj)) == 1


def test_broken_draft_fallback_rewrites(tmp_path):
    """断点草稿文件丢失 → 回退全章重写，不因空草稿卡死"""
    proj = _mk_proj(tmp_path)
    st.save_chapter_step(proj, 1, step_done="deslop", draft_path="正文/.drafts/第001.md",
                         votes=[])
    client, _ctx = _run(proj, "## 第1章 起点\n\n重新写的草稿。" * 5)
    assert client.prose_calls >= 1, "草稿丢失时应重写"
    assert len(project.list_chapters(proj)) == 1
