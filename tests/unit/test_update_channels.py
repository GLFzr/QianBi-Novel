# -*- coding: utf-8 -*-
"""更新链路底座：通道链 / 代理 / 缓存 / 验签规则

这一层没有一样是「锦上添花」：`fetch_manifest` 旧版把 404、DNS 污染、验签失败统一
吞成 None，于是「检查失败」在界面上长成「已是最新版本」。所以下面每一条断言都对着
一个具体的说谎姿势，而不是覆盖率数字。
"""
import base64
import json
import os
import time

import pytest

from app import config as cfg_mod
from app import update_check as uc


# ---------- 夹具 ----------

def _cfg(**updates):
    u = dict(cfg_mod.DEFAULT_CONFIG["updates"])
    u.update(updates)
    return {"updates": u}


def _new_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate()


def _signed(priv, payload: dict) -> dict:
    body = dict(payload)
    sig = priv.sign(uc.canonical_bytes(body))
    body["sig"] = base64.b64encode(sig).decode()
    return body


@pytest.fixture
def isolate_updates_dir(tmp_path, monkeypatch):
    """缓存必须落在可隔离的目录：探针跑在真用户环境里，不能留残留"""
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


# ---------- 通道链 ----------

def test_channels_derive_github_family_from_configured_url():
    ch = uc.channels(_cfg())
    keys = [k for k, _ in ch]
    assert keys == ["raw", "pages", "jsdelivr"], keys
    urls = dict(ch)
    assert urls["raw"] == "https://raw.githubusercontent.com/GLFzr/QianBi-Novel/main/latest.json"
    assert urls["jsdelivr"].endswith("GLFzr/QianBi-Novel@main/latest.json")


def test_pages_channel_is_all_lowercase():
    """Pages 子域名只认小写：照抄 `GLFzr` 会拼出一个永远解析不到的主机"""
    urls = dict(uc.channels(_cfg(manifest_url="https://raw.githubusercontent.com/GL/MyRepo/main/latest.json")))
    assert urls["pages"] == "https://gl.github.io/myrepo/latest.json", urls["pages"]
    # jsDelivr 反过来区分大小写，不能被顺手一起 lower
    assert urls["jsdelivr"].endswith("gh/GL/MyRepo@main/latest.json")


def test_custom_url_goes_first_and_survives_without_slug():
    ch = uc.channels(_cfg(custom_url="https://mirror.example.com/qianbi/latest.json",
                          manifest_url=""))
    assert ch[0][0] == "custom" and len(ch) == 1, ch


def test_non_http_channel_is_dropped_not_fetched():
    """`file://` 填进更新源，等于把「检查更新」变成启动本地 PE 的一条路"""
    for bad in ("file:///C:/Windows/win.ini", r"\\nas\share\latest.json", "javascript:alert(1)"):
        ch = uc.channels(_cfg(custom_url=bad))
        assert all(k != "custom" for k, _ in ch), bad


def test_last_good_channel_is_sticky():
    ch = uc.channels(_cfg(last_channel="jsdelivr"))
    assert ch[0][0] == "jsdelivr", ch


def test_lowercase_factory_config_normalizes_to_canonical_case():
    """老版本出厂写的是小写仓库名（GitHub 本身不敏感，派生通道敏感）"""
    urls = dict(uc.channels(_cfg(manifest_url="https://raw.githubusercontent.com/glfzr/qianbi-novel/main/latest.json")))
    assert urls["raw"] == uc._canonical_default_url(
        "https://raw.githubusercontent.com/glfzr/qianbi-novel/main/latest.json")
    assert "GLFzr/QianBi-Novel" in urls["jsdelivr"]


# ---------- 代理 ----------

def test_proxy_mode_none_overrides_env():
    plan = uc.resolve_proxy(_cfg(proxy_mode="none"))
    assert plan.proxy == "" and plan.trust_env is False


def test_proxy_custom_without_url_does_not_invent_one():
    plan = uc.resolve_proxy(_cfg(proxy_mode="custom", proxy_url=""))
    assert plan.proxy == "" and plan.note, plan


def test_proxy_custom_adds_scheme_once():
    plan = uc.resolve_proxy(_cfg(proxy_mode="custom", proxy_url="127.0.0.1:7897"))
    assert plan.proxy == "http://127.0.0.1:7897", plan.proxy


def test_proxy_system_falls_back_to_env_when_absent(monkeypatch):
    monkeypatch.setattr(uc, "system_proxy", lambda: ("", "系统未启用代理"))
    plan = uc.resolve_proxy(_cfg(proxy_mode="system"))
    assert plan.proxy == "" and plan.trust_env is True and plan.note == "系统未启用代理"


