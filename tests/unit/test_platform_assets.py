# -*- coding: utf-8 -*-
"""平台资产与「一键更新」门槛（app/update_check.py）

同一份 latest.json 同时挂着 .exe 与 .dmg，客户端各取各的：下载名、哈希、下载地址
三处必须同指一份，否则「校验的是 dmg、下载的是 exe」这种错位没人拦得住。连带钉住
三条平台差异——老清单只认 Windows 包、运行方式门槛两侧不同、系统代理两侧读法不同。
"""
import os
import subprocess
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from app import update_check as uc  # noqa: E402


# ---------- 平台资产 ----------

def test_asset_kind_by_platform():
    assert uc.asset_kind("darwin") == "dmg"
    assert uc.asset_kind("win32") == "setup"
    assert uc.asset_kind("linux") == "setup"
    assert uc.asset_ext("dmg") == ".dmg"


def test_download_name_defaults_to_platform_asset(monkeypatch):
    monkeypatch.setattr(uc, "asset_kind", lambda platform=None: "dmg")
    m = {"version": "99.0.0", "assets": {"dmg": {"name": "QianBi-Novel-v99-mac.dmg"}}}
    assert uc.download_name(m) == "QianBi-Novel-v99-mac.dmg"
    assert uc.download_name({"version": "99.0.0"}).endswith("-mac.dmg"), "没给名字时按本平台后缀兜"
    assert uc.setup_download_name(m).endswith("-setup.exe"), "Windows 侧入口不受平台默认影响"


def test_asset_name_only_accepted_when_same_family():
    """拿 .exe 名字当 .dmg 落盘：校验通过之后点开的是另一个程序"""
    assert uc.download_name({"version": "1.2.3", "assets": {"dmg": {"name": "evil.exe"}}},
                            "dmg") == "QianBi-Novel-v1.2.3-mac.dmg"
    assert "/" not in uc.download_name(
        {"version": "../x", "assets": {"dmg": {"name": "a/b.dmg"}}}, "dmg")


def test_legacy_manifest_counts_only_for_setup(monkeypatch):
    legacy = {"version": "1.0.0", "url": "https://x/setup.exe", "sha256": "aa"}
    monkeypatch.setattr(uc, "asset_kind", lambda platform=None: "dmg")
    assert uc.has_platform_asset(legacy) is False, "老清单的字节是 Windows 的，Mac 不许认领"
    assert uc.asset_sha(legacy) == "", "拿 exe 的哈希去校验 dmg 只会失败得莫名其妙"
    monkeypatch.setattr(uc, "asset_kind", lambda platform=None: "setup")
    assert uc.has_platform_asset(legacy) is True
    assert uc.asset_sha(legacy) == "aa"


def test_asset_sha_prefers_own_entry():
    m = {"sha256": "TOP", "assets": {"dmg": {"sha256": "DMG"}}}
    assert uc.asset_sha(m, "dmg") == "DMG"
    assert uc.asset_sha(m, "setup") == "TOP"
    assert uc.asset_sha({"sha256": "TOP"}, "dmg") == ""


def test_asset_url_list_takes_only_own_platform():
    m = {"url": "https://x/top-setup.exe",
         "assets": {"dmg": {"url": "https://x/a-mac.dmg", "mirrors": ["https://m/a.dmg"]}}}
    assert uc.asset_url_list(m, "dmg") == ["https://x/a-mac.dmg", "https://m/a.dmg"]
    assert uc.asset_url_list(m, "setup") == ["https://x/top-setup.exe"]


def test_asset_urls_mirror_prefix_accepts_dmg():
    from app import update_install as ui
    m = {"version": "99.0.0",
         "assets": {"dmg": {"url": "https://x/a-mac.dmg", "sha256": "s"}}}
    urls = ui.asset_urls(m, "dmg", "https://my.lan/mirror/")
    assert urls[-1] == "https://my.lan/mirror/" + uc.download_name(m, "dmg")
    urls = ui.asset_urls(m, "dmg", "https://my.lan/mirror/QianBi-Novel-v99-mac.dmg")
    assert urls[-1].endswith("-mac.dmg"), "完整下载地址也认（.exe/.dmg 后缀）"
    assert urls[0] == "https://x/a-mac.dmg", "官方直链排第一，用户镜像排最后"


# ---------- 运行方式门槛 ----------

def test_install_allowed_matrix():
    assert uc.install_allowed("installed", "darwin") is True
    assert uc.install_allowed("portable", "darwin") is True, "打开 .dmg 不碰正在运行的 .app"
    assert uc.install_allowed("dev", "darwin") is False
    assert uc.install_allowed("installed", "win32") is True
    assert uc.install_allowed("portable", "win32") is False, "Windows 会被覆盖正在运行的自己"
    assert uc.install_allowed("dev", "win32") is False


def test_install_denied_reason_wording_per_platform():
    win = uc.install_denied_reason(platform="win32")
    mac = uc.install_denied_reason(platform="darwin")
    assert "便携版" in win
    assert "源码运行" in mac and "便携版" not in mac, "Mac 上没有便携版，别让用户去查本机不存在的东西"
    assert "覆盖正在运行的自己" in uc.install_denied_reason(short=True, platform="win32")
    assert "安装版" in uc.install_denied_reason(short=True, platform="darwin")


# ---------- macOS 系统代理 ----------

def _arm_scutil(monkeypatch, stdout="", rc=0, exc=None):
    def run(*args, **kwargs):
        if exc is not None:
            raise exc
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    monkeypatch.setattr(uc, "subprocess",
                        types.SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError))


