# -*- coding: utf-8 -*-
"""三通道清单一致性校验（M-CI，发版日/手动 CI 跑）

对 raw / GitHub Pages / jsDelivr 三条通道拉取 latest.json，与仓库根的本地清单做
逐字节（canonical 序列化）比对，并可对安装包做真哈希对账。裁决规则
（docs/落地计划附录C §4.3 口径）：

    raw vs Pages vs 本地逐字节一致          = PASS
    jsDelivr 版本一致                       = PASS
    jsDelivr 旧版（落后）                   = PASS + WARN（s-maxage=43200，≤12h 追平；
                                              清单带签名，滞后的镜像只会少报不会乱报）
    jsDelivr 新版 / 同版本但内容被改写       = FAIL
    Pages 与 raw/本地不一致                  = FAIL（Pages 一两分钟内就该追平）
    Pages 整条拉不到（404）                  = PASS + WARN（Pages 属发布窗口动作，
                                              checklist §5 未打勾前 404 是已知的诚实现状；
                                              但**拉到了却不一致**仍然是 FAIL）
    raw 整条拉不到                          = FAIL（发布生效判定的基准通道）
    顶层 sha256 与 assets.setup.sha256 不等  = FAIL（老客户端核对的双写契约断裂）
    安装包哈希 ≠ 清单声明                     = FAIL

网络：urllib + ProxyHandler({}) **直连**——本脚本的职责就是核对公网真实状态，
环境变量里的代理（常常指向本机调试端口）只会污染结论。
CI：.github/workflows/tests.yml 的 release-consistency job（workflow_dispatch 手动
触发，不随 push/PR 跑网络）。退出码：有 FAIL=1，否则 0（WARN 不红）。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 直连 opener：ProxyHandler({}) 显式清空代理表，不读 http_proxy 等环境变量
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = {"User-Agent": "qianbi-release-consistency"}

OK, WARN, FAIL = "OK", "WARN", "FAIL"
CHANNELS = ("raw", "pages", "jsdelivr")


# ---------- 纯函数（单测面） ----------

def canonical_bytes(data: dict) -> bytes:
    """签名作用域同款序列化（与 app.update_check.canonical_bytes 逐字节同源）：
    去 sig、键序固定、无空白。通道间格式化差异不算漂移，语义差异才算。"""
    body = {k: v for k, v in (data or {}).items() if k != "sig"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def parse_ver(v: str) -> tuple:
    nums = re.findall(r"\d+", (v or "").strip())
    return tuple(int(x) for x in nums[:3]) if nums else (0,)


def parse_manifest(raw: bytes) -> tuple:
    """(dict|None, err) —— 结构不合法到此为止"""
    try:
        data = json.loads((raw or b"").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return (None, "不是合法 JSON（%s）" % type(e).__name__)
    if not isinstance(data, dict) or not str(data.get("version") or "").strip():
        return (None, "清单里没有 version 字段")
    return (data, "")


def dual_write_ok(data: dict) -> bool:
    """顶层兼容字段与 assets.setup.* 双写一致（v0.15~0.17 老客户端的核对契约）"""
    m = data or {}
    setup = (m.get("assets") or {}).get("setup") or {}
    top_sha = str(m.get("sha256") or "").strip().lower()
    setup_sha = str(setup.get("sha256") or "").strip().lower()
    if not top_sha or top_sha != setup_sha:
        return False
    url = str(m.get("url") or "")
    return bool(setup.get("url")) and str(m.get("version") or "") in url


def _diff_keys(a: dict, b: dict) -> str:
    ka = set(a or {})
    kb = set(b or {})
    changed = sorted(k for k in ka & kb if (a.get(k) != b.get(k)) and k != "sig")
    return "/".join(changed + sorted(ka ^ kb)) or "(仅 sig 不同)"


def judge(local: dict, results: dict) -> tuple:
    """裁决核心（纯函数，零网络）。

    local：仓库根 latest.json 的 dict（没有则 None）
    results：{通道名: (dict|None, err)}，通道 ∈ CHANNELS
    返回 (level, findings, rows)；findings 是 (level, msg)，rows 供打表。
    """
    findings = []
    rows = []

    def add(level, msg):
        findings.append((level, msg))

    for name in CHANNELS:
        data, err = results.get(name, (None, "没有结果"))
        if data is None:
            # raw 是「发布是否生效」的判定基准，缺席即红；Pages/jsDelivr 拉不到只判
            # WARN（Pages 未发布/checklist §5 未打勾前 404 是已知现状；CDN 缓存同理）——
            # 但**拉到了却不一致**仍然是 FAIL，缺席≠分歧。
            add(FAIL if name == "raw" else WARN,
                "%s 通道拉不到清单：%s" % (name, err))
        rows.append((name, data))

    base = local
    if base is None:
        for name in CHANNELS:
            d = results.get(name, (None, ""))[0]
            if d is not None:
                base = d
                break
    if base is None:
        add(FAIL, "本地清单缺失且三通道全拉不到，无法判定一致性")
        return (FAIL, findings, rows)

    # 双写契约逐份核对（含本地）
    for label, data in [("本地", local)] + [(n, results.get(n, (None, ""))[0])
                                            for n in CHANNELS]:
        if data is not None and not dual_write_ok(data):
            add(FAIL, "%s 清单顶层 sha256 与 assets.setup.sha256 双写断裂（老客户端会拿到对不上的组合）" % label)

    base_ver = str(base.get("version") or "")
    base_canon = canonical_bytes(base)
    for name in CHANNELS:
        data, _err = results.get(name, (None, ""))
        if data is None:
            continue
        ver = str(data.get("version") or "")
        if canonical_bytes(data) == base_canon:
            continue
        if parse_ver(ver) < parse_ver(base_ver):
            # 只有「整版落后」允许 WARN，且仅限 jsDelivr（已知的缓存延迟）
            if name == "jsdelivr":
                add(WARN, "jsDelivr 滞后：%s 落后于 %s（缓存 s-maxage=43200，≤12h 追平；"
                          "只会少报不会乱报，别拿它判断发没发布）" % (ver or "?", base_ver))
            else:
                add(FAIL, "%s 清单版本 %s 落后于基准 %s" % (name, ver or "?", base_ver))
        elif ver != base_ver:
            add(FAIL, "%s 清单版本 %s 比基准 %s 还新（发布状态错乱）" % (name, ver or "?", base_ver))
        else:
            add(FAIL, "%s 清单与基准同版本（%s）但内容不一致：改动字段 %s"
                      % (name, base_ver, _diff_keys(base, data)))
    worst = FAIL if any(lv == FAIL for lv, _ in findings) else (
        WARN if any(lv == WARN for lv, _ in findings) else OK)
    return (worst, findings, rows)


# ---------- 网络（只在 main 跑） ----------

def channel_urls() -> list:
    """三条派生通道——与客户端同源（app.update_check.channels），避免第三处手写 URL"""
    try:
        sys.path.insert(0, ROOT)
        from app import config as cfg_mod
        from app import update_check as uc
        return [(k, u) for k, u in uc.channels(cfg_mod.DEFAULT_CONFIG)
                if k in CHANNELS]
    except Exception as e:  # noqa: BLE001
        print("[WARN] 派生通道失败（app 导入不了？）：%s" % e)
        return []


def fetch_url(url: str, timeout: float = 30.0) -> tuple:
    """(bytes|None, err) —— 直连（OPENER 已清空代理表）"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with OPENER.open(req, timeout=timeout) as r:
            return (r.read(), "")
    except Exception as e:  # noqa: BLE001
        return (None, "%s: %s" % (type(e).__name__, e))