def test_stale_proxy_does_not_kill_a_working_update(monkeypatch):
    """带代理时全链失败 → 再无代理跑一遍。陈旧系统代理不该挡死本来能成的更新"""
    calls = []

    def fake(url, plan, timeout=uc.TIMEOUT):
        calls.append(bool(plan.proxy))
        return ("", "代理不可用") if plan.proxy else ('{"version":"9.9.9","url":"https://x/y"}', "")

    monkeypatch.setattr(uc, "fetch_text", fake)
    monkeypatch.setattr(uc, "resolve_proxy",
                        lambda cfg: uc.ProxyPlan(proxy="http://127.0.0.1:1", trust_env=False, label="跟随系统"))
    res = uc.check(_cfg(), "0.17.0")
    assert res.state == uc.STATE_NEW
    assert calls[:1] == [True] and any(c is False for c in calls), calls
    assert any(e["channel"] == "proxy" for e in res.errors), res.errors
    assert res.proxy_label.endswith("（回退）") or "不使用代理" in res.proxy_label


def test_deadline_stops_the_chain(monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: ("", "超时"))
    clock = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr(uc.time, "monotonic", lambda: next(clock))
    res = uc.check(_cfg(), "0.17.0", deadline=1.0)
    assert res.state == uc.STATE_FAILED
    assert any("总时限" in e["reason"] for e in res.errors), res.errors


# ---------- 结果对象：不许说谎 ----------

def test_all_channels_down_is_failed_not_latest(monkeypatch):
    """旧实现把这条判成「已是最新版本」——断网用户会以为自己已经最新"""
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: ("", "连接失败"))
    res = uc.check(_cfg(), "0.17.0")
    assert res.state == uc.STATE_FAILED
    assert not res.is_new and not res.manifest
    assert len(res.errors) >= 3 and all(e["reason"] for e in res.errors)


def test_first_success_wins_and_is_the_reported_channel(monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: (
        ('{"version":"0.99.0","url":"https://x"}', "") if "jsdelivr" in url else ("", "HTTP 404")))
    res = uc.check(_cfg(), "0.17.0")
    assert (res.state, res.channel) == (uc.STATE_NEW, "jsdelivr"), res
    assert [e["channel"] for e in res.errors] == ["raw", "pages"]


def test_garbage_response_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: ("<html>登录</html>", ""))
    res = uc.check(_cfg(), "0.17.0")
    assert res.state == uc.STATE_FAILED
    assert "JSON" in res.errors[0]["reason"], res.errors


def test_same_version_is_latest(monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: (
        '{"version":"0.17.0","url":"https://x"}', ""))
    assert uc.check(_cfg(), "0.17.0").state == uc.STATE_LATEST


# ---------- 验签：未验签不得执行 ----------

def test_unsigned_manifest_can_be_shown_but_not_installed(monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: (
        json.dumps({"version": "0.99.0", "url": "https://x"}), ""))
    res = uc.check(_cfg(), "0.17.0")
    assert res.is_new and not res.verified
    assert res.can_install is False
    assert "未签名" in res.verify_reason


def test_pinned_key_signature_unlocks_install(monkeypatch):
    priv = _new_key()
    pub = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    monkeypatch.setattr(uc, "PUBKEYS", [{"kid": "test", "pub": pub}])
    body = _signed(priv, {"version": "0.99.0", "url": "https://x", "notes": "n", "sha256": "a" * 64})
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: (json.dumps(body), ""))
    res = uc.check(_cfg(), "0.17.0")
    assert (res.verified, res.can_install) == (True, True), res.verify_reason


def test_signature_from_an_unpinned_key_is_rejected(monkeypatch):
    """否则「任何陌生人签的清单」都算作者发布——多通道就白加了"""
    monkeypatch.setattr(uc, "PUBKEYS", [{"kid": "other", "pub": base64.b64encode(
        _new_key().public_key().public_bytes_raw()).decode()}])
    body = _signed(_new_key(), {"version": "0.99.0", "url": "https://x"})
    verified, reason = uc.verify_manifest(body)
    assert verified is False and "不匹配" in reason, reason


def test_tampering_any_field_breaks_the_signature():
    """签名作用域必须是整个 payload：只签 version 等于没签"""
    priv = _new_key()
    body = _signed(priv, {"version": "0.99.0", "url": "https://safe/x", "sha256": "a" * 64})
    swapped_url = dict(body, url="https://evil/x")
    assert uc.verify_manifest(swapped_url)[0] is False


def test_base64_junk_signature_is_not_a_crash():
    assert uc.verify_manifest({"version": "1.0", "sig": "!!!not base64!!!"})[0] is False


def test_missing_crypto_degrades_without_crashing(monkeypatch):
    """打包漏收 cryptography 时症状必须是「无法验证」，不是启动崩溃"""
    monkeypatch.setattr(uc, "CRYPTO_OK", False)
    monkeypatch.setattr(uc, "CRYPTO_ERR", "ModuleNotFoundError")
    verified, reason = uc.verify_manifest({"version": "1.0", "sig": "AAAA"})
    assert verified is False and "cryptography" in reason


