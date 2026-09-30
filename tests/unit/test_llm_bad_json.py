# -*- coding: utf-8 -*-
"""0.23.0 实测阻断修复回归：200 + 畸形 JSON body 不得裸抛绕过重试/台账。

背景：OpenRouter stealth 长非流式调用两连发 200 + 断裂 body（JSONDecodeError
在「line 201 column 1」），旧行为直接裸抛——绕过重试、对话台账、用量记账。
"""
import httpx
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.getcwd())

from app import dialogue_log
from app.llm.client import LLMClient


class _BadJsonResp:
    status_code = 200
    text = 'data: {"choices":[{"delta":{"content":"世'

    def json(self):
        raise json.JSONDecodeError("Expecting value", self.text, 28)


class _OkResp:
    status_code = 200

    def __init__(self):
        self._p = {"choices": [{"message": {"content": "重试后成功"}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def json(self):
        return self._p


def _records(proj):
    d = dialogue_log.dialogue_dir(proj)
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".jsonl"):
            out += [json.loads(ln) for ln in
                    open(os.path.join(d, fn), encoding="utf-8") if ln.strip()]
    return out


def test_bad_json_retries_and_succeeds(monkeypatch):
    proj = tempfile.mkdtemp(prefix="qbn_badjson_")
    dialogue_log.configure(proj, enabled=True)
    calls = {"n": 0}

    class FlakyClient(httpx.Client):
        def post(self, *a, **kw):
            calls["n"] += 1
            return _BadJsonResp() if calls["n"] == 1 else _OkResp()

    monkeypatch.setattr(httpx, "Client", FlakyClient)
    cli = LLMClient("https://api.example.com", "sk-test", "test-model",
                    max_retries=2, backoff_base=0)
    assert cli.chat("写一句话") == "重试后成功"
    assert calls["n"] == 2
    recs = _records(proj)
    assert [r["outcome"] for r in recs] == ["bad_json", "ok"], (
        f"坏 JSON 发必须留痕 bad_json 并重试，实际 {[r['outcome'] for r in recs]}")


def test_bad_json_exhausted_raises_with_body_head(monkeypatch):
    proj = tempfile.mkdtemp(prefix="qbn_badjson_")
    dialogue_log.configure(proj, enabled=True)

    class AlwaysBadClient(httpx.Client):
        def post(self, *a, **kw):
            return _BadJsonResp()

    monkeypatch.setattr(httpx, "Client", AlwaysBadClient)
    cli = LLMClient("https://api.example.com", "sk-test", "test-model",
                    max_retries=1, backoff_base=0)
    with pytest.raises(Exception) as ei:
        cli.chat("写一句话")
    msg = str(ei.value)
    assert "JSON 解析失败" in msg, f"错误现场须带解析失败说明：{msg[:200]}"
    assert "data:" in msg, f"错误现场须带 body 头片段：{msg[:200]}"
    recs = _records(proj)
    assert len(recs) == 2 and all(r["outcome"] == "bad_json" for r in recs), (
        f"每发坏 JSON 各留一条台账，实际 {len(recs)} 条")
