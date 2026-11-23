# -*- coding: utf-8 -*-
"""C05 LLM 容错四件套 + QW-A4 空模型黄牌

- `<think>` 流式过滤状态机四态（正常/思考段内/闭合后/半截标签 holdback），
  语义逐字对拍 easy-writing `src/utils/ai-think-filter.ts`（MIT）：大小写不敏感、
  holdback 上限=标签长-1、正常收尾吐回扣住的尾巴、思考段内断流整体丢弃；
- `last_finish_reason` 识别层：流式过去从不读 finish_reason，现在落到 client
  实例上（后续 G2 截断拦截消费）；
- Retry-After：429 带头照它等，无头退回指数退避（与改动前逐字一致）；
- 非流式 max_tokens 地板 2048（思考计入输出上限，太小会被思考吃光）；
- finish_reason 三条人话 + clean_llm_output 剥思考段；
- QW-A4：test_connection 空模型黄牌零网络。
全部假传输，零真机调用。
"""
import json
import time
import types

import pytest

import app.llm.client as lc


# ---------- 假传输设施（对拍 test_llm_payload 的形态） ----------

class _StreamResp:
    def __init__(self, lines, status=200, text="", headers=None):
        self.status_code = status
        self._lines = list(lines)
        self.text = text
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return types.SimpleNamespace(text=self.text)

    def iter_lines(self):
        return iter(self._lines)


class _JsonResp:
    def __init__(self, payload, status=200, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def read(self):
        return types.SimpleNamespace(text=self.text)


def _sse(chunks=(), finish=None, usage=None):
    out = []
    for c in chunks:
        out.append("data: " + json.dumps({"choices": [{"delta": {"content": c}}]}))
    if finish is not None:
        out.append("data: " + json.dumps(
            {"choices": [{"delta": {}, "finish_reason": finish}]}))
    if usage:
        out.append("data: " + json.dumps({"choices": [], "usage": usage}))
    out.append("data: [DONE]")
    return out


def _content(content, finish="stop"):
    return _JsonResp({"choices": [{"message": {"content": content},
                                   "finish_reason": finish}]})


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

    def post(self, url, json=None, headers=None):
        self.calls.append(json)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]

    def get(self, url, headers=None):
        idx = min(len(self.calls), len(self.responses) - 1)
        return self.responses[idx]

    def stream(self, method, url, json=None, headers=None):
        self.calls.append(json)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


@pytest.fixture
def http(monkeypatch):
    def _install(responses):
        fake = _FakeHttp(responses)
        monkeypatch.setattr(lc.httpx, "Client", fake)
        return fake
    return _install


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(lc, "_sleep", lambda s: None)


# ---------- 1. 状态机单测：四态逐字对拍 easy-writing ----------

def test_state_normal_passthrough():
    """正常态：无标签文本逐字透传，无扣留"""
    f = lc._ThinkStreamFilter()
    assert f.push("今天天气不错，") == "今天天气不错，"
    assert f.push("适合写小说。") == "适合写小说。"
    assert f.finish() == ""


def test_state_in_think_discarded_then_after_close_resume():
    """`<think>` 开→思考段内整体丢弃→闭合后恢复正常输出"""
    f = lc._ThinkStreamFilter()
    assert f.push("正文A<think>秘密思考") == "正文A"
    assert f.push("继续想") == ""
    assert f.push("</think>正文B") == "正文B"
    assert f.finish() == ""


def test_case_insensitive_think_tags():
    """`<Think>` / `</THINK>` 大小写不敏感（对拍 easy-writing toLowerCase）"""
    f = lc._ThinkStreamFilter()
    assert f.push("A<Think>x</THINK>B") == "AB"


def test_holdback_partial_open_tag():
    """半截标签 holdback：尾部 `<thi` 可能是标签开头，扣住等下一片"""
    f = lc._ThinkStreamFilter()
    assert f.push("正文<thi") == "正文"
    assert f.push("nk>秘密</think>尾") == "尾"
    assert f.finish() == ""


def test_holdback_partial_close_tag_inside_think():
    """思考段内尾部 `</th` 扣住：下一片补齐成闭标签则丢弃，补不齐则它本是正文"""
    f = lc._ThinkStreamFilter()
    assert f.push("<think>想到</th") == ""
    assert f.push("ink>）其实这段是正文") == "）其实这段是正文"


def test_tag_split_across_three_chunks():
    """标签被切成三片跨 chunk：行为与整段一致（逐字对拍 easy-writing push 序列）"""
    f = lc._ThinkStreamFilter()
    assert f.push("A<th") == "A"
    assert f.push("ink>x</th") == ""
    assert f.push("ink>B") == "B"
    assert f.finish() == ""


