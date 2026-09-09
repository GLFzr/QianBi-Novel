# -*- coding: utf-8 -*-
"""W-4 重试与计费黑洞：退避不许被绕过，白付的那几发必须进账

盘上证据（W 轮计划 §2 W-4）：
- 429/5xx 与"200 但空内容"两条 `continue` 直接绕过退避睡眠 ⇒ 同一份几百 k 的深栈
  当场再打一遍（T3 首段就是被 TR 的 503 SERVICE_BUSY 三连打死的）；
- `_record_usage` 只在成功分支调用 ⇒ 重试、空流、用户中止的钱在账上恒等于 0。

本文件锁两件事：① 只要还要重发就先退避（等待期间可被 abort 打断）；
② 拿得到 usage 的失败发一律落一行带 `st` 标记的用量。全部假传输，零真机调用。
"""
import importlib
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import httpx  # noqa: E402

import app.llm.client as client_mod  # noqa: E402

USAGE = {"prompt_tokens": 1000, "completion_tokens": 40,
         "prompt_cache_hit_tokens": 900, "prompt_cache_miss_tokens": 100}


class _Resp:
    """流式假响应：status + SSE 行序列；非 200 时 read().text 给错误体"""

    def __init__(self, status=200, lines=(), body=""):
        self.status_code = status
        self._lines = list(lines)
        self._body = body

    def read(self):
        body = self._body

        class _R:
            text = body
        return _R()

    @property
    def text(self):
        return self._body

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sse(usage=None, contents=()):
    out = []
    if usage:
        out.append("data: " + json.dumps({"choices": [], "usage": usage}))
    for c in contents:
        out.append("data: " + json.dumps({"choices": [{"delta": {"content": c}}]}))
    out.append("data: [DONE]")
    return out


def _json_resp(payload):
    class _R:
        status_code = 200
        text = ""

        def json(self):
            return payload
    return _R()


def _install(monkeypatch, tmp_path, responses):
    st = {"connections": 0, "sleeps": [], "queue": list(responses)}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            st["connections"] += 1
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, json=None, headers=None):
            return st["queue"].pop(0)

        def post(self, url, json=None, headers=None):
            r = st["queue"].pop(0)
            return r

    class _Shim:
        Client = _Client
        TimeoutException = httpx.TimeoutException
        RequestError = httpx.RequestError

    monkeypatch.setattr(client_mod, "httpx", _Shim)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: st["sleeps"].append(s))
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    st["usage"] = um
    return st


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def _cli(**kw):
    kw.setdefault("max_retries", 2)
    kw.setdefault("backoff_base", 0.05)
    return client_mod.LLMClient("https://example.test/v1", "k", "deepseek-v4-flash",
                                slot="writing", **kw)


def test_5xx_retries_only_after_backoff(monkeypatch, tmp_path):
    """5xx 必须先睡 backoff_base×2^n 再重发（过去这条 continue 直接绕过退避）"""
    st = _install(monkeypatch, tmp_path, [
        _Resp(503, body="SERVICE_BUSY"),
        _Resp(200, _sse(USAGE, ["正文"]))])
    c = _cli()
    assert c.chat_turn([{"role": "user", "content": "写"}]) == "正文"
    assert st["connections"] == 2
    assert st["sleeps"] and st["sleeps"][0] == 0.05, "重发前没退避"


def test_empty_stream_is_charged_then_retried_with_backoff(monkeypatch, tmp_path):
    """200 但全程无内容：这一发的 token 真花了 ⇒ 落 st=empty 行，且重发前退避"""
    st = _install(monkeypatch, tmp_path, [
        _Resp(200, _sse(USAGE)),                      # 只有 usage，没吐出内容
        _Resp(200, _sse(USAGE, ["正文"]))])
    c = _cli()
    assert c.chat_turn([{"role": "user", "content": "写"}], phase="prose") == "正文"
    assert st["sleeps"], "空内容重发没退避"
    rows = _rows(tmp_path / "usage.jsonl")
    assert [r.get("st") for r in rows] == ["empty", None]
    assert rows[0]["in"] == 1000 and rows[0]["phase"] == "prose"
    assert rows[1]["hit"] == 900 and rows[1]["miss"] == 100


def test_abort_charges_when_usage_already_arrived(monkeypatch, tmp_path):
    """点停止≠免费：末块 usage 已到就如实记一行 st=abort，且不再重开连接"""
    st = _install(monkeypatch, tmp_path, [
        _Resp(200, _sse(USAGE, ["一", "二", "三"]))])
    c = _cli()
    calls = {"n": 0}

    def abort():
        calls["n"] += 1
        return calls["n"] > 3        # 让 usage 块与部分内容先过手

    out = c.chat_turn([{"role": "user", "content": "写"}], phase="prose", abort=abort)
    assert c.last_aborted is True
    assert st["connections"] == 1, "用户中止后仍在重连"
    rows = _rows(tmp_path / "usage.jsonl")
    assert [r.get("st") for r in rows] == ["abort"] and out


def test_nonstream_empty_is_charged_and_backs_off(monkeypatch, tmp_path):
    """非流式同理：chat() 的空内容分支过去既不计费也不退避"""
    st = _install(monkeypatch, tmp_path, [
        _json_resp({"choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}], "usage": USAGE}),
        _json_resp({"choices": [{"message": {"content": "正文"}}], "usage": USAGE})])
    c = _cli()
    assert c.chat("写", phase="review") == "正文"
    assert st["sleeps"], "空内容重发没退避"
    rows = _rows(tmp_path / "usage.jsonl")
    assert [r.get("st") for r in rows] == ["empty", None]


def test_status_key_only_appears_when_set(monkeypatch, tmp_path):
    """行形状纪律：没 status 就不多出 st 键（旧消费方与历史行逐字节同形）"""
    st = _install(monkeypatch, tmp_path, [])
    um = st["usage"]
    um.record(None, "m", "s", 10, 2, 0.3, phase="prose")
    um.record(None, "m", "s", 10, 2, 0.3, phase="prose", status="retry")
    rows = _rows(tmp_path / "usage.jsonl")
    assert "st" not in rows[0] and rows[1]["st"] == "retry"
