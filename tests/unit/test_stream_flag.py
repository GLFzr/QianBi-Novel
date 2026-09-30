# -*- coding: utf-8 -*-
"""C44 连接级流式开关：连接 dict 带 "stream": False 的模型走 chat() 非流式。

背景：OpenRouter stealth/space-bunny-alpha 不支持流式——长 prompt 流式请求
返回空内容（实测 609s 空流后「模型返回空内容」失败，见 0.23.0 全量实测）。
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
    stages._stream(ctx, "review", "提示词")
    assert ctx.gen_trace and ctx.gen_trace[-1]["phase"] == "review"