def fetch_asset_sha(url: str, timeout: float = 600.0, retries: int = 1) -> tuple:
    """流式下载安装包并算 sha256 —— (hexdigest|None, size|None, err)；失败重试一次"""
    err = ""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            h = hashlib.sha256()
            size = 0
            with OPENER.open(req, timeout=timeout) as r:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    h.update(block)
                    size += len(block)
            return (h.hexdigest(), size, "")
        except Exception as e:  # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
    return (None, None, err)


# ---------- main ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="三通道 latest.json 一致性校验（M-CI）")
    ap.add_argument("--no-asset", action="store_true",
                    help="跳过安装包下载（只比清单；发版日默认全量对账）")
    args = ap.parse_args(argv)

    local = None
    local_path = os.path.join(ROOT, "latest.json")
    if os.path.exists(local_path):
        with open(local_path, "rb") as f:
            local, bad = parse_manifest(f.read())
            if local is None:
                print("[FAIL] 仓库根 latest.json 读不懂：%s" % bad)

    urls = channel_urls()
    if not urls:
        print("[FAIL] 拼不出任何通道 URL——检查 app/config 的出厂 manifest_url")
        return 1
    results = {}
    print("=== 三通道清单比对（直连，不走环境代理）===", flush=True)
    print("%-9s %-8s %-16s %-14s %-12s %s" % ("通道", "状态", "版本", "sha256[:12]", "大小", "备注"))
    for name, url in urls:
        raw, err = fetch_url(url)
        data, perr = (None, err) if raw is None else parse_manifest(raw)
        results[name] = (data, perr)
        if data is None:
            print("%-9s %-8s %-16s %-14s %-12s %s"
                  % (name, "DOWN", "-", "-", "-", perr))
            continue
        setup = (data.get("assets") or {}).get("setup") or {}
        print("%-9s %-8s %-16s %-14s %-12s %s"
              % (name, "ok", data.get("version"), str(data.get("sha256") or "")[:12],
                 _fmt_size(setup.get("size")), url))

    level, findings, rows = judge(local, results)

    # 安装包真哈希对账：以 raw（判定通道）声明的地址为准
    asset_findings = []

    def add_asset(lv, msg):
        asset_findings.append((lv, msg))

    raw_data = results.get("raw", (None, ""))[0] or local
    if args.no_asset:
        print("[SKIP] --no-asset：未下载安装包做哈希对账")
    elif raw_data:
        setup = (raw_data.get("assets") or {}).get("setup") or {}
        url = str(setup.get("url") or "")
        declared = str(setup.get("sha256") or "").strip().lower()
        print("=== 安装包对账：%s（%.1f MB）===" % (url, (setup.get("size") or 0) / 1048576),
              flush=True)
        got, size, err = fetch_asset_sha(url)
        if got is None:
            add_asset(FAIL, "安装包下载失败：%s（--no-asset 可跳过本段）" % err)
        else:
            ok_sha = (got == declared) if declared else False
            ok_size = (str(setup.get("size") or "") == "" or size == int(setup.get("size")))
            print("  sha256 %s（声明 %s）" % (got[:12], declared[:12] or "无"))
            print("  size   %d（声明 %s）" % (size, setup.get("size") or "?"))
            if declared and not ok_sha:
                add_asset(FAIL, "安装包哈希与清单声明不一致：清单 %s… / 实际 %s…"
                                % (declared[:12], got[:12]))
            elif not declared:
                add_asset(FAIL, "清单没有给出安装包 sha256，无从对账")
            if not ok_size:
                add_asset(FAIL, "安装包大小与清单声明不一致")
    else:
        print("[SKIP] 没有 raw 清单可提供安装包地址")

    for lv, msg in asset_findings:
        findings.append((lv, msg))
    if any(lv == FAIL for lv, _ in asset_findings):
        level = FAIL
    elif level == OK and any(lv == WARN for lv, _ in asset_findings):
        level = WARN

    print("=== 裁决：%s ===" % level)
    for lv, msg in findings:
        print("[%s] %s" % (lv, msg))
    if level == OK:
        print("PASS：三通道清单与安装包一致")
    return 1 if level == FAIL else 0


def _fmt_size(n) -> str:
    try:
        return "%.1fMB" % (int(n) / 1048576)
    except (TypeError, ValueError):
        return "-"


if __name__ == "__main__":
    sys.exit(main())