def test_unclosed_think_at_stream_end_discarded():
    """流在思考段内结束（未闭合）：未吐出的部分整体丢弃，不许漏半句进正文"""
    f = lc._ThinkStreamFilter()
    assert f.push("正文<think>想到一半") == "正文"
    assert f.push("还在想") == ""
    assert f.finish() == ""


def test_finish_flushes_plain_heldback_tail():
    """正常收尾：扣住的半截标签其实是普通文本，finish() 如实吐回"""
    f = lc._ThinkStreamFilter()
    assert f.push("abc") == "abc"
    assert f.push("def<") == "def"
    assert f.finish() == "<"


def test_push_accepts_none_chunk():
    f = lc._ThinkStreamFilter()
    assert f.push(None) == ""
    assert f.finish() == ""


# ---------- 2. 非流式 strip：strip_think_blocks + clean_llm_output ----------

def test_strip_think_blocks_closed_and_truncated():
    assert lc.strip_think_blocks("<think>想</think>正文") == "正文"
    assert lc.strip_think_blocks("A<think>想1</think>B<think>想2</think>C") == "ABC"
    # 只剩开标签没闭合（被截断）：其后全为思考内容一并丢弃
    assert lc.strip_think_blocks("正文<think>想到一半……") == "正文"
    assert lc.strip_think_blocks("<Think>x</Think>ok") == "ok"
    assert lc.strip_think_blocks("") == ""


def test_clean_llm_output_strips_think_then_fence():
    """先剥思考段再剥围栏（`<think>` 打头会顶掉 fence 检测，顺序不能反）"""
    out = lc.clean_llm_output("<think>想</think>\n```\n正文\n```")
    assert out == "正文"
    out2 = lc.clean_llm_output("<think>想</think>\n```python\nprint(1)\n```")
    assert out2 == "print(1)"
    assert lc.clean_llm_output("普通正文") == "普通正文"


# ---------- 3. 流式集成：过滤 + finish_reason 识别层 ----------

