# -*- coding: utf-8 -*-
"""内置镜像表与无代理自动换源（v0.18.5）"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import update_mirrors as um
from app.update_check import ProxyPlan


GH = "https://github.com/GLFzr/QianBi-Novel/releases/download/v0.18.5/QianBi-Novel-v0.18.5-setup.exe"


def _manifest():
    return {"version": "0.18.5",
            "url": GH,
            "assets": {"setup": {"url": GH, "sha256": "ab" * 32, "name": "QianBi-Novel-v0.18.5-setup.exe"}}}


# ---------- proxy_in_use：实事求是地判定「这次下载走不走代理」 ----------

def test_proxy_in_use_when_plan_has_proxy():
    assert um.proxy_in_use(ProxyPlan(proxy="http://127.0.0.1:7890"))


def test_proxy_in_use_env_vars_count(monkeypatch):
    plan = ProxyPlan(trust_env=True)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    assert not um.proxy_in_use(plan)          # trust_env 但环境里真没有 → 无代理
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    assert um.proxy_in_use(plan)


def test_proxy_in_use_none_mode_never():
    assert not um.proxy_in_use(ProxyPlan(trust_env=False))


# ---------- ordered_urls：无代理时主镜像置顶，其余兜底；不做逐个试探 ----------

def test_no_proxy_puts_primary_mirror_first():
    urls, via = um.ordered_urls(_manifest(), "setup", "", {}, ProxyPlan(trust_env=False))
    p = um.primary()
    assert urls[0] == p["prefix"] + GH
    assert urls[1] == GH                       # 官方直链殿后兜底
    assert urls.index(GH) < len(urls) - 1
    assert "未检测到代理" in via and p["name"] in via


def test_with_proxy_keeps_official_first(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    urls, via = um.ordered_urls(_manifest(), "setup", "", {}, ProxyPlan(trust_env=True))
    assert urls[0] == GH
    assert via == ""


def test_mirror_off_never_prepends():
    cfg = {"updates": {"mirror": "off"}}
    urls, via = um.ordered_urls(_manifest(), "setup", "", cfg, ProxyPlan(trust_env=False))
    assert urls[0] == GH and via == ""


def test_user_mirror_prefix_still_last():
    urls, _ = um.ordered_urls(_manifest(), "setup", "https://my.lan/mirror/", {},
                              ProxyPlan(trust_env=False))
    assert urls[-1].startswith("https://my.lan/mirror/")


def test_non_github_official_skips_mirror():
    m = _manifest()
    m["assets"]["setup"]["url"] = "https://cdn.example.com/pkg.exe"
    urls, via = um.ordered_urls(m, "setup", "", {}, ProxyPlan(trust_env=False))
    assert urls[0].startswith("https://cdn.example.com/") and via == ""


# ---------- mirror_url 的卫生 ----------

def test_mirror_url_requires_https_prefix():
    assert um.mirror_url("http://evil.example/", GH) == ""
    assert um.mirror_url("https://gh-proxy.com", GH).endswith(GH)      # 自动补尾斜杠
    assert um.mirror_url("https://gh-proxy.com/", "https://gitlab.com/x/y") == ""


def test_primary_exists_and_https():
    p = um.primary()
    assert p["id"] == "gh-proxy" and p["prefix"].startswith("https://")
    assert len(um.MIRRORS) >= 3
