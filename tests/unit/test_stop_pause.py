# -*- coding: utf-8 -*-
"""停止/暂停链路的真实行为测试

起因：用户报「停止和暂停好像有些未生效」。根因是流式生成期间没有中断出口
（client 的 iter_lines 循环不查任何标志），点停止要等本次 HTTP 流跑完
（timeout 默认 300s）才在下一个 checkpoint 生效；细纲批次里 PipelineStopped
还会被宽泛 except 吞成「生成失败」。

这里钉住的都是**真路径**（旧 smoke_func 只断言 Event 标志，checkpoint()
写成空函数也照样绿）：
1. chat_stream 的 abort 谓词真的能中断取流并置 last_aborted
2. 中断发生在收到内容之前时，不再重连烧重试预算
3. 未 abort 时行为与从前一致
4. stages._stream 下传谓词，并在 client 报中断时抛 PipelineStopped
5. Orchestrator.gate 先过 checkpoint（暂停态不弹门，避免两个「继续」打架）
"""
import json

import httpx
import pytest

import app.llm.client as client_mod
from app.core.orchestrator import Orchestrator, PipelineStopped


# ---------------------------------------------------------------- 假 SSE 传输

_CHUNKS = 40


class _FakeResp:
    def __init__(self, n_chunks=_CHUNKS, probe=None):
        self.status_code = 200
        self._n = n_chunks
        self._probe = probe

    def read(self):
        return b""

    def iter_lines(self):
        for i in range(self._n):
            payload = {"choices": [{"delta": {"content": "字%02d" % i}}]}
            yield "data: " + json.dumps(payload, ensure_ascii=False)
        yield "data: [DONE]"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeHttpxClient:
    """替掉 httpx.Client：不联网，但如实执行调用方传入的 abort 谓词。

    记账 connections：重试会重开连接，测试靠它判定「中断后是否还在烧预算」。
    """

    connections = 0

    def __init__(self, n_chunks=_CHUNKS, **kw):
        self.n = n_chunks

    def __enter__(self):
        type(self).connections += 1
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        return _FakeResp(self.n)


class _HttpxShim:
    Client = _FakeHttpxClient
    # client.py 的 except 子句会取这两个属性；漏了会把真实异常换成 AttributeError
    TimeoutException = httpx.TimeoutException
    RequestError = httpx.RequestError


@pytest.fixture(autouse=True)
def _reset_connections(monkeypatch):
    _FakeHttpxClient.connections = 0
    monkeypatch.setattr(client_mod, "httpx", _HttpxShim)
    yield


def _client():
    return client_mod.LLMClient(base_url="https://example.test/v1",
                                api_key="k", model="m")


# ---------------------------------------------------------------- 客户端层

def test_abort_predicate_stops_stream_early():
    c = _client()
    calls = {"n": 0}

    def abort_after_5():
        calls["n"] += 1
        return calls["n"] > 5

    out = c.chat_stream("p", abort=abort_after_5)
    assert c.last_aborted is True
    assert calls["n"] > 1, "abort 谓词根本没被调用 → 中断是假的"
    assert out.count("字") < _CHUNKS, "未提前中断，取流跑满了"
    assert _FakeHttpxClient.connections == 1


def test_abort_before_first_chunk_does_not_retry():
    """立刻停止（还没吐字）不能触发重试——曾经会重连烧光 max_retries"""
    c = _client()
    c.max_retries = 3
    out = c.chat_stream("p", abort=lambda: True)
    assert c.last_aborted is True
    assert out == ""
    assert _FakeHttpxClient.connections == 1, "用户中断后仍在重连重试"


def test_no_abort_keeps_old_behaviour():
    c = _client()
    out = c.chat_stream("p")
    assert c.last_aborted is False
    assert "字00" in out and "字%d" % (_CHUNKS - 1) in out


def test_last_aborted_initialised_false():
    assert _client().last_aborted is False


# ---------------------------------------------------------------- _stream 接线

class _StubClient:
    def __init__(self, aborted=False, text="正文内容"):
        self.last_aborted = aborted
        self.last_prompt = ""
        self.last_sampling = {}
        self.last_latency = 0.0
        self.last_phase = ""
        self.text = text
        self.seen_abort = None

    def chat_stream(self, prompt, system="", temperature=None,
                    on_chunk=None, on_reasoning=None, phase="", **kw):
        self.seen_abort = kw.get("abort")
        return self.text


class _Ctx:
    """最小 ctx：只提供 _stream 用到的接口，stopped 可外部翻转"""

    def __init__(self, client, stopped=False):
        self.proj = ""
        self.router = type("R", (), {"client": staticmethod(lambda slot: client)})()
        self._stopped = stopped

    @property
    def stopped(self):
        return self._stopped

    def stream_stage(self, label): pass
    def stream_chunk(self, c): pass
    def stream_reasoning(self, r): pass
    def log(self, *a): pass


@pytest.fixture
def _no_record(monkeypatch):
    import app.core.stages as stages
    monkeypatch.setattr(stages, "_record_call", lambda *a: None)


def test_stream_raises_when_client_reports_abort(_no_record):
    import app.core.stages as stages
    with pytest.raises(PipelineStopped):
        stages._stream(_Ctx(_StubClient(aborted=True)), "writing",
                       "prompt", label="x", phase="prose")


def test_stream_passes_abort_predicate_bound_to_ctx(_no_record):
    import app.core.stages as stages
    cl = _StubClient()
    ctx = _Ctx(cl, stopped=False)
    text = stages._stream(ctx, "writing", "prompt", label="x", phase="prose")
    assert text == "正文内容"
    assert callable(cl.seen_abort), "_stream 没把 abort 谓词传给 client"
    assert cl.seen_abort() is False
    ctx._stopped = True
    assert cl.seen_abort() is True, "谓词没有跟着 ctx.stopped 变，停止信号传不进来"


# ---------------------------------------------------------------- 决策门竞态

def _orch(tmp_path, monkeypatch, mode="step"):
    from app import project
    proj = project.create_project(str(tmp_path), "门测试")
    orch = Orchestrator(proj, {"writing": {"run_mode": mode}})
    return orch


def test_gate_waits_at_pause_not_opens_gate(tmp_path):
    """暂停态到达决策门：先停在步骤边界，不弹门（否则界面上两个「继续」）"""
    orch = _orch(tmp_path, None)
    order = []
    orch.checkpoint = lambda: order.append("checkpoint")
    orch.sig_gate.connect(lambda *a: order.append("gate"))
    # 决策门会直等人放行；在信号槽里同步放行，测试才不会挂住
    orch.sig_gate.connect(lambda *a: orch.resolve_gate("next", ""))

    orch.gate("G2", "摘要", 1)
    assert order == ["checkpoint", "gate"], order


def test_gate_stops_instead_of_opening(tmp_path):
    """已请求停止：gate() 直接抛，不该再弹门等人"""
    orch = _orch(tmp_path, None)
    orch.sig_gate.connect(lambda *a: pytest.fail("停止后仍弹了决策门"))
    orch.stop()
    with pytest.raises(PipelineStopped):
        orch.gate("G2", "摘要", 1)


def test_gate_returns_immediately_when_disabled(tmp_path):
    orch = _orch(tmp_path, None, mode="auto")
    assert orch.gate("G2", "摘要", 1) == ""


def test_stopped_property_reflects_request(tmp_path):
    orch = _orch(tmp_path, None)
    assert orch.stopped is False
    orch.checkpoint()                       # 未停止：正常返回不抛
    orch.stop()
    assert orch.stopped is True
    with pytest.raises(PipelineStopped):
        orch.checkpoint()
