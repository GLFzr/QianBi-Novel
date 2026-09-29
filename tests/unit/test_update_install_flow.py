# -*- coding: utf-8 -*-
"""B7 更新下载/续传/清理链路补测 + U-2 通道不短路 + U-C 旧包清理（C09a）

盯的都是「升级那天才会暴露」的事：
- download/resume：Range 续传、服务端不认 Range 时从头再来、边下边算哈希；
- 哈希失败：不匹配不安装、清单没给哈希更不安装；
- U-1 钉子：**损坏（非截断）的半截文件会毒化续传**——resume 对已有字节算哈希再追加，
  中段被改写的文件每次都拼出坏哈希，只能等 stale_partial 或手删。本测试按现状钉死，
  未来的修复（前缀独立校验/哈希不符即弃重下）必须**有意识地**翻掉这条断言；
- U-C：prune_old_installers 保留当前+上一版；
- U-2：未验签清单不写缓存、不短路——后面的干净通道照常试，全链无可信结果才回退
  显示第一条未验签结果；
- 状态机离屏分支：can_install 三重门（验签 × 有新版 × 非失败态）。

桥侧 TODO：bridge.installUpdateNow / updateState 的状态机离屏测试（arm→下载→
校验→安装两步确认、离屏 QML 分支）本轮不做——bridge.py 属 S2 领地，接线随
B8b 搬迁轮补：①下载成功后调 prune_old_installers；②/quiet 安装编排（U-A）。
全部假传输，零真机调用。
"""
import base64
import hashlib
import json
import os
import time

import pytest

from app import config as cfg_mod
from app import update_check as uc
from app import update_install as upd


# ---------- 夹具与假传输 ----------

@pytest.fixture
def isolate_updates_dir(tmp_path, monkeypatch):
    """缓存/安装包落盘必须隔离：探针跑在真用户环境里，不能留残留"""
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    """download 有自己的 offline 杀开关：单测里确保它是关的"""
    monkeypatch.delenv(uc.OFFLINE_ENV, raising=False)


CONTENT = b"A" * 100_000 + b"B" * 100_000     # 200KB 假安装包（跨多个 64KB chunk）
CONTENT_SHA = hashlib.sha256(CONTENT).hexdigest()


class _FakeStreamResp:
    """诚实的服务器：带 Range 且认 → 206 + 剩余字节；不认 → 200 + 全量"""

    def __init__(self, url_body=None, ignore_range=False):
        self._body = url_body or {}
        self._ignore_range = ignore_range
        self.status_code = 200
        self.headers = {}

    def stream(self, method, url, headers=None):   # 由 _FakeHttpx 转调
        body = self._body.get(url, b"")
        pos = 0
        rng = (headers or {}).get("Range")
        if rng and not self._ignore_range:
            pos = int(rng.split("=", 1)[1].split("-", 1)[0] or 0)
            self.status_code = 206
        else:
            self.status_code = 200
        served = body[pos:]
        self.headers = {"Content-Length": str(len(served))}
        self._served = served
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, n):
        for i in range(0, len(self._served), n):
            yield self._served[i:i + n]


class _FakeHttpx:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def __call__(self, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        return self._resp.stream(method, url, headers=headers)


@pytest.fixture
def fake_http(monkeypatch):
    import httpx
    def _install(resp):
        fake = _FakeHttpx(resp)
        monkeypatch.setattr(httpx, "Client", fake)
        return fake
    return _install


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


# ---------- download / resume ----------

def test_download_full_success_writes_and_hashes(fake_http, tmp_path):
    fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}))
    dest = str(tmp_path / "setup.exe")
    out = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                       expected_sha=CONTENT_SHA)
    assert out["ok"] is True and out["resumed"] is False, out
    assert out["sha256"] == CONTENT_SHA
    with open(dest, "rb") as f:
        assert f.read() == CONTENT


def test_resume_sends_range_and_appends_prefix_hash(fake_http, tmp_path):
    """断点续传：带 Range: bytes=N-，已有前缀参与哈希，落盘=完整原文"""
    http = fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}))
    dest = str(tmp_path / "setup.exe")
    with open(dest, "wb") as f:
        f.write(CONTENT[:150_000])
    out = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                       expected_sha=CONTENT_SHA)
    assert out["ok"] is True and out["resumed"] is True, out
    assert http.calls and http.calls[0]["headers"].get("Range") == "bytes=150000-"
    with open(dest, "rb") as f:
        assert f.read() == CONTENT