def test_parse_scutil_proxy_is_line_split():
    text = ("HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7890\n"
            "ProxyAutoConfigURLString : http://pac.lan:8080/pac\n"
            "没有冒号的行\n: 空键\n\n")
    assert uc.parse_scutil_proxy(text) == {
        "HTTPEnable": "1", "HTTPProxy": "127.0.0.1", "HTTPPort": "7890",
        "ProxyAutoConfigURLString": "http://pac.lan:8080/pac"}
    assert uc.parse_scutil_proxy("") == {}


def test_mac_system_proxy_http(monkeypatch):
    _arm_scutil(monkeypatch, "HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7890\n")
    assert uc._mac_system_proxy() == ("http://127.0.0.1:7890", "")


def test_mac_system_proxy_https_wins(monkeypatch):
    _arm_scutil(monkeypatch, "HTTPEnable : 1\nHTTPProxy : 10.0.0.1\nHTTPPort : 8080\n"
                             "HTTPSEnable : 1\nHTTPSProxy : 10.0.0.2\nHTTPSPort : 8443\n")
    assert uc._mac_system_proxy() == ("http://10.0.0.2:8443", "")


def test_mac_system_proxy_disabled_says_so(monkeypatch):
    _arm_scutil(monkeypatch, "HTTPEnable : 0\n")
    assert uc._mac_system_proxy() == ("", "系统未启用代理")


def test_mac_system_proxy_pac_is_reported_not_parsed(monkeypatch):
    _arm_scutil(monkeypatch, "ProxyAutoConfigEnable : 1\n"
                             "ProxyAutoConfigURLString : http://pac.lan/pac\n")
    proxy, note = uc._mac_system_proxy()
    assert proxy == "" and "PAC" in note, "PAC 只报存在、不解析，拿不准就交回手填"


def test_mac_system_proxy_enabled_without_address(monkeypatch):
    _arm_scutil(monkeypatch, "HTTPEnable : 1\n")
    proxy, note = uc._mac_system_proxy()
    assert proxy == "" and "没有可用地址" in note


def test_mac_system_proxy_silent_on_error(monkeypatch):
    _arm_scutil(monkeypatch, exc=OSError("no scutil"))
    assert uc._mac_system_proxy() == ("", "")
    _arm_scutil(monkeypatch, "HTTPEnable : 1\nHTTPProxy : 1.2.3.4\nHTTPPort : 1\n", rc=1)
    assert uc._mac_system_proxy() == ("", "")


# ---------- 发布侧：清单回填只改本平台，不抹别人的包（scripts/build_release.py） ----------

def _pkg(tmp_path, name, payload=b"payload"):
    p = tmp_path / name
    p.write_bytes(payload)
    return str(p)


def _entry(tmp_path, data, kind):
    from scripts.build_release import build_manifest_entry
    return build_manifest_entry(
        data, version="99.0.0", base="https://github.com/o/r/releases/", kind=kind,
        installer_path=_pkg(tmp_path, "pkg.dmg" if kind == "dmg" else "pkg.exe"),
        portable=_pkg(tmp_path, "port.zip"))


def test_mac_manifest_backfill_keeps_the_windows_asset(tmp_path):
    """一份清单服务所有平台：mac 侧回填不许把 setup 从 assets 里抹掉"""
    prior = {"version": "0.20.1", "notes": "n", "sig": "s",
             "assets": {"setup": {"name": "QianBi-Novel-v0.20.1-setup.exe",
                                  "url": "https://x/setup.exe", "sha256": "aa" * 32,
                                  "size": 1}}}
    out = _entry(tmp_path, prior, "dmg")
    assert out["assets"]["setup"]["sha256"] == "aa" * 32, "mac 回填抹掉了 Windows 包"
    assert out["assets"]["dmg"]["name"].endswith(".dmg")
    assert out["assets"]["portable"]["name"].endswith("port.zip")
    assert out["notes"] == "n" and out["sig"] == "s", "notes/sig 是人写的，回填不许动"
    # 顶层 sha256 仍是老客户端会去校验的那份 setup 的哈希
    assert out["sha256"] == "aa" * 32


def test_windows_manifest_backfill_keeps_the_dmg_asset(tmp_path):
    prior = {"version": "0.20.1",
             "assets": {"dmg": {"name": "QianBi-Novel-v0.20.1-mac.dmg",
                                "url": "https://x/m.dmg", "sha256": "bb" * 32, "size": 2}}}
    out = _entry(tmp_path, prior, "setup")
    assert out["assets"]["dmg"]["sha256"] == "bb" * 32, "Windows 回填抹掉了 Mac 包"
    assert out["assets"]["setup"]["name"].endswith(".exe")
    # 顶层 sha256 = 本次 setup 的哈希（老客户端校验的就是它）
    from scripts.build_release import sha256
    assert out["sha256"] == sha256(_pkg(tmp_path, "pkg.exe"))


def test_mac_manifest_without_setup_never_forges_a_top_level_sha(tmp_path):
    """清单里没有 Windows 包时，不许拿 dmg 的哈希冒充顶层 sha256

    顶着 dmg 的哈希，老 Windows 客户端会拿它校验自己下的 exe，必然对不上——
    虽是安全失败，却把「这版没发 Windows 包」错报成「哈希坏了」。
    """
    out = _entry(tmp_path, {"version": "0.20.1"}, "dmg")
    assert "sha256" not in out, "没产 setup 却写了顶层 sha256（拿 dmg 哈希冒充）"
    assert set(out["assets"]) == {"dmg", "portable"}
