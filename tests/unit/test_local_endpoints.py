# -*- coding: utf-8 -*-
"""本地模型端点（Ollama / llama.cpp / LM Studio / vLLM / KoboldCpp / text-gen-webui）。

这一层的存在理由：本机服务没有 Key、端口各家不同、地址常被写成 `127.0.0.1:11434`
（无协议头），而远端域名可以被伪造成 `localhost.evil.com`。所有判定收在纯函数里，
扫描走注入的 get 以便离线测试。
"""
import json

from app.llm import local


def test_normalize_local_url_adds_http_for_bare_loopback():
    assert local.normalize_local_url("127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert local.normalize_local_url("localhost:8080") == "http://localhost:8080"
    assert local.normalize_local_url("[::1]:1234") == "http://[::1]:1234"


def test_normalize_local_url_leaves_remote_and_scheme_untouched():
    assert local.normalize_local_url("https://api.deepseek.com") == "https://api.deepseek.com"
    # 远端裸域名不替用户猜协议：猜错会把 https 网关变成明文 http
    assert local.normalize_local_url("api.deepseek.com") == "api.deepseek.com"
    assert local.normalize_local_url("") == ""


def test_is_local_base_url_accepts_all_loopback_forms():
    for url in ("http://127.0.0.1:11434", "127.0.0.1:11434", "http://localhost:1234/v1",
                "http://[::1]:8080", "http://0.0.0.0:8000"):
        assert local.is_local_base_url(url), url


def test_is_local_base_url_rejects_lookalike_and_lan():
    for url in ("https://api.deepseek.com", "http://192.168.1.5:11434",
                "http://localhost.evil.com:11434", "http://notlocalhost:11434"):
        assert not local.is_local_base_url(url), url


def test_needs_api_key_only_for_non_local_or_missing_key():
    assert local.needs_api_key({"base_url": "https://api.deepseek.com", "api_key": ""}) is True
    assert local.needs_api_key({"base_url": "http://127.0.0.1:11434", "api_key": ""}) is False
    assert local.needs_api_key({"base_url": "http://[::1]:11434", "api_key": ""}) is False
    assert local.needs_api_key({"base_url": "https://api.deepseek.com", "api_key": "sk-x"}) is False
    assert local.needs_api_key({}) is True


def test_parse_openai_models_sorts_and_dedups():
    payload = {"object": "list", "data": [{"id": "b"}, {"id": "a"}, {"id": "a"}, {"x": 1}]}
    assert local.parse_openai_models(payload) == ["a", "b"]
    assert local.parse_openai_models(None) == []
    assert local.parse_openai_models({"data": "nope"}) == []


def test_parse_ollama_tags_reads_name_field():
    payload = {"models": [{"name": "qwen2.5:7b", "size": 1}, {"model": "ignored"}]}
    assert local.parse_ollama_tags(payload) == ["qwen2.5:7b"]
    assert local.parse_ollama_tags({}) == []


def test_probe_service_falls_back_to_ollama_tags():
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        if url.endswith("/v1/models"):
            return 404, ""
        return 200, json.dumps({"models": [{"name": "qwen2.5:7b"}]})

    hit = local.probe_service(11434, get=fake_get)
    assert hit is not None
    assert hit["models"] == ["qwen2.5:7b"]
    assert hit["service"] == "Ollama"
    assert hit["port"] == 11434
    assert calls[-1].endswith("/api/tags")


def test_probe_service_reports_up_with_zero_models():
    def fake_get(url, timeout):
        return 200, json.dumps({"data": []})

    hit = local.probe_service(8080, get=fake_get)
    assert hit is not None and hit["count"] == 0
    assert hit["service"] == "llama.cpp"


def test_probe_service_returns_none_when_nothing_listens():
    def fake_get(url, timeout):
        raise OSError("connection refused")

    assert local.probe_service(1234, get=fake_get) is None


def test_scan_ports_skips_dead_ports_and_sorts():
    def fake_probe(port):
        if port == 8080:
            return {"port": port, "service": "llama.cpp", "models": [], "count": 0}
        return None

    hits = local.scan_ports(probe=fake_probe)
    assert [h["port"] for h in hits] == [8080]


def test_scan_ports_default_targets_are_the_six_known_ports():
    seen = []

    def fake_probe(port):
        seen.append(port)
        return None

    local.scan_ports(probe=fake_probe)
    assert sorted(seen) == [1234, 5000, 5001, 8000, 8080, 11434]


def test_sanitize_proxy_env_drops_ipv6_entries():
    env = {"NO_PROXY": "localhost,127.0.0.1,::1,[::1]",
           "no_proxy": "::1,10.0.0.1"}
    local.sanitize_proxy_env(env)
    assert env["NO_PROXY"] == "localhost,127.0.0.1", env
    assert env["no_proxy"] == "10.0.0.1", env


# ---- 接入层：URL 规整 / 预设 / 测试连接 / 模型拉取 ----

def test_check_base_url_normalizes_bare_local_host_and_is_idempotent():
    from app.llm.client import check_base_url

    once = check_base_url("127.0.0.1:11434")
    assert once == "http://127.0.0.1:11434/v1", once
    assert check_base_url(once) == once
    assert check_base_url("http://[::1]:8080") == "http://[::1]:8080/v1"


def test_local_presets_are_keyless_and_point_at_loopback():
    from app.llm import providers as pv

    for svc in local.LOCAL_SERVICES:
        key = svc["key"]
        assert key in pv.PROVIDERS, key
        spec = pv.PROVIDERS[key]
        assert spec["builtin"] is False, key
        assert spec["base_url"].startswith("http://127.0.0.1:%d" % svc["port"]), key
        assert local.needs_api_key({"base_url": spec["base_url"], "api_key": ""}) is False, key


def test_test_connection_translates_invalid_url(monkeypatch):
    import httpx

    from app.llm.client import LLMClient, LLMError

    def boom(self, url, **kw):
        raise httpx.InvalidURL("Invalid port: ':1]'")

    monkeypatch.setattr(httpx.Client, "get", boom)
    c = LLMClient("http://127.0.0.1:11434", "", "m")
    try:
        c.test_connection()
    except LLMError as e:
        assert "地址" in str(e), str(e)
    else:
        raise AssertionError("畸形地址竟然没有翻成中文化错误")


def test_test_connection_local_reports_model_count(monkeypatch):
    import httpx
    import json

    from app.llm.client import LLMClient

    class _Resp:
        status_code = 200
        text = json.dumps({"object": "list", "data": [{"id": "qwen2.5:7b"}]})
        def json(self):
            return json.loads(self.text)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _Resp())
    msg = LLMClient("http://127.0.0.1:11434", "", "qwen2.5:7b").test_connection()
    assert "1" in msg and "模型" in msg, msg


def test_list_models_falls_back_to_ollama_tags(monkeypatch):
    import httpx
    import json

    from app.llm.client import LLMClient

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or {}
            self.text = json.dumps(self._payload)
        def json(self):
            return self._payload

    def fake_get(self, url, **kw):
        if url.endswith("/api/tags"):
            return _Resp(200, {"models": [{"name": "qwen2.5:7b"}]})
        return _Resp(404, {"error": "not found"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    got = LLMClient("http://127.0.0.1:11434", "", "qwen2.5:7b").list_models()
    assert got == ["qwen2.5:7b"], got