def test_canonical_bytes_drop_sig_only():
    raw = uc.canonical_bytes({"b": 1, "sig": "x", "a": "中"})
    assert json.loads(raw.decode()) == {"a": "中", "b": 1}
    assert raw == uc.canonical_bytes({"a": "中", "sig": "different", "b": 1})


# ---------- 缓存 ----------

def test_cache_roundtrip_reverifies_every_read(isolate_updates_dir, monkeypatch):
    """缓存只存原文：一次验过不能变成永久信任"""
    priv = _new_key()
    pub = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    monkeypatch.setattr(uc, "PUBKEYS", [{"kid": "test", "pub": pub}])
    body = _signed(priv, {"version": "0.99.0", "url": "https://x"})
    uc.save_cache(json.dumps(body), "pages")
    res = uc.cached_result(_cfg(), "0.17.0")
    assert res and res.verified and res.channel == "cache"
    monkeypatch.setattr(uc, "PUBKEYS", [])
    assert uc.cached_result(_cfg(), "0.17.0").verified is False


def test_stale_cache_about_my_own_version_stays_quiet(isolate_updates_dir):
    uc.save_cache(json.dumps({"version": "0.99.0", "url": "https://x"}), "raw")
    assert uc.cached_result(_cfg(), "0.99.0") is None


def test_corrupt_cache_is_ignored(isolate_updates_dir):
    os.makedirs(uc.updates_dir(), exist_ok=True)
    with open(uc.cache_file(), "w", encoding="utf-8") as f:
        f.write('{"raw": "not json"}')
    assert uc.cached_result(_cfg(), "0.17.0") is None


def test_cache_dir_follows_config_dir(isolate_updates_dir):
    assert uc.updates_dir().startswith(str(isolate_updates_dir))


# ---------- 限流与杀开关 ----------

def test_auto_check_respects_switch_and_interval(monkeypatch):
    monkeypatch.delenv(uc.OFFLINE_ENV, raising=False)
    now = time.time()
    assert uc.should_auto_check(_cfg(auto_check=False), now) is False
    assert uc.should_auto_check(_cfg(auto_check=True, last_check_ts=now - 60), now) is False
    assert uc.should_auto_check(_cfg(auto_check=True, last_check_ts=now - 90000), now) is True
    assert uc.should_auto_check(_cfg(auto_check=True), now) is True


def test_offline_env_kills_every_request(monkeypatch):
    """发布闸门（打包态 selftest）与所有探针的零网络保证都靠它"""
    monkeypatch.setenv(uc.OFFLINE_ENV, "1")
    assert uc.offline() is True
    text, reason = uc.fetch_text("https://example.invalid/x.json", uc.ProxyPlan())
    assert text == "" and uc.OFFLINE_ENV in reason
    assert uc.should_auto_check(_cfg(auto_check=True), time.time()) is False


def test_offline_env_values_are_strict(monkeypatch):
    monkeypatch.setenv(uc.OFFLINE_ENV, "0")
    assert uc.offline() is False


# ---------- 落盘卫生 ----------

def test_version_field_cannot_carry_a_path():
    assert uc.sanitize_version("../../windows/system32/cmd") == "windowssystem32cmd"
    assert uc.sanitize_version("0.18.0") == "0.18.0"
    assert not uc.sanitize_version("0.18.0...").endswith(".")


def test_download_name_ignores_nested_asset_names():
    assert uc.setup_download_name({"version": "0.18.0"}).endswith("v0.18.0-setup.exe")
    assert "/" not in uc.setup_download_name({"version": "../x", "assets": {"setup": {"name": "a/b.exe"}}})
    assert uc.setup_download_name({"version": "1", "assets": {"setup": {"name": "ok.exe"}}}) == "ok.exe"


def test_asset_url_policy():
    assert uc.safe_asset_url("https://github.com/a/b") is True
    assert uc.safe_asset_url("file:///C:/x.exe") is False
    assert uc.safe_asset_url(r"\\nas\x.exe") is False


# ---------- 与既有接线保持一致 ----------

def test_to_map_carries_everything_the_dialog_needs(monkeypatch):
    """QML 只读一次 bridge.updateState()，字段缺一个就是一片空白"""
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: (
        json.dumps({"version": "0.99.0", "url": "https://x", "notes": "n", "sha256": "b" * 64}), ""))
    m = uc.check(_cfg(), "0.17.0").to_map()
    assert {"state", "hasNew", "verified", "canInstall", "version", "notes", "url",
            "sha256", "channelLabel", "errors", "checkedAt"} <= set(m)
    assert m["hasNew"] is True and m["canInstall"] is False


def test_offline_manifest_import_reports_why_it_is_not_trusted(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"version": "0.99.0", "url": "https://x"}), encoding="utf-8")
    data, reason = uc.load_manifest_file(str(p))
    assert data and "未签名" in reason
    missing, err = uc.load_manifest_file(str(tmp_path / "nope.json"))
    assert missing is None and "读不到" in err
