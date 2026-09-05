# -*- coding: utf-8 -*-
"""章会话消息栈（ChapterSession）+ 客户端多轮入口（chat_turn）单元测试

覆盖：
1. ChapterSession 消息栈结构 / turn_count / 异常不固化 / snapshot 深拷贝 /
   commit_turn / restart_with_prose 种子语义 / disabled 契约 / kwargs 透传；
2. chat_turn：messages 原样进入 _build_payload 产物，流式回调与 phase 透传，
   空模型守卫与 chat_stream 一致；
3. _record_usage 的 reasoning 口径（completion_tokens_details.reasoning_tokens）；
4. chat_stream 老路径冒烟（深度回归由 tests/unit/test_llm_payload.py 等承担）。

全部使用内存假件，不触碰真实用户数据目录（usage 埋点用 monkeypatch 拦截）。
"""
import json
import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

import app.llm.client as lc
from app.core.chapter_session import ChapterSession


# ---------------- 假件 ----------------

class FakeClient:
    """chat_turn 替身：记录调用参数，按脚本依次返回（或恒抛错）"""

    def __init__(self, replies=None, error=None):
        self.calls = []   # [(messages, kwargs), ...]
        self.replies = list(replies) if replies is not None else ["回复"]
        self.error = error

    def chat_turn(self, messages, *, on_chunk=None, on_reasoning=None,
                  phase="", temperature=None, abort=None):
        self.calls.append((messages, dict(on_chunk=on_chunk, on_reasoning=on_reasoning,
                                          phase=phase, temperature=temperature,
                                          abort=abort)))
        if self.error is not None:
            raise self.error
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


class FlakyClient:
    """第一次调用抛错、之后成功的替身：验证失败不固化、种子保留"""

    def __init__(self):
        self.calls = []

    def chat_turn(self, messages, **kw):
        self.calls.append(messages)
        if len(self.calls) == 1:
            raise RuntimeError("第一次调用失败")
        return "恢复回复"


SYS = {"role": "system", "content": "S"}


# ---------------- 1. ChapterSession 消息栈 ----------------

def test_ask_builds_stack_and_turn_count():
    c = FakeClient(["甲", "乙"])
    s = ChapterSession(c, "S")
    assert s.enabled is True
    assert s.system_text == "S"
    assert s.turn_count() == 0
    out1 = s.ask("问题1")
    assert out1 == "甲"
    assert s.snapshot() == [SYS,
                            {"role": "user", "content": "问题1"},
                            {"role": "assistant", "content": "甲"}]
    assert s.turn_count() == 1
    out2 = s.ask("问题2")
    assert out2 == "乙"
    assert s.snapshot() == [SYS,
                            {"role": "user", "content": "问题1"},
                            {"role": "assistant", "content": "甲"},
                            {"role": "user", "content": "问题2"},
                            {"role": "assistant", "content": "乙"}]
    assert s.turn_count() == 2
    # 请求时只带「栈 + 本轮 user」，assistant 不提前入栈
    assert c.calls[0][0] == [SYS, {"role": "user", "content": "问题1"}]
    assert c.calls[1][0] == [SYS, {"role": "user", "content": "问题1"},
                             {"role": "assistant", "content": "甲"},
                             {"role": "user", "content": "问题2"}]


def test_ask_passes_stream_kwargs_through():
    c = FakeClient()
    s = ChapterSession(c, "S")
    chunks, reasons = [], []
    stop = lambda: False  # noqa: E731
    s.ask("u", on_chunk=chunks.append, on_reasoning=reasons.append,
          phase="review", temperature=0.2, abort=stop)
    kw = c.calls[0][1]
    assert kw["phase"] == "review"
    assert kw["temperature"] == 0.2
    assert kw["on_chunk"] == chunks.append
    assert kw["on_reasoning"] == reasons.append
    assert kw["abort"] == stop
    # 默认值也不缺位（客户端契约：关键字全都收到）
    s.ask("v")
    kw2 = c.calls[1][1]
    assert kw2["phase"] == "" and kw2["temperature"] is None
    assert kw2["on_chunk"] is None and kw2["on_reasoning"] is None and kw2["abort"] is None


def test_ask_failure_leaves_stack_intact_and_reraises():
    boom = RuntimeError("网络炸了")
    c = FakeClient(error=boom)
    s = ChapterSession(c, "S")
    s.commit_turn("u0", "a0")          # 先固化一轮作为前置状态
    before = s.snapshot()
    with pytest.raises(RuntimeError) as ei:
        s.ask("u1")
    assert ei.value is boom            # 异常原样向上传播
    assert s.snapshot() == before      # 栈保持调用前状态
    assert s.turn_count() == 1
    assert len(c.calls) == 1           # 请求确实发起过（失败在客户端侧）


