# -*- coding: utf-8 -*-
"""C44 连接级流式开关：连接 dict 带 "stream": False 的模型走 chat() 非流式。

背景：OpenRouter stealth/space-bunny-alpha 不支持流式——长 prompt 流式请求
返回空内容（实测 609s 空流后「模型返回空内容」失败，见 0.20.3 全量实测）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from app.llm.client import LLMClient
from app.core import stages


class _FakeRouter:
    def __init__(self, client):
        self._client = client

    def client(self, slot):
        return self._client


class _FakeCtx:
    """最小 ctx 桩：_stream 只需要 router/stream_chunk/step/_trace 面。"""

    def __init__(self, client):
        self.proj = "proj"
        self.cfg = {}
        self.stopped = False
        self.chunks = []
        self.router = _FakeRouter(client)
        self.gen_trace = []

    def step(self, num, step_const):
        pass

    def log(self, level, msg):
        pass

    def stream_chunk(self, c):
        self.chunks.append(c)

    def stream_reasoning(self, r):
        pass

    def _trace(self):
        return self.gen_trace


class _FakeClient:
    """替身：stream_enabled=False 走 chat；True 走 chat_stream。"""

    def __init__(self, stream_enabled, reply="正文内容"):
        self.stream_enabled = stream_enabled
        self.model = "fake-model"
        self.last_sampling = {}
        self.last_degraded = False
        self.last_aborted = False
        self.last_finish_reason = "stop"
        self._reply = reply
        self.chat_called = 0
        self.stream_called = 0

    def chat(self, prompt, phase=""):
        self.chat_called += 1
        return self._reply

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None,
                    phase="", abort=None):
        self.stream_called += 1
        if on_chunk:
            on_chunk(self._reply)
        return self._reply


def test_from_connection_default_stream_on():
    c = LLMClient.from_connection({"base_url": "https://x", "model": "m"})
    assert c.stream_enabled is True


def test_from_connection_stream_off():
    c = LLMClient.from_connection({"base_url": "https://x", "model": "m",
                                   "stream": False})
    assert c.stream_enabled is False


def test_stream_off_uses_chat_path():
    fc = _FakeClient(stream_enabled=False, reply="一次性全文")
    ctx = _FakeCtx(fc)
    text = stages._stream(ctx, "prose", "提示词")
    assert text == "一次性全文"
    assert fc.chat_called == 1 and fc.stream_called == 0
    assert ctx.chunks == ["一次性全文"]


def test_stream_on_uses_stream_path():
    fc = _FakeClient(stream_enabled=True, reply="流式全文")
    ctx = _FakeCtx(fc)
    text = stages._stream(ctx, "prose", "提示词")
    assert text == "流式全文"
    assert fc.stream_called == 1 and fc.chat_called == 0


def test_stream_off_stop_flag_raises_after_return():
    fc = _FakeClient(stream_enabled=False)
    ctx = _FakeCtx(fc)
    ctx.stopped = True
    with pytest.raises(stages.PipelineStopped):
        stages._stream(ctx, "prose", "提示词")


def test_stream_off_records_call():
    fc = _FakeClient(stream_enabled=False)
    ctx = _FakeCtx(fc)
    stages._stream(ctx, "review", "提示词", phase="review")
    assert ctx.gen_trace and ctx.gen_trace[-1]["phase"] == "review"


# ---- C44 收口：路由下沉到客户端本体（覆盖共写/审校等 chat_stream 直调点）----

def _real_client(stream_enabled):
    c = LLMClient.from_connection({"base_url": "https://x", "model": "m",
                                   "stream": stream_enabled})
    return c


def test_client_chat_stream_routes_to_chat_when_disabled():
    c = _real_client(False)
    calls = {"chat": 0, "stream_kernel": 0}
    c.chat = lambda prompt, system="", temperature=None, phase="": (
        calls.__setitem__("chat", calls["chat"] + 1) or "全文")
    c._stream_messages = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("非流式连接不得进流式内核"))
    chunks = []
    text = c.chat_stream("提示词", on_chunk=chunks.append, phase="prose")
    assert text == "全文" and calls["chat"] == 1
    assert chunks == ["全文"]


def test_client_chat_turn_routes_to_chat_messages_when_disabled():
    c = _real_client(False)
    seen = {}
    c.chat_messages = lambda messages, temperature=None, phase="": (
        seen.update(messages=list(messages), phase=phase) or "会话全文")
    c._stream_messages = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("非流式连接不得进流式内核"))
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "答"},
            {"role": "user", "content": "第二轮"}]
    text = c.chat_turn(msgs, on_chunk=lambda t: seen.update(chunk=t))
    assert text == "会话全文"
    assert seen["messages"] == msgs and seen["phase"] == ""
    assert seen["chunk"] == "会话全文"


def test_client_stream_enabled_still_streams():
    c = _real_client(True)
    c.chat = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("流式连接不得走 chat 兜底"))
    c._stream_messages = lambda *a, **k: "流式全文"
    assert c.chat_stream("提示词") == "流式全文"
    assert c.chat_turn([{"role": "user", "content": "x"}]) == "流式全文"


def test_client_fallback_sets_last_aborted():
    c = _real_client(False)
    c.chat = lambda *a, **k: "全文"
    c.chat_stream("提示词", abort=lambda: True)
    assert c.last_aborted is True
    c2 = _real_client(False)
    c2.chat = lambda *a, **k: "全文"
    c2.chat_stream("提示词")
    assert c2.last_aborted is False


def test_chat_messages_last_prompt_from_user_turn():
    c = _real_client(False)
    c._chat_nonstream = lambda messages, temperature=None, phase="", **k: "ok"
    c.chat_messages([{"role": "user", "content": "第一轮"},
                     {"role": "assistant", "content": "答"},
                     {"role": "user", "content": "第二轮"}])
    assert c.last_prompt == "第二轮"
