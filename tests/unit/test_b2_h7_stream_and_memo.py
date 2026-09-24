# -*- coding: utf-8 -*-
"""H-7 局部小修护栏：流式订阅方异常不重试 + 能力备忘录失效入口。

审查报告（可本地小修的两个切面）：
- 流式 except Exception 把订阅方 Python bug 伪装成「流式读取中断」，
  整份深栈重发 max_retries 次（真金）——现在订阅方异常包成 _SubscriberError
  原样上抛，不进重试射程；
- 降级备忘录按 (base_url, model) 进程内记、无失效入口——现在有
  invalidate_capability()，且 bridge.saveConnection 保存后定点失效（AST 钉死）。
"""
import ast
import os

import pytest

from app.llm import client as llm_client
from app.llm.client import LLMClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE = os.path.join(ROOT, "app", "ui", "bridge.py")


# ---- 流式：订阅方 bug 原样上抛、一次都不重发 ----

class _FakeResp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        yield from self._lines

    def read(self):
        class _Body:
            text = ""
        return _Body()


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


class _FakeHttpxClient:
    """单次 SSE 流：吐一个内容增量后 [DONE]"""
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _FakeStreamCtx(_FakeResp([
            'data: {"choices":[{"delta":{"content":"你好"}}]}',
            "data: [DONE]",
        ]))


def test_subscriber_bug_not_masked_or_retried(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "Client", _FakeHttpxClient)
    calls = {"n": 0}

    def bad_chunk(_text):
        calls["n"] += 1
        raise ZeroDivisionError("订阅方自身的 bug")

    c = LLMClient(base_url="https://api.example.com", api_key="k",
                  model="m", max_retries=2, backoff_base=1.0)
    with pytest.raises(llm_client._SubscriberError) as ei:
        c.chat_stream("hi", on_chunk=bad_chunk)
    assert isinstance(ei.value.__cause__, ZeroDivisionError), "原因链必须保留"
    assert calls["n"] == 1, (
        f"订阅方异常被重试 {calls['n']} 次——伪装成「流式读取中断」烧重试预算（H-7 复发）")


# ---- 能力备忘录失效入口 ----

def test_invalidate_capability_clears_memo():
    from app.llm.client import _UNSUPPORTED
    key = ("https://x.example", "m1")   # _memo_key 口径：base_url 已去尾部 /
    _UNSUPPORTED[key] = {"max_tokens"}
    try:
        LLMClient(base_url="https://x.example", api_key="k", model="m1"
                  ).invalidate_capability()
        assert key not in _UNSUPPORTED, "实例入口未清掉同键备忘录"
    finally:
        _UNSUPPORTED.pop(key, None)


def test_save_connection_invalidates_capability_memo():
    """bridge.saveConnection 保存后必须调 invalidate_capability（AST 钉死）——
    否则用户改好连接后本进程仍按旧结论剥参数（改了等于没改）"""
    src = open(BRIDGE, encoding="utf-8").read()
    tree = ast.parse(src)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "saveConnection" in fns, "bridge.saveConnection 消失"
    hits = [c for c in ast.walk(fns["saveConnection"])
            if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "invalidate_capability"]
    assert hits, "saveConnection 不再调 invalidate_capability——H-7 失效入口被摘"