def test_resume_survives_server_ignoring_range(fake_http, tmp_path):
    """服务端不认 Range 回 200 全量：从头重来，绝不把前缀拼成半个坏文件"""
    fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}, ignore_range=True))
    dest = str(tmp_path / "setup.exe")
    with open(dest, "wb") as f:
        f.write(CONTENT[:150_000])
    out = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                       expected_sha=CONTENT_SHA)
    assert out["ok"] is True and out["resumed"] is False, out
    with open(dest, "rb") as f:
        assert f.read() == CONTENT


def test_hash_mismatch_refuses_to_install(fake_http, tmp_path):
    fake_http(_FakeStreamResp({"https://x/setup.exe": b"tampered-bytes"}))
    dest = str(tmp_path / "setup.exe")
    out = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                       expected_sha=CONTENT_SHA)
    assert out["ok"] is False and "SHA-256 不匹配" in out["reason"], out


def test_missing_expected_sha_refuses_to_install(fake_http, tmp_path):
    """清单没给哈希：下得再完整也不许装（「下完了」不等于「校验过」）"""
    fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}))
    out = upd.download("https://x/setup.exe", str(tmp_path / "s.exe"),
                       uc.ProxyPlan(), expected_sha="")
    assert out["ok"] is False and "无法校验" in out["reason"], out


def test_cancel_keeps_partial_for_next_resume(fake_http, tmp_path):
    fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}))
    _n = [0]

    def cancelled():
        _n[0] += 1
        return _n[0] > 1          # 第二个 chunk 后取消

    dest = str(tmp_path / "setup.exe")
    out = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                       expected_sha=CONTENT_SHA, cancelled=cancelled)
    assert out["ok"] is False and "取消" in out["reason"], out
    assert os.path.getsize(dest) > 0, "半截文件必须留盘（下次续传）"


def test_http_error_is_reported_not_installed(fake_http, tmp_path):
    class _R:
        status_code = 403
        headers = {}

        def stream(self, method, url, headers=None):
            return self

        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    fake_http(_R())
    out = upd.download("https://x/setup.exe", str(tmp_path / "s.exe"),
                       uc.ProxyPlan(), expected_sha=CONTENT_SHA)
    assert out["ok"] is False and "403" in out["reason"], out


# ---------- U-1 钉子：损坏的半截文件毒化续传 ----------

def test_u1_corrupted_partial_poisons_resume(fake_http, tmp_path):
    """损坏（非截断）的半截文件：每次续传都拼出坏哈希，且半截文件留盘继续毒化。

    现状钉子（U-1）：download 的 resume 只把「已有字节」并进哈希，不校验前缀归属——
    中段被改写的文件永远续不出正确哈希。出路只有 stale_partial(6h) 或手删。
    修复（前缀独立校验 / mismatch 即弃重下）落地时必须改写本断言并说明新语义。
    """
    fake_http(_FakeStreamResp({"https://x/setup.exe": CONTENT}))
    dest = str(tmp_path / "setup.exe")
    corrupt = bytearray(CONTENT[:150_000])
    corrupt[100_000] ^= 0xFF                     # 中段翻转一个字节
    with open(dest, "wb") as f:
        f.write(bytes(corrupt))

    out1 = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                        expected_sha=CONTENT_SHA)
    assert out1["ok"] is False and out1["resumed"] is True
    assert "SHA-256 不匹配" in out1["reason"]

    out2 = upd.download("https://x/setup.exe", dest, uc.ProxyPlan(),
                        expected_sha=CONTENT_SHA)
    assert out2["ok"] is False, "毒化的续传点必须再次失败（现状）"
    assert os.path.exists(dest), "现状不清理毒化文件（修复时翻转此断言）"