def test_snapshot_is_deep_copy():
    c = FakeClient()
    s = ChapterSession(c, "S")
    s.ask("u1")
    snap = s.snapshot()
    snap.append({"role": "user", "content": "注入"})
    snap[1]["content"] = "篡改"
    assert s.turn_count() == 1
    assert len(s.snapshot()) == 3
    assert s.snapshot()[1]["content"] == "u1"


def test_commit_turn_appends_pair():
    c = FakeClient()
    s = ChapterSession(c, "S")
    s.commit_turn("投票", "胜出稿")
    assert s.snapshot() == [SYS,
                            {"role": "user", "content": "投票"},
                            {"role": "assistant", "content": "胜出稿"}]
    assert s.turn_count() == 1


def test_restart_with_prose_seeds_first_ask_only():
    c = FakeClient(["r0", "r1", "r2"])
    s = ChapterSession(c, "S")
    s.ask("草稿")
    assert s.turn_count() == 1
    s.restart_with_prose("续跑正文")
    assert s.turn_count() == 0
    assert s.snapshot() == [SYS]
    s.ask("审校")
    msgs1 = c.calls[1][0]
    assert msgs1 == [SYS, {"role": "user",
                           "content": "## 本章正文\n续跑正文\n\n审校"}]
    assert s.snapshot() == [SYS, {"role": "user", "content": "## 本章正文\n续跑正文\n\n审校"},
                            {"role": "assistant", "content": "r1"}]
    assert s.turn_count() == 1
    s.ask("追踪")
    msgs2 = c.calls[2][0]
    assert msgs2[-1]["content"] == "追踪"          # 第二次不带种子前缀
    assert msgs2[-2]["role"] == "assistant"        # 且无连续两条 user 的非法结构
    assert s.turn_count() == 2


def test_restart_seed_survives_failed_ask():
    c = FlakyClient()
    s = ChapterSession(c, "S")
    s.restart_with_prose("正文P")
    with pytest.raises(RuntimeError):
        s.ask("审校")
    assert s.snapshot() == [SYS] and s.turn_count() == 0
    out = s.ask("审校")                 # 重试仍带正文前缀
    assert out == "恢复回复"
    assert c.calls[1][-1]["content"] == "## 本章正文\n正文P\n\n审校"


def test_disabled_session_contract():
    s = ChapterSession(FakeClient(), "S", enabled=False)
    assert s.enabled is False
    assert s.system_text == "S"
    assert s.turn_count() == 0
    with pytest.raises(RuntimeError):
        s.ask("u")
    assert s.snapshot() == [SYS]       # 栈未被触碰
    # 属性只读契约
    with pytest.raises(AttributeError):
        s.enabled = True


def test_client_without_chat_turn_disables_session():
    class LegacyClient:
        def chat_stream(self, *a, **k):
            return "旧路径"

    s = ChapterSession(LegacyClient(), "S", enabled=True)
    assert s.enabled is False
    with pytest.raises(RuntimeError):
        s.ask("u")


def test_scope_line_constant_is_stable():
    assert ChapterSession.SCOPE_LINE == (
        "（作用域：仅依据系统设定基准与本会话中的章正文消息执行本步；"
        "此前轮次的评审/结论性发言不得影响本步输出。）")


# ---------------- 2. client 层：chat_turn 与 chat_stream 老路径 ----------------

class _StreamCtx:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        # 真实 httpx：流式响应必须 read() 后才有 .text
        return types.SimpleNamespace(text="")

    def iter_lines(self):
        msg = (self._payload.get("choices") or [{}])[0].get("message", {})
        pieces = msg.get("_pieces") or [msg.get("content", "")]
        for p in pieces:
            if p:
                yield 'data: ' + json.dumps({"choices": [{"delta": {"content": p}}]})
        yield "data: [DONE]"


