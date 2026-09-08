# -*- coding: utf-8 -*-
"""同字节重放探针：章界那一笔到底能不能命中深前缀？

背景（E1，看板 §5 20:35）：`t2_smoke2` 里第 22 章 prose 请求（319,686 tok）**逐字节**是
第 21 章末笔请求（308,996 tok）的纯追加，却只记到 hit=14,336（4.5%）；而 40-65 秒后
同一前缀链上的 enrich 记到 hit=307,200（95.8%）。深节点当时存在，prose 没被记上。

三种可能，本探针一次分辨（同一串字节、同一渠道、同一 user_id，只差请求参数）：
  A 路由/记账抖动      → 原样重放会命中深前缀（和 enrich 一样）
  B 参数进缓存键       → 换参数的那一发命中、原参数那一发仍不命中
  C 大请求+大新尾的形状  → 三种参数全都记不到深处（那就是形状问题，修法在请求结构）

用法（从既有 fake home 的会话栈里切前 N 条消息当请求）：
  python scripts/replay_request_probe.py --home t2_smoke2 --slice 136 --conn tr-dsv4f
  ... --reps 2         每种参数形状重复几遍（分辨 A 用）
用量：每发 ≈slice 的 tok 量级，多数按命中价计；单发实测几分钱量级。不落任何 usage.jsonl。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

BOOK = "种子书"


def _hit_miss(usage: dict) -> tuple:
    tin = int(usage.get("prompt_tokens", 0) or 0)
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
    if not hit and not miss:
        hit = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        miss = tin - hit
    return tin, hit, miss


def main() -> None:
    ap = argparse.ArgumentParser(description="同字节重放：分辨抖动/参数键/请求形状")
    ap.add_argument("--home", required=True, help="tests_output/bench 下的变体名（取其会话栈）")
    ap.add_argument("--proj", default="", help="工程目录（缺省 <home>/bench/种子书）")
    ap.add_argument("--volume", default="", help="卷文件名（缺省取最大卷号）")
    ap.add_argument("--slice", type=int, default=136, help="取前 N 条消息作请求（含 system）")
    ap.add_argument("--conn", default="tr-dsv4f")
    ap.add_argument("--reps", type=int, default=1, help="每种形状重复次数")
    ap.add_argument("--model", default="", help="显式覆盖模型名（缺省按 --conn 解析）")
    a = ap.parse_args()

    proj = a.proj or os.path.join(ROOT, "tests_output", "bench", a.home, "bench", BOOK)
    sess = os.path.join(proj, "会话")
    cands = sorted(f for f in os.listdir(sess) if f.endswith("_messages.jsonl"))
    if not cands:
        raise SystemExit("没有会话栈：%s" % sess)
    fn = a.volume if a.volume.endswith(".jsonl") else (
        a.volume + "_messages.jsonl") if a.volume else cands[-1]
    msgs = []
    with open(os.path.join(sess, fn), encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                m = json.loads(ln)
                msgs.append({"role": m["role"], "content": m["content"]})
    req = msgs[:a.slice]
    if len(req) < a.slice:
        raise SystemExit("栈只有 %d 条，切不到 %d" % (len(req), a.slice))
    chars = sum(len(m["content"]) for m in req)
    print("栈 %s 共 %d 条，取前 %d 条（%s 字）重放"
          % (fn, len(msgs), len(req), format(chars, ",")))

    from cost_bench import _load_key
    conn, _pro = _load_key(prefer_id=a.conn)
    model = a.model or conn["model"]
    base = conn["base"].rstrip("/")
    headers = {"Authorization": "Bearer %s" % conn["key"], "Content-Type": "application/json"}
    print("渠道 %s @ %s ｜user 字段=%s\n" % (model, base, conn.get("user_id") or "(未设)"))

    shapes = [
        ("原样(不带 thinking)", {}),
        ("thinking=enabled+effort:high", {"thinking": {"type": "enabled"},
                                          "reasoning_effort": "high"}),
        ("thinking=disabled", {"thinking": {"type": "disabled"}}),
    ]
    rows = []
    with httpx.Client(timeout=600.0) as hx:
        for rep in range(a.reps):
            for tag, extra in shapes:
                payload = {"model": model, "messages": req, "stream": False,
                           "max_tokens": 16, "temperature": 0.7}
                payload.update(extra)
                t0 = time.time()
                r = hx.post(base + "/chat/completions", headers=headers, json=payload)
                if r.status_code != 200:
                    print("  %-28s HTTP %s %s" % (tag, r.status_code, r.text[:80]))
                    continue
                tin, hit, miss = _hit_miss(r.json().get("usage") or {})
                rows.append({"rep": rep + 1, "shape": tag, "in": tin, "hit": hit,
                             "miss": miss, "lat": round(time.time() - t0, 1)})
                print("  %-28s in=%-9s hit=%-9s (%5.1f%%) miss=%-9s %5.1fs"
                      % (tag, format(tin, ","), format(hit, ","),
                         100.0 * hit / max(1, tin), format(miss, ","), time.time() - t0))
    print("\n判读：与实跑记到的 hit=14,336 对照——"
          "\n  任一发记到 ~300k ⇒ 参数不在缓存键里，实跑那发是记账/路由抖动（A）；"
          "\n  三发都趴在 14k 附近 ⇒ 是这个请求形状本身（C），要改的是请求结构不是参数。")
    out = os.path.join(ROOT, "tests_output", "probe_replay_%s.json"
                       % time.strftime("%Y%m%d_%H%M"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"home": a.home, "stack": fn, "slice": len(req), "model": model,
                   "rows": rows}, f, ensure_ascii=False, indent=1)
    print("→", out)


if __name__ == "__main__":
    main()
