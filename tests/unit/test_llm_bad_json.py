# -*- coding: utf-8 -*-
"""0.20.3 实测阻断修复回归：200 + 畸形 JSON body 不得裸抛绕过重试/台账。

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


def test_nonstream_deadline_enforced(monkeypatch):
    """0.20.3 实测阻断修复#3：keep-alive 填充重置空闲超时 → 总时钟死线收口。

    模拟网关行为：post 每 0.05s 吐一个填充字节、永不结束——空闲超时永不触发，
    总死线（timeout=1s）必须掐断并按可重试超时处理；第二发正常返回。
    """
    import threading
    import time as _t

    proj = tempfile.mkdtemp(prefix="qbn_deadline_")
    dialogue_log.configure(proj, enabled=True)
    calls = {"n": 0}

    class _PaddingResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": " recovered"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

    class PaddingGateway(httpx.Client):
        def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                # 永不返回的填充流（守护线程内 join 不到头，进程不退出）
                def _trickle():
                    while True:
                        _t.sleep(0.05)
                th = threading.Thread(target=_trickle, daemon=True)
                th.start()
                _t.sleep(3600)   # 模拟悬挂的 post 调用
            return _PaddingResp()

    monkeypatch.setattr(httpx, "Client", PaddingGateway)
    cli = LLMClient("https://api.example.com", "sk-test", "test-model",
                    max_retries=1, backoff_base=0)
    cli.timeout = 1   # 1s 总死线，测试不等 900s
    t0 = _t.monotonic()
    text = cli.chat("写一句话")
    took = _t.monotonic() - t0
    assert "recovered" in text
    assert took < 10, f"死线未生效：耗时 {took:.1f}s（应 ~1s 掐断后重试）"
    assert calls["n"] == 2, f"死线掐断后应重试，实际 {calls['n']} 发"
    recs = _records(proj)
    assert [r["outcome"] for r in recs] == ["timeout", "ok"], (
        f"死线超时须留 timeout 台账，实际 {[r['outcome'] for r in recs]}")