class _FakeHttp:
    """记录每次请求体；按脚本依次返回响应（列表耗尽后重复最后一个）"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, timeout=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        self.calls.append(json)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return _StreamCtx(self.responses[idx])


@pytest.fixture
def http(monkeypatch):
    def _install(responses):
        fake = _FakeHttp(responses)
        monkeypatch.setattr(lc.httpx, "Client", fake)
        return fake
    return _install


def test_chat_turn_messages_go_into_payload_verbatim(http):
    recorder = http([{"choices": [{"message": {"content": "ok"}}]}])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m",
                     temperature=0.7, max_tokens=4096)
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "正文"},
            {"role": "assistant", "content": "稿"},
            {"role": "user", "content": "审校"}]
    out = c.chat_turn(msgs, phase="review", temperature=0.2)
    assert out == "ok"
    body = recorder.calls[0]
    assert body["messages"] == msgs            # 原样进入请求体
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 4096
    assert "phase" not in body                 # phase 只做选档/诊断，不进请求体
    assert c.last_phase == "review"
    assert c.last_prompt == "审校"             # 诊断字段取最后一条 user 轮
    assert c.last_aborted is False and c.last_error == ""


def test_chat_turn_streams_chunks_and_aborts_like_chat_stream(http):
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    chunks = []
    http([{"choices": [{"message": {"content": "增量"}}]}])
    assert c.chat_turn([{"role": "user", "content": "u"}],
                       on_chunk=chunks.append) == "增量"
    assert chunks == ["增量"]
    # abort 语义与 chat_stream 一致：逐块各查一次、置 last_aborted、
    # 回已收增量、不在本层抛停止异常
    calls = {"n": 0}

    def stop_after_first_piece():
        calls["n"] += 1
        return calls["n"] > 1   # 第一块放行，之后中断

    http([{"choices": [{"message": {"content": "abcd", "_pieces": ["ab", "cd"]}}]}])
    aborted_chunks = []
    out = c.chat_turn([{"role": "user", "content": "u"}],
                      on_chunk=aborted_chunks.append, abort=stop_after_first_piece)
    assert c.last_aborted is True
    assert out == "ab"                     # 已收增量交回调用方处置
    assert aborted_chunks == ["ab"]


def test_chat_turn_requires_model_like_chat_stream():
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "")
    with pytest.raises(lc.LLMError) as ei:
        c.chat_turn([{"role": "user", "content": "x"}])
    assert "模型" in str(ei.value)
    with pytest.raises(lc.LLMError):
        c.chat_stream("x")


def test_chat_stream_old_path_unchanged(http):
    """薄封装后老路径逐字不变：messages 构造、回调、返回值、诊断字段"""
    recorder = http([{"choices": [{"message": {"content": "流式正文"}}]}])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    chunks = []
    out = c.chat_stream("提示", system="系统", on_chunk=chunks.append, phase="prose")
    assert out == "流式正文"
    assert chunks == ["流式正文"]
    body = recorder.calls[0]
    assert body["messages"] == [{"role": "system", "content": "系统"},
                                {"role": "user", "content": "提示"}]
    assert body["stream"] is True
    assert c.last_prompt == "提示"
    assert c.last_phase == "prose"


# ---------------- 3. _record_usage 的 reasoning 口径 ----------------

def _patch_usage_record(monkeypatch, seen):
    import app.usage as um

    def _rec(cfg, model, slot, tin, tout, latency=0.0, **kw):
        seen.update(model=model, slot=slot, tin=tin, tout=tout, kw=kw)
    monkeypatch.setattr(um, "record", _rec)


def test_record_usage_extracts_reasoning_tokens(monkeypatch):
    seen = {}
    _patch_usage_record(monkeypatch, seen)
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", slot="writing")
    c._record_usage({"prompt_tokens": 100, "completion_tokens": 30,
                     "prompt_cache_hit_tokens": 64, "prompt_cache_miss_tokens": 36,
                     "completion_tokens_details": {"reasoning_tokens": 21}},
                    1.5, phase="review")
    assert seen["tin"] == 100 and seen["tout"] == 30
    assert seen["kw"]["hit"] == 64 and seen["kw"]["miss"] == 36
    assert seen["kw"]["phase"] == "review"
    assert seen["kw"]["reasoning"] == 21


def test_record_usage_reasoning_defaults_to_zero(monkeypatch):
    seen = {}
    _patch_usage_record(monkeypatch, seen)
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c._record_usage({"prompt_tokens": 10, "completion_tokens": 5}, 0.5)
    assert seen["kw"]["reasoning"] == 0
    # details 为 null / 空 dict 也不炸、仍落 0
    c._record_usage({"prompt_tokens": 10, "completion_tokens": 5,
                     "completion_tokens_details": None}, 0.5)
    assert seen["kw"]["reasoning"] == 0
    c._record_usage({"prompt_tokens": 10, "completion_tokens": 5,
                     "completion_tokens_details": {}}, 0.5)
    assert seen["kw"]["reasoning"] == 0


def test_record_usage_zero_tokens_still_skips(monkeypatch):
    seen = {}
    _patch_usage_record(monkeypatch, seen)
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c._record_usage({}, 0.5)               # 无用量：不触埋点（与旧口径一致）
    assert seen == {}
    assert c.total_prompt_tokens == 0 and c.total_completion_tokens == 0
