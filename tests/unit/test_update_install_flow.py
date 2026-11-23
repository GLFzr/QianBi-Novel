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
    _touch(d, "QianBi-Novel-v0.20.2-setup.exe")      # 刚下载成功的新版
    rep = upd.prune_old_installers(str(d), current_version="0.20.2", keep=2)
    kept = sorted(os.path.basename(p) for p in rep["kept"])
    assert kept == ["QianBi-Novel-v0.20.0-setup.exe", "QianBi-Novel-v0.20.2-setup.exe"], rep
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


# ---------- M-CI：三通道清单一致性裁决（纯函数面，零网络） ----------

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mci():
    import importlib.util
    path = os.path.join(ROOT, "scripts", "check_manifest_consistency.py")
    spec = importlib.util.spec_from_file_location("qbn_check_manifest_consistency", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pub_manifest(version="99.0.0", sha=None):
    sha = sha or "a" * 64
    return {"version": version,
            "url": "https://github.com/GLFzr/QianBi-Novel/releases/tag/v%s" % version,
            "sha256": sha, "notes": "n",
            "assets": {"setup": {"name": "QianBi-Novel-v%s-setup.exe" % version,
                                 "url": "https://github.com/GLFzr/QianBi-Novel/releases/"
                                        "download/v%s/QianBi-Novel-v%s-setup.exe"
                                        % (version, version),
                                 "sha256": sha, "size": 4096}}}


def test_mci_all_channels_identical_is_ok():
    mci = _mci()
    m = _pub_manifest()
    level, findings, _rows = mci.judge(m, {"raw": (m, ""), "pages": (m, ""),
                                           "jsdelivr": (m, "")})
    assert level == mci.OK and findings == [], findings


def test_mci_jsdelivr_lag_is_warn_not_fail():
    """jsDelivr 旧版 = PASS(WARN)：已知缓存延迟，只会少报不会乱报"""
    mci = _mci()
    old = _pub_manifest("98.0.0")
    new = _pub_manifest("99.0.0")
    level, findings, _rows = mci.judge(new, {"raw": (new, ""), "pages": (new, ""),
                                             "jsdelivr": (old, "")})
    assert level == mci.WARN
    assert any("滞后" in msg for _lv, msg in findings), findings


def test_mci_jsdelivr_newer_or_rewritten_is_fail():
    mci = _mci()
    new = _pub_manifest("99.0.0")
    newer = _pub_manifest("100.0.0")
    rewritten = dict(_pub_manifest("99.0.0"), sha256="b" * 64)
    rewritten["assets"]["setup"]["sha256"] = "b" * 64
    lv1, f1, _ = mci.judge(new, {"raw": (new, ""), "pages": (new, ""),
                                 "jsdelivr": (newer, "")})
    assert lv1 == mci.FAIL and any("还新" in msg for _lv, msg in f1)
    lv2, f2, _ = mci.judge(new, {"raw": (new, ""), "pages": (new, ""),
                                 "jsdelivr": (rewritten, "")})
    assert lv2 == mci.FAIL and any("内容不一致" in msg for _lv, msg in f2)


def test_mci_pages_mismatch_is_fail():
    """Pages 一两分钟内就该追平 raw：不一致不算缓存延迟，直接红"""
    mci = _mci()
    new = _pub_manifest("99.0.0")
    old_pages = _pub_manifest("98.0.0")
    level, findings, _rows = mci.judge(new, {"raw": (new, ""), "pages": (old_pages, ""),
                                             "jsdelivr": (new, "")})
    assert level == mci.FAIL
    assert any("pages" in msg and "落后" in msg for _lv, msg in findings), findings


def test_mci_down_channels_raw_is_fail_others_warn():
    """raw 缺席=FAIL（判定基准）；Pages 404（发布窗口未开）/jsDelivr 缺席=WARN——
    缺席≠分歧，但 Pages **拉到了却不一致**仍是 FAIL（见 test_mci_pages_mismatch_is_fail）"""
    mci = _mci()
    m = _pub_manifest()
    lv_raw, _f, _r = mci.judge(m, {"raw": (None, "ConnectError"), "pages": (m, ""),
                                   "jsdelivr": (m, "")})
    assert lv_raw == mci.FAIL
    lv_pages, f_pages, _r = mci.judge(m, {"raw": (m, ""), "pages": (None, "HTTPError 404"),
                                          "jsdelivr": (m, "")})
    assert lv_pages == mci.WARN and any("pages" in msg for _lv, msg in f_pages)
    lv_js, f_js, _r = mci.judge(m, {"raw": (m, ""), "pages": (m, ""),
                                    "jsdelivr": (None, "ConnectError")})
    assert lv_js == mci.WARN and any("jsdelivr" in msg for _lv, msg in f_js)


def test_mci_dual_write_broken_is_fail_everywhere():
    mci = _mci()
    m = _pub_manifest()
    broken = dict(m, sha256="e" * 64)          # 顶层与 assets.setup 双写断裂
    level, findings, _rows = mci.judge(broken, {"raw": (m, ""), "pages": (m, ""),
                                                "jsdelivr": (m, "")})
    assert level == mci.FAIL
    assert any("双写断裂" in msg and "本地" in msg for _lv, msg in findings), findings


def test_mci_dual_write_contract():
    """老客户端核对的是顶层字段：sha 双写相等 + 版本在 url 里 + setup 有直链"""
    mci = _mci()
    assert mci.dual_write_ok(_pub_manifest()) is True
    split = _pub_manifest()
    split["sha256"] = "f" * 64                                   # 顶层另指一个哈希
    assert mci.dual_write_ok(split) is False
    no_ver_url = _pub_manifest()
    no_ver_url["url"] = "https://github.com/GLFzr/QianBi-Novel/releases"
    assert mci.dual_write_ok(no_ver_url) is False
    assert mci.dual_write_ok({}) is False


def test_mci_parse_manifest_rejects_garbage():
    mci = _mci()
    assert mci.parse_manifest(b"<html>")[0] is None
    assert mci.parse_manifest(json.dumps({"notes": "x"}).encode())[0] is None
    data, err = mci.parse_manifest(json.dumps(_pub_manifest()).encode())
    assert data and err == ""


# ---------- M-SCH：latest.json stats 回填的构件 ----------

def test_msch_notes_embedded_counts_detector():
    from scripts.build_release import notes_has_embedded_counts
    assert notes_has_embedded_counts("单元测试 1122 项 + 探针舰队 49 支，CI 全绿")
    assert notes_has_embedded_counts("新增 12 tests")
    assert not notes_has_embedded_counts("共写默认档与两档制收口，修复若干问题")


def test_msch_count_probes_matches_disk():
    from scripts.build_release import count_probes
    import glob as _glob
    expected = len(_glob.glob(os.path.join(ROOT, "tests", "probe_*.py")))
    assert count_probes() == expected > 0


def test_msch_count_unit_tests_matches_collect_only():
    """stats.unit_tests 的唯一来源：pytest --collect-only（构建机实测，慢一点值得）"""
    from scripts.build_release import count_unit_tests
    assert count_unit_tests() > 1000
