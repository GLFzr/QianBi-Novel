# -*- coding: utf-8 -*-
"""更新载荷的下载与校验（GUI-only，不进 dual_sync 共享层）

门在调用方：只有 `update_check.CheckResult.can_install`（清单验签通过 + 确实有更新）
才会走到这里；本模块自己再验一次，因为「谁调我」这件事迟早会被人改掉。

只认 sha256 命中，不认「下完了」：51MB 的包在墙外 CDN 上断在半路是常态，
半截文件的哈希不匹配就是没下完，不是坏了的更新源。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

from . import update_check as uc

logger = logging.getLogger("qianbi.update")

CHUNK = 1 << 16
TIMEOUT = 20.0


def asset_urls(manifest: dict, kind: str = "setup", mirror_prefix: str = "") -> list:
    """候选下载地址：官方直链 → 清单里作者签过名的镜像 → 用户自己配的镜像前缀

    顺序有意义——`mirror_prefix` 是用户填的陌生主机，排最后；它拼出来的字节照样要过
    sha256，所以「排在最后」只是省一次无谓的第三方流量，不是安全边界。
    """
    out = [u for u in uc.asset_url_list(manifest, kind) if uc.safe_asset_url(u)]
    seen = set(out)
    prefix = (mirror_prefix or "").strip()
    if prefix:
        name = uc.setup_download_name(manifest)
        cand = prefix if prefix.lower().endswith(".exe") else prefix.rstrip("/") + "/" + name
        if uc.safe_asset_url(cand) and cand not in seen:
            out.append(cand)
    return out


def download(url: str, dest: str, plan: uc.ProxyPlan, *, expected_sha: str = "",
             on_progress=None, cancelled=None, timeout: float = TIMEOUT,
             resume: bool = True) -> dict:
    """流式下载到 dest，边写边算 sha256（省一次 51MB 重读）

    返回 {"ok", "reason", "sha256", "path", "resumed"}。
    """
    result = {"ok": False, "reason": "", "sha256": "", "path": dest, "resumed": False}
    if uc.offline():
        result["reason"] = "已置 %s=1，本次不联网" % uc.OFFLINE_ENV
        return result
    h = hashlib.sha256()
    pos = 0
    mode = "wb"
    if resume and os.path.exists(dest):
        pos = os.path.getsize(dest)
        if pos:
            with open(dest, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            mode = "ab"
            result["resumed"] = True
    try:
        import httpx
        headers = {"Range": "bytes=%d-" % pos} if pos else {}
        with httpx.Client(proxy=plan.proxy or None, trust_env=plan.trust_env,
                          timeout=timeout, follow_redirects=True) as c:
            with c.stream("GET", url, headers=headers) as r:
                if r.status_code == 200 and pos:
                    pos, mode = 0, "wb"          # 服务端不认 Range：从头再来，别拼出半个文件
                    h = hashlib.sha256()
                    result["resumed"] = False
                elif r.status_code not in (200, 206):
                    result["reason"] = "HTTP %s" % r.status_code
                    return result
                total = pos + int(r.headers.get("Content-Length") or 0)
                with open(dest, mode) as f:
                    for chunk in r.iter_bytes(CHUNK):
                        if cancelled is not None and cancelled():
                            result["reason"] = "已取消（下次会从断点续传）"
                            result["sha256"] = h.hexdigest()
                            return result
                        f.write(chunk)
                        h.update(chunk)
                        pos += len(chunk)
                        if on_progress is not None:
                            on_progress(pos, total)
    except Exception as e:  # noqa: BLE001
        result["reason"] = uc.error_reason(e)
        result["sha256"] = h.hexdigest()
        return result
    result["sha256"] = h.hexdigest()
    if expected_sha and result["sha256"].lower() != expected_sha.strip().lower():
        result["reason"] = ("SHA-256 不匹配（清单 %s… / 实际 %s…）：下载被半路改写或没下完，"
                            "不会安装" % (expected_sha[:8], result["sha256"][:8]))
        return result
    if not expected_sha:
        result["reason"] = "清单没有给出 SHA-256，无法校验，不会安装"
        return result
    result["ok"] = True
    return result


def verify_local(path: str, expected_sha: str) -> dict:
    """离线包对账：用户自己下好的 exe，算哈希跟验签清单比"""
    out = {"ok": False, "path": path, "actual": "", "expected": expected_sha, "reason": ""}
    if not os.path.isfile(path):
        out["reason"] = "文件不存在"
        return out
    if not expected_sha:
        out["reason"] = "没有可对照的 SHA-256（清单未验签或未给出校验值）"
        return out
    try:
        out["actual"] = uc.sha256_file(path)
    except OSError as e:
        out["reason"] = "读不了这个文件：%s" % e
        return out
    if out["actual"].lower() != expected_sha.strip().lower():
        out["reason"] = "SHA-256 与验签清单不一致，不会安装"
        return out
    out["ok"] = True
    return out


def disk_space_ok(path: str, manifest: dict) -> bool:
    """下一半才发现盘满，等于给用户一个永远装不上的半截文件"""
    need = int(((manifest or {}).get("assets") or {}).get("setup", {}).get("size") or 0)
    if need <= 0:
        return True
    import shutil
    try:
        return shutil.disk_usage(os.path.dirname(path) or ".").free >= need
    except OSError:
        return True         # 问不出剩余空间就别拿它当理由拦用户，让下载自己面对失败


def stale_partial(dest: str, max_age: float = 6 * 3600.0) -> None:
    """清掉很久以前留下的半截文件：续传点过期了就让服务端重新给一份"""
    try:
        if os.path.isfile(dest) and time.time() - os.path.getmtime(dest) > max_age:
            os.remove(dest)
    except OSError:
        pass