def test_stale_partial_expires_the_poison(tmp_path):
    """毒化续传点的现状出路：6h 后 stale_partial 清掉，下次下载从头再来"""
    dest = str(tmp_path / "setup.exe")
    with open(dest, "wb") as f:
        f.write(b"poisoned")
    old = time.time() - 7 * 3600
    os.utime(dest, (old, old))
    upd.stale_partial(dest)
    assert not os.path.exists(dest)
    with open(dest, "wb") as f:
        f.write(b"fresh")
    upd.stale_partial(dest)
    assert os.path.exists(dest)


# ---------- U-C：旧安装包保留清理 ----------

def _touch(directory, name, size=16):
    p = os.path.join(str(directory), name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


def test_prune_keeps_current_and_previous(tmp_path):
    """台账验收原文：updates/ 已有三份 setup → 下载成功新版后剩两份（当前+上一版）"""
    d = tmp_path / "updates"
    d.mkdir()
    _touch(d, "QianBi-Novel-v0.18.0-setup.exe")
    _touch(d, "QianBi-Novel-v0.19.0-setup.exe")
    _touch(d, "QianBi-Novel-v0.20.0-setup.exe")
    _touch(d, "QianBi-Novel-v0.21.0-setup.exe")      # 刚下载成功的新版
    rep = upd.prune_old_installers(str(d), current_version="0.21.0", keep=2)
    kept = sorted(os.path.basename(p) for p in rep["kept"])
    assert kept == ["QianBi-Novel-v0.20.0-setup.exe", "QianBi-Novel-v0.21.0-setup.exe"], rep
    assert sorted(os.path.basename(p) for p in rep["deleted"]) == [
        "QianBi-Novel-v0.18.0-setup.exe", "QianBi-Novel-v0.19.0-setup.exe"], rep
    remaining = [n for n in os.listdir(str(d)) if n.endswith(".exe")]
    assert len(remaining) == 2, remaining


def test_prune_never_touches_unparseable_or_newer(tmp_path):
    """解析不出版本/比当前还新的文件：清理函数无权动它们"""
    d = tmp_path / "updates"
    d.mkdir()
    _touch(d, "QianBi-Novel-v0.16.0-setup.exe")
    _touch(d, "readme.txt")                              # 非 exe，根本不进名单
    _touch(d, "QianBi-Novel-vX-setup.exe")               # 版本段解析不出
    _touch(d, "QianBi-Novel-v99.0.0-setup.exe")          # 比当前还新
    rep = upd.prune_old_installers(str(d), current_version="0.20.0", keep=2)
    assert rep["deleted"] == [], rep
    assert os.path.exists(str(d / "QianBi-Novel-v99.0.0-setup.exe"))
    assert "readme.txt" not in str(rep)
    assert any("vX" in s for s in rep["skipped"])


def test_prune_default_version_comes_from_app(monkeypatch, tmp_path):
    """current_version 缺省取 app.__version__（单测 monkeypatch 验证缺省路径）"""
    import app
    d = tmp_path / "updates"
    d.mkdir()
    monkeypatch.setattr(app, "__version__", "0.19.0", raising=False)
    _touch(d, "QianBi-Novel-v0.18.0-setup.exe")
    _touch(d, "QianBi-Novel-v0.19.0-setup.exe")
    _touch(d, "QianBi-Novel-v0.17.0-setup.exe")
    rep = upd.prune_old_installers(str(d), keep=2)
    assert sorted(os.path.basename(p) for p in rep["kept"]) == [
        "QianBi-Novel-v0.18.0-setup.exe", "QianBi-Novel-v0.19.0-setup.exe"], rep
    assert not os.path.exists(str(d / "QianBi-Novel-v0.17.0-setup.exe"))


def test_prune_missing_dir_is_reported_not_crash(tmp_path):
    rep = upd.prune_old_installers(str(tmp_path / "nope"), current_version="0.20.0")
    assert rep["deleted"] == [] and rep["skipped"], rep


# ---------- U-2：未验签不写缓存、不短路 ----------

def test_u2_unsigned_new_manifest_is_not_cached(isolate_updates_dir, monkeypatch):
    def fake(url, plan, timeout=uc.TIMEOUT):
        return (json.dumps({"version": "99.0.0", "url": "https://x"}), "")
    monkeypatch.setattr(uc, "fetch_text", fake)
    res = uc.check(_cfg(), "0.20.0")
    assert res.is_new and not res.verified
    assert not os.path.exists(uc.cache_file()), "未验签清单不得写缓存（U-2）"


def test_u2_unverified_channel_does_not_shadow_cleaner_one(isolate_updates_dir, monkeypatch):
    """raw 被投毒（未验签有新版）→ 不短路，jsDelivr 的干净清单照常被采用并写缓存"""
    priv = _new_key()
    pub = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    monkeypatch.setattr(uc, "PUBKEYS", [{"kid": "test", "pub": pub}])
    good = _signed(priv, {"version": "99.0.0", "url": "https://x", "sha256": "a" * 64})

    def fake(url, plan, timeout=uc.TIMEOUT):
        if "raw.githubusercontent" in url:
            return (json.dumps({"version": "99.0.0", "url": "https://evil"}), "")  # 投毒
        if "jsdelivr" in url:
            return (json.dumps(good), "")
        return ("", "HTTP 404")
    monkeypatch.setattr(uc, "fetch_text", fake)
    res = uc.check(_cfg(), "0.20.0")
    assert res.channel == "jsdelivr" and res.verified and res.can_install, res
    assert res.version() == "99.0.0"
    cached = uc.cached_result(_cfg(), "0.20.0")
    assert cached is not None and cached.verified, "写进缓存的必须是验签过的那份"


def test_u2_all_unverified_falls_back_to_first_unverified(isolate_updates_dir, monkeypatch):
    """全链都未验签：回退显示第一条（「未验签也看得见」的既有 UX 不丢），仍不写缓存"""
    def fake(url, plan, timeout=uc.TIMEOUT):
        return (json.dumps({"version": "99.0.0", "url": "https://x"}), "")
    monkeypatch.setattr(uc, "fetch_text", fake)
    res = uc.check(_cfg(), "0.20.0")
    assert res.is_new and not res.verified and res.can_install is False
    assert res.channel == "raw", res            # 回退的是**第一条**未验签结果
    assert not os.path.exists(uc.cache_file())


def test_u2_verified_new_manifest_still_short_circuits_and_caches(isolate_updates_dir, monkeypatch):
    """验签通过的新清单：第一通道即返回并写缓存（改动前的行为原样保留）"""
    priv = _new_key()
    pub = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    monkeypatch.setattr(uc, "PUBKEYS", [{"kid": "test", "pub": pub}])
    good = _signed(priv, {"version": "99.0.0", "url": "https://x", "sha256": "a" * 64})

    def fake(url, plan, timeout=uc.TIMEOUT):
        if "raw.githubusercontent" in url:
            return (json.dumps(good), "")
        raise AssertionError("验签通过就该短路，不该再试后面的通道")
    monkeypatch.setattr(uc, "fetch_text", fake)
    res = uc.check(_cfg(), "0.20.0")
    assert res.channel == "raw" and res.can_install
    assert os.path.exists(uc.cache_file())


# ---------- 状态机离屏分支（update_check 侧；bridge 侧见文件头 TODO） ----------

def test_state_machine_install_gate_is_verified_new_only():
    """can_install 三重门：有新版 × 验签通过；latest/failed 无论验没验签都装不了"""
    m = {"version": "99.0.0", "url": "https://x"}
    new_ok = uc.CheckResult(state=uc.STATE_NEW, manifest=m, verified=True)
    new_bad = uc.CheckResult(state=uc.STATE_NEW, manifest=m, verified=False)
    latest = uc.CheckResult(state=uc.STATE_LATEST, manifest=m, verified=True)
    failed = uc.CheckResult(state=uc.STATE_FAILED, manifest=None, verified=False)
    assert new_ok.can_install is True
    assert new_bad.can_install is False
    assert latest.can_install is False
    assert failed.can_install is False and failed.is_new is False


def test_state_machine_failed_has_no_manifest(isolate_updates_dir, monkeypatch):
    monkeypatch.setattr(uc, "fetch_text", lambda url, plan, timeout=uc.TIMEOUT: ("", "连接失败"))
    res = uc.check(_cfg(), "0.20.0")
    assert res.state == uc.STATE_FAILED and res.manifest is None
    assert not res.is_new and not res.can_install
