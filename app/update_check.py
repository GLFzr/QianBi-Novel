# -*- coding: utf-8 -*-
"""应用内检查更新（v1：提示 + 跳转/下载，不静默安装）

- 版本清单 JSON（GitHub Releases 主通道，URL 可配置）：
  {"version": "0.15.0", "url": "https://...下载页或安装包直链", "notes": "...", "sha256": "..."}
- is_newer：按点分数字逐段比较（非严格 semver，容忍 0.14 / 0.14.0 混写）
- 网络失败一律静默（手动检查时由调用方提示）
"""
import logging
import re

logger = logging.getLogger("qianbi.update")


def parse_ver(v: str) -> tuple:
    nums = re.findall(r"\d+", (v or "").strip())
    return tuple(int(x) for x in nums[:3]) if nums else (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_ver(remote) > parse_ver(local)


def fetch_manifest(url: str, timeout: float = 10.0) -> dict | None:
    """拉取版本清单；任何异常返回 None（调用方决定是否提示）"""
    if not url:
        return None
    try:
        import httpx
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200:
            logger.info("更新清单 HTTP %s（未发布或网络不可达，静默）", resp.status_code)
            return None
        data = resp.json()
        if not isinstance(data, dict) or not data.get("version"):
            return None
        return data
    except Exception as e:  # noqa: BLE001
        logger.info("更新检查失败（静默）: %s", e)
        return None


def check(manifest_url: str, local_version: str, timeout: float = 10.0) -> dict | None:
    """返回新版信息 dict（version/url/notes/sha256），无新版或失败返回 None"""
    manifest = fetch_manifest(manifest_url, timeout)
    if not manifest:
        return None
    if is_newer(str(manifest.get("version", "")), local_version):
        return manifest
    return None
