# -*- coding: utf-8 -*-
"""更新载荷的下载与校验（GUI-only）

门在调用方：只有 `update_check.CheckResult.can_install`（清单验签通过 + 确实有更新）
才会走到这里；本模块自己再验一次，因为「谁调我」这件事迟早会被人改掉。

只认 sha256 命中，不认「下完了」：51MB 的包在墙外 CDN 上断在半路是常态，
半截文件的哈希不匹配就是没下完，不是坏了的更新源。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
        if uc.is_http_url(cand) and cand not in seen:
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
        result["reason"] = uc.error_reason(e, plan.proxy)
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


# U-C：旧安装包保留策略（当前+上一版，更早删除）
_VER_IN_NAME = re.compile(r"v(\d+(?:\.\d+){1,2})", re.IGNORECASE)


def prune_old_installers(directory: str, current_version: str = None,
                         keep: int = 2) -> dict:
    """updates/ 目录的旧安装包清理：保留当前版+上一版（共 keep 份），更早的删掉

    一份 setup 51MB，下载新版成功后调用方（bridge.installUpdateNow，接线归
    B8b/U-A 轮——本轮只交付函数与单测）拿落盘目录调这里，用户不该手动管磁盘。

    只删「确定是更老的安装包」的东西：
    - 文件名解析不出版本段（`v<数字[.数字]>`）→ 跳过不动，绝不顺手删文件；
    - 版本比 current_version 还新（时钟错乱/手动放置）→ 跳过不动；
    - 其余按版本从新到旧保留 keep 份（current_version 那份必在其中）。
    current_version 缺省取 app.__version__（单测 monkeypatch 它验证缺省路径）。
    返回 {"deleted"/"kept"/"skipped": [路径或文件名…]}，全路径便于上层回执。
    """
    if current_version is None:
        from . import __version__ as current_version
    report = {"deleted": [], "kept": [], "skipped": []}
    try:
        names = sorted(n for n in os.listdir(directory)
                       if n.lower().endswith(".exe"))
    except OSError as e:
        report["skipped"].append("%s（%s）" % (directory, e))
        return report
    cur = uc.parse_ver(current_version)
    scored = []
    for n in names:
        m = _VER_IN_NAME.search(n)
        if not m:
            report["skipped"].append(n)
            continue
        v = uc.parse_ver(m.group(1))
        if v > cur:
            report["skipped"].append(n)   # 比当前还新：不是「旧安装包」，清理无权动它
            continue
        scored.append((v, n))
    scored.sort(key=lambda x: x[0], reverse=True)
    keep = max(int(keep), 0)
    for _v, n in scored[:keep]:
        report["kept"].append(os.path.join(directory, n))
    for _v, n in scored[keep:]:
        p = os.path.join(directory, n)
        try:
            os.remove(p)
            report["deleted"].append(p)
        except OSError as e:
            report["skipped"].append("%s（%s）" % (n, e))
    return report


# ---------- C19/U-A：静默安装的 journal × 完成标记 ----------
#
# 编排三方分工（w5_update.md §2.2，不引入常驻第三方进程）：
#   app 写意向日志（journal，installUpdateNow 在拉起安装器**之前**落盘）；
#   Inno 写完成标记（marker，installer.iss [Code] CurStepChanged ssPostInstall）；
#   启动逻辑对账（app/main.py，journal × marker 两态）。
# journal/marker 是更新域的落盘物，路径常量寄居本模块——既有数据目录 helper
# （uc.updates_dir/uc.install_dir）全复用，config.py 本轮归 S4b 在途不加新键；
# TODO(收口批/B8b)：随 Updates 域搬迁时整体平移进 UpdatesMixin 的领地。
JOURNAL_NAME = "update_journal.json"   # 待更新意向：~/.qianbi_novel/updates/ 下
MARKER_NAME = ".update_done"           # 装完标记：跟着程序目录走


def journal_path() -> str:
    return os.path.join(uc.updates_dir(), JOURNAL_NAME)


def marker_path(base_dir: str = "") -> str:
    return os.path.join(base_dir or uc.install_dir(), MARKER_NAME)


def write_journal(to_version: str, pkg_path: str, from_version: str = "") -> dict:
    """拉起安装器前落盘的「待更新」意向；先写临时文件再 replace，断电不留半份

    记录 from/to 版本、安装包路径（排障与「引导手动安装」都靠它指路）与时间戳
    （R3 回滚卡用它判「更新后首启崩溃」）。写失败由调用方决定去留——bridge 侧
    的取舍是继续装（最坏是这次安装没人对账，不比放弃升级差）。
    """
    if not from_version:
        from . import __version__ as from_version
    entry = {"from": str(from_version), "to": str(to_version or ""),
             "pkg": str(pkg_path or ""), "ts": time.time(), "phase": "launching"}
    path = journal_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entry, f, ensure_ascii=False)
    os.replace(tmp, path)
    return entry


def read_journal() -> dict:
    """读不到/读坏都返回 {}：journal 只是意向，坏了不能挡正常启动"""
    try:
        with open(journal_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def clear_journal() -> None:
    try:
        os.remove(journal_path())
    except OSError:
        pass


def read_marker_text(path: str = "") -> str:
    """marker 内容（`v<版本> <时间戳>`）；空串 = 没有 marker = 安装器没跑完"""
    try:
        with open(path or marker_path(), encoding="utf-8", errors="replace") as f:
            return f.read(256).strip()
    except OSError:
        return ""


def reconcile_update(journal: dict, marker_text: str) -> dict:
    """journal × marker 两态对账（纯判定；IO 由调用方做，好测）

    - journal 缺 → {"state": "none"}：上次没在装更新，什么都不用做；
    - journal + marker → {"state": "clear"}：安装器跑完了，清 journal 正常启动
      （marker 里带的版本随行返回，给「已更新到 vX」的 toast 用）；
    - journal 而 marker 缺 → {"state": "notify"}：安装器被杀软截杀/中途失败/断电
      （U-3/U-4）——journal **保留**（下次启动继续提醒、供排障），指向安装包
      引导手动安装；包不在了就退回 updates/ 目录（旧安装包的保留策略归 U-C）。
    marker 在而版本与 journal.to 不符的细分（比如用户手动重装了旧版）归 R3
    回滚卡，本态按「装完了」处理。
    """
    if not journal:
        return {"state": "none"}
    if marker_text:
        return {"state": "clear", "to": str(journal.get("to") or marker_text),
                "marker": marker_text}
    pkg = str(journal.get("pkg") or "")
    if pkg and not os.path.isfile(pkg):
        pkg = ""
    return {"state": "notify", "pkg": pkg, "updates_dir": uc.updates_dir()}
