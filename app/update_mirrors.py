# -*- coding: utf-8 -*-
"""GitHub 发布包镜像（GUI-only，不进 dual_sync 共享层）

为什么要有这张表：Release 资产 53MB 走 github.com 直连，没挂代理的国内用户
经常「下一半被重置」。清单通道（raw/jsDelivr/Pages）只解决 1KB 的 latest.json，
解决不了大文件。镜像站=URL 前缀反代，`前缀 + 官方完整 URL` 即可下载，
字节照样过清单里的 SHA-256——镜像只影响「下得快不快」，不影响「下到的是不是作者发的」。

纪律（对应需求原话「不用一个一个试」）：
- 判定**无代理**时，确定性选一张主镜像放在候选位第一，其余来源（官方直链/清单
  镜像/用户自填）顺序殿后作为失败兜底——不是把镜像表挨个试一遍。
- 表是代码内置的：换主镜像=发一版应用；清单里的 `assets.setup.mirrors` 是作者
  签名的运行期补充（应急轮换不用等发版），两条腿都有。
- 表内地址 2026-09-06 逐一实测（无代理直连 + Range 206 + 2MB 采样 + 53.5MB
  整包 sha256 对账通过 gh-proxy.com），速度序与稳定性加权后定序。
"""
from __future__ import annotations

import os

from . import update_check as uc
from . import update_install as ui

# 实测排序（2026-09-06，无代理直连 2MB 采样）：
#   gh-proxy.com 1.11MB/s · ghfast.top 0.20MB/s · ghproxy.net 0.77MB/s ·
#   gh.zwy.one 1.26MB/s · ghproxy.cxkpro.top 1.14MB/s
# 主镜像选 gh-proxy.com：速度第一梯队且为长期运营的大站；zwy/cxkpro 虽快但属
# 个人/社区源，耐久性存疑，殿后作清单 mirrors 与换代表备选。
MIRRORS: list[dict] = [
    {"id": "gh-proxy", "prefix": "https://gh-proxy.com/", "name": "gh-proxy 镜像"},
    {"id": "ghfast", "prefix": "https://ghfast.top/", "name": "ghfast 镜像"},
    {"id": "ghproxy-net", "prefix": "https://ghproxy.net/", "name": "ghproxy.net 镜像"},
    {"id": "zwy", "prefix": "https://gh.zwy.one/", "name": "zwy 镜像"},
    {"id": "cxkpro", "prefix": "https://ghproxy.cxkpro.top/", "name": "cxkpro 镜像"},
]
PRIMARY_ID = "gh-proxy"

_ENV_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


def is_github_asset_url(url: str) -> bool:
    """只给 github.com 的 release 资产挂镜像——镜像前缀拼在别的域上语义不明"""
    u = (url or "").strip()
    return u.startswith("https://github.com/") and "/releases/download/" in u


def mirror_url(prefix: str, url: str) -> str:
    """前缀 + 官方 URL；前缀必须 https 且以 / 结尾（拼出来不是合法 https 就返回空串）"""
    p = (prefix or "").strip()
    u = (url or "").strip()
    if not p or not u or not uc.is_https_url(p):
        return ""
    if not p.endswith("/"):
        p += "/"
    cand = p + u
    return cand if uc.is_https_url(cand) and is_github_asset_url(u) else ""


def primary() -> dict:
    for m in MIRRORS:
        if m["id"] == PRIMARY_ID:
            return m
    return MIRRORS[0] if MIRRORS else {"id": "", "prefix": "", "name": ""}


def proxy_in_use(plan) -> bool:
    """这次下载会不会走代理——resolve_proxy 结果 + 环境变量的实事求实

    trust_env=True 只代表「允许 httpx 看环境变量」，环境变量里真的有代理才算数；
    否则「没挂代理的用户」会被误判成「有代理」，镜像永远轮不上。
    """
    if plan is None:
        return False
    if plan.proxy:
        return True
    if not plan.trust_env:
        return False
    return any(os.environ.get(v) for v in _ENV_PROXY_VARS)


def mirror_enabled(cfg: dict) -> bool:
    """updates.mirror: auto（默认，无代理时启用）| off（永不使用内置镜像）"""
    return str(((cfg or {}).get("updates") or {}).get("mirror") or "auto").strip().lower() != "off"


def ordered_urls(manifest: dict, kind: str, mirror_prefix: str,
                 cfg: dict, plan) -> tuple:
    """(有序候选下载地址, 经镜像提示文案)

    有代理：官方直链优先（现状不变，镜像无增益）。
    无代理：主镜像前缀的官方直链提到第一，官方直链与清单/用户镜像殿后兜底——
    失败一次就能续传换源（同一文件同一字节，跨源 Range 续传成立）。
    """
    urls = ui.asset_urls(manifest, kind, mirror_prefix)
    official = urls[0] if urls else ""
    via = ""
    if (mirror_enabled(cfg) and official and is_github_asset_url(official)
            and not proxy_in_use(plan)):
        m = primary()
        cand = mirror_url(m.get("prefix", ""), official)
        if cand:
            urls = [cand] + [u for u in urls if u != cand]
            via = "未检测到代理，已从%s加速下载" % m.get("name", "镜像站")
    return urls, via