def test_stream_inline_think_never_reaches_chunks_or_result(http):
    rec = http([_StreamResp(_sse(["<think>暗念", "盘算</think>", "第一章"], finish="stop"))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    got = []
    assert c.chat_stream("p", on_chunk=got.append) == "第一章"
    assert got == ["第一章"], got


def test_stream_think_only_is_empty_and_records_length(http):
    """只吐了思考段（未闭合）：等于空流——自愈/重试语义不变，且识别层记录 length"""
    rec = http([_StreamResp(_sse(["<think>全在想"], finish="length"))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_tokens=32768,
                     max_retries=0, backoff_base=0)
    with pytest.raises(lc.LLMError) as e:
        c.chat_stream("p")
    assert c.last_finish_reason == "length"
    assert "finish_reason=length" in str(e.value)
    assert "max_tokens" in str(e.value)          # 人话文案点破「被截断」
    assert len(rec.calls) == 1                   # 已到天花板：不再自愈重发


def test_stream_finish_reason_recorded_on_success(http):
    http([_StreamResp(_sse(["正文"], finish="stop"))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    assert c.chat_stream("p") == "正文"
    assert c.last_finish_reason == "stop"
    assert c.chat_stream("q") == "正文"          # 每次调用重置后重新记录
    assert c.last_finish_reason == "stop"


def test_stream_finish_reason_absent_stays_empty(http):
    http([_StreamResp(_sse(["正文"]))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c.chat_stream("p")
    assert c.last_finish_reason == ""


def test_nonstream_finish_reason_recorded(http):
    http([_content("好"), _content("好2", finish="stop")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_retries=2, backoff_base=0)
    assert c.chat("a") == "好" and c.last_finish_reason == "stop"
    assert c.chat("b") == "好2" and c.last_finish_reason == "stop"


def test_nonstream_empty_length_error_carries_human_hint(http):
    """非流式空内容 + finish_reason=length：错误文案是人话，不是裸字段名"""
    http([_content("", finish="length")])
    c = lc.LLMClient("http://127.0.0.1:9/v1", "sk", "m", max_tokens=32768,
                     max_retries=0, backoff_base=0)
    with pytest.raises(lc.LLMError) as e:
        c.chat("p")
    assert "finish_reason=length" in str(e.value)
    assert "被截断" in str(e.value)
    assert c.last_finish_reason == "length"


def test_finish_reason_hint_table():
    """三条人话文案钉死（length/stop/content_filter）；认不出返回空串不编话"""
    assert "被截断" in lc._finish_reason_hint("length")
    assert "正常" in lc._finish_reason_hint("stop")
    assert "拦截" in lc._finish_reason_hint("content_filter")
    assert lc._finish_reason_hint("tool_calls") == ""
    assert lc._finish_reason_hint("") == ""


# ---------- 4. 非流式输出地板 2048 ----------

def test_nonstream_max_tokens_floor(http):
    rec = http([_content("好")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_tokens=512)
    c.chat("p")
    assert rec.calls[0]["max_tokens"] == 2048, "思考计入输出上限，512 必被思考吃光"


def test_stream_has_no_floor(http):
    """流式不受地板约束：增量天然可截断，请求体逐字保持调用方给的值"""
    rec = http([_StreamResp(_sse(["好"]))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_tokens=512)
    c.chat_stream("p")
    assert rec.calls[0]["max_tokens"] == 512


def test_floor_interacts_with_escalation(http):
    """地板抬到 2048 后空内容自愈从 2048 翻倍，而不是从 512（否则两次都在地板下空转）"""
    rec = http([_content("", finish="length"), _content("正文")])
    c = lc.LLMClient("https://gateway.invalid/v1", "sk", "m", max_tokens=512,
                     max_retries=2, backoff_base=0)
    assert c.chat("p") == "正文"
    assert rec.calls[0]["max_tokens"] == 2048
    assert rec.calls[1]["max_tokens"] == 4096


# ---------- 5. Retry-After ----------

def test_parse_retry_after_forms():
    assert lc._parse_retry_after("7") == 7.0
    assert lc._parse_retry_after(" 2.5 ") == 2.5
    assert lc._parse_retry_after("") is None
    assert lc._parse_retry_after(None) is None
    assert lc._parse_retry_after("soon") is None          # 认不出的值 → 退回指数退避
    assert lc._parse_retry_after("-3") == 0.0             # 已过期 → 立刻重试
    # HTTP-date（过去的时刻）→ 钳成 0
    assert lc._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_429_retry_after_is_honored(http, monkeypatch):
    """429 带头：按 Retry-After 等（7s），而不是指数退避的 2s"""
    sleeps = []
    monkeypatch.setattr(lc, "_sleep", sleeps.append)   # 接缝（勿 patch 标准库 time：V5）
    http([_JsonResp({}, status=429, text="rate limited",
                    headers={"Retry-After": "7"}),
          _content("好")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", backoff_base=2.0, max_retries=2)
    assert c.chat("p") == "好"
    assert sleeps and sleeps[0] == 7.0, sleeps


def test_429_retry_after_http_date_and_cap(http, monkeypatch):
    """HTTP-date 形式折算成秒；恶意大值被钳到上限 120s（不把挂机跑吊死）"""
    from email.utils import formatdate
    sleeps = []
    monkeypatch.setattr(lc, "_sleep", sleeps.append)   # 接缝（勿 patch 标准库 time：V5）
    future = formatdate(timeval=time.time() + 30, usegmt=True)
    http([_JsonResp({}, status=429, headers={"Retry-After": future}),
          _JsonResp({}, status=429, headers={"Retry-After": "999999"}),
          _content("好")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", backoff_base=2.0, max_retries=2)
    assert c.chat("p") == "好"
    assert 20 <= sleeps[0] <= 30, sleeps       # date 折算 ≈30s（允许一点时钟偏差）
    assert sleeps[1] == lc._RETRY_AFTER_CAP


def test_429_without_header_falls_back_to_exponential(http, monkeypatch):
    """无头/非 429：退回指数退避，与改动前逐字一致"""
    sleeps = []
    monkeypatch.setattr(lc, "_sleep", sleeps.append)   # 接缝（勿 patch 标准库 time：V5）
    http([_JsonResp({}, status=429, headers={}),
          _JsonResp({}, status=503, text="busy"),
          _content("好")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", backoff_base=2.0, max_retries=2)
    assert c.chat("p") == "好"
    assert sleeps == [2.0, 4.0], sleeps


def test_stream_429_retry_after_is_honored(http, monkeypatch):
    """流式 429 同一条规则（W-4 统一退避入口 + Retry-After）"""
    sleeps = []
    monkeypatch.setattr(lc, "_sleep", sleeps.append)   # 接缝（勿 patch 标准库 time：V5）
    http([_StreamResp([], status=429, text="rate limited", headers={"Retry-After": "5"}),
          _StreamResp(_sse(["好"], finish="stop"))])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", backoff_base=2.0, max_retries=2)
    assert c.chat_stream("p") == "好"
    assert sleeps and sleeps[0] == 5.0, sleeps


# ---------- 6. QW-A4：test_connection 空模型黄牌（零网络） ----------

def test_connection_without_model_yellow_cards_with_zero_network(monkeypatch):
    """连接配置缺 model：返回 ⚠ 警告级结果，不发起任何真实请求"""
    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("空模型黄牌不得发起任何网络请求")

    monkeypatch.setattr(lc.httpx, "Client", _Boom)
    c = lc.LLMClient("http://127.0.0.1:9/v1", "sk", "   ")   # 空白模型=没选
    out = c.test_connection()
    assert out.startswith("⚠")
    assert "未选择模型" in out
    assert "连接与模型" in out          # 深链指引（与 _slot_readiness 体系同向）


def test_connection_with_model_still_tests(http):
    """选了模型：走原有真实测试路径（这里只验证黄牌分支没有误伤正常路径）"""
    class _ModelsResp:
        status_code = 200
        text = ""
        headers = {}

        def json(self):
            return {"data": [{"id": "m1"}]}

    http([_ModelsResp()])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m1")
    assert c.test_connection() == "连接成功"


# ---------- 7. QW-B2：按名即剥 + 值校验白名单（client 侧） ----------

@pytest.fixture(autouse=True)
def _clean_memo(monkeypatch):
    """能力备忘录是进程内全局：逐例清空，否则「不支持」结论跨用例串味"""
    monkeypatch.setattr(lc, "_UNSUPPORTED", {})


def _err(status, text):
    return _JsonResp({}, status=status, text=text)


def test_value_echo_rejection_is_not_stripped(http):
    """max_tokens 给大了被 4xx 点名且回显取值：这是值级拒收——原样抛错，
    不剥参数、不进备忘录（按名即剥会把配置错误藏起来还整进程停发 max_tokens）"""
    rec = http([_err(400, "max_tokens is too large: 32768, this model supports at most 8192")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_tokens=32768,
                     max_retries=0, backoff_base=0)
    with pytest.raises(lc.LLMError) as e:
        c.chat("p")
    assert "32768" in str(e.value), "真错误要原样到用户手里"
    assert c.last_degraded is False
    assert "max_tokens" not in c._unsupported()
    assert rec.calls[0]["max_tokens"] == 32768      # 请求体没被动过


def test_name_level_rejection_still_strips(http):
    """白名单内、无值回显的点名 → 照旧按名即剥并记备忘录"""
    rec = http([_err(400, "Invalid parameter: 'max_tokens' is not supported by this model"),
                _content("好")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", max_tokens=4096,
                     max_retries=2, backoff_base=0)
    assert c.chat("p") == "好"
    assert c.last_degraded is True
    assert "max_tokens" in c._unsupported()
    assert "max_tokens" not in rec.calls[1]


def test_temperature_value_echo_raises_instead_of_strip(http):
    """temperature=3.7 越界回显在错误里：值级拒收，抛错不改请求体"""
    http([_err(400, "temperature must be between 0 and 2, got 3.7")])
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", temperature=3.7,
                     max_retries=0, backoff_base=0)
    with pytest.raises(lc.LLMError):
        c.chat("p")
    assert c.last_degraded is False and not c._unsupported()


def test_whitelist_out_param_is_never_stripped(http):
    """白名单外参数（user/model）被点名：不剥、直接抛——剥了会悄悄改变请求语义"""
    for text in ("field 'user' is not allowed here", "unknown field: 'model'"):
        rec = http([_err(400, text)])
        c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", user_id="u1",
                         max_retries=0, backoff_base=0)
        with pytest.raises(lc.LLMError):
            c.chat("p")
        assert c.last_degraded is False
        assert "user" in rec.calls[0] and "model" in rec.calls[0]


def test_value_echo_helper_forms():
    """回显判据：整数/逗号千分位/浮点/整数化浮点都算；容器与 None 不算"""
    assert lc._value_echoed_in("got 32768 tokens", 32768)
    assert lc._value_echoed_in("got 32,768 tokens", 32768)
    assert lc._value_echoed_in("temperature 3.7 invalid", 3.7)
    assert lc._value_echoed_in("value 3 is out of range", 3.0)      # 整数化浮点
    assert lc._value_echoed_in("thinking must be an object", {"type": "enabled"}) is False
    assert lc._value_echoed_in("anything", None) is False
