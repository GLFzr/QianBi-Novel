# -*- coding: utf-8 -*-
"""H-8 护栏：测试连接的错误必须可读、可兜底，不许裸 httpx 异常穿成崩溃。

审查报告：test_connection 无 try，空 base_url 抛 httpx.UnsupportedProtocol 直穿；
_NetWorker.run 只 except LLMError ⇒ 新用户点「测试连接」即崩；list_models 漏
resp.json() 防护（代理门户劫持返 200+HTML → JSONDecodeError）。
修复：test_connection 内部翻译空地址/协议不支持/超时/DNS 失败四类；
_NetWorker.run 兜 except Exception 转 LLMError 形态回执（log 不吞栈）。
"""
import httpx
import pytest

from app.llm import client as llm_client
from app.llm.client import LLMClient, LLMError


# ---- 四类连接错误就地翻译 ----

def test_empty_base_url_friendly_error():
    c = LLMClient(base_url="", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.test_connection()
    msg = str(ei.value)
    assert "接口地址为空" in msg
    assert "UnsupportedProtocol" not in msg   # 异常类名不许漏进人话


def test_bad_scheme_translated():
    c = LLMClient(base_url="ftp://example.com", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.test_connection()
    msg = str(ei.value)
    assert "协议" in msg and "http" in msg
    assert "UnsupportedProtocol" not in msg


def test_timeout_translated(monkeypatch):
    def fake_get(self, *a, **k):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    c = LLMClient(base_url="https://api.example.com", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.test_connection()
    assert "超时" in str(ei.value)


def test_dns_failure_translated(monkeypatch):
    def fake_get(self, *a, **k):
        raise httpx.ConnectError("[WinError 11001] getaddrinfo failed")
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    c = LLMClient(base_url="https://no-such-host.example", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.test_connection()
    assert "域名解析失败" in str(ei.value)


def test_connect_refused_translated(monkeypatch):
    def fake_get(self, *a, **k):
        raise httpx.ConnectError("[WinError 10061] 目标计算机积极拒绝")
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    c = LLMClient(base_url="https://127.0.0.1:9", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.test_connection()
    assert "无法连接到" in str(ei.value)


# ---- list_models：200+HTML（代理门户劫持）不许裸 JSONDecodeError ----

class _FakeResp:
    status_code = 200
    text = ""

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return _FakeResp()


def test_list_models_non_json_guard(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    c = LLMClient(base_url="https://portal.example.com", api_key="k", model="m")
    with pytest.raises(LLMError) as ei:
        c.list_models()
    assert "JSON" in str(ei.value)


# ---- _NetWorker.run 兜底：未预期异常转 LLMError 形态回执，不穿透 QThread.run ----

def _collect(worker, signal_name):
    got = {}
    getattr(worker, signal_name).connect(
        lambda *args: got.update(args=args))
    return got


def test_net_worker_catches_unexpected_exception(monkeypatch):
    from app.ui.bridge import _NetWorker
    w = _NetWorker("test", {"id": "c1", "base_url": "https://x.example"}, None)
    got = _collect(w, "test_done")

    def boom(self):
        raise RuntimeError("未预期爆炸")
    monkeypatch.setattr("app.ui.bridge.LLMClient.test_connection", boom)
    w.run()   # 同步直调 run：不异常穿透即为过
    assert got["args"][0] == "c1"
    assert got["args"][1] is False
    assert "RuntimeError" in got["args"][2], f"回执应带异常类名：{got['args'][2]}"


def test_net_worker_models_mode_catches_unexpected_exception(monkeypatch):
    from app.ui.bridge import _NetWorker
    w = _NetWorker("models", {"id": "c2", "base_url": "https://x.example"}, None)
    got = _collect(w, "models_done")

    def boom(self):
        raise RuntimeError("未预期爆炸")
    monkeypatch.setattr("app.ui.bridge.LLMClient.list_models", boom)
    w.run()
    assert got["args"] == ("c2", [])
