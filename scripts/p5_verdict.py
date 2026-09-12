# -*- coding: utf-8 -*-
"""P5 收车判定工具（v16 3.2/5.5 预注册判据的机械化）

口径：综合命中率 = hit ÷（hit+miss+out），usage.jsonl 逐行按章聚合。
判据：
  1. 主判据：稳态窗（ch34-56，剔除每卷首 2 章）连续 ≥20 章中 ≥19 章综合 ≥95%，
     且全程塌陷（单章较前章 -5pt）在归因协议外 = 0；
  2. 机制判据：audit ≤1.5 笔/章、audit thinking disabled、快速道触发率 ≥50%、
     corpus_rolled 零违例；
  3. 并行如实报告：全窗累计综合、稳态窗均值。
冷击归因协议（单章跌幅 ≥5pt 时逐条核对）：in 尺寸正常 / 无结构事件 / 次章恢复 /
全跑限 1 次。

用法：python scripts/p5_verdict.py --usage <usage.jsonl> [--events <session_events.jsonl>]
退出码：0=达标；1=未达标。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

STEADY_START, STEADY_END = 34, 56
VOLUME_HEADS = {38, 47}          # 卷首章（卷四 38-46、卷五 47-56）
HEADS_PER_VOLUME = 2             # 每卷剔除首 2 章
GATE_RATE = 95.0
GATE_MIN_CHAPTERS = 19
COLLAPSE_PT = 5.0
AUDIT_MAX_PER_CH = 1.5
FAST_MIN_RATE = 0.5


def _load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser(description="P5 收车判定（预注册判据机械化）")
    ap.add_argument("--usage", required=True)
    ap.add_argument("--events", default="")
    ap.add_argument("--fast-log", default="", help="run 日志（数快速道行）")
    args = ap.parse_args()

    rows = _load(args.usage)
    by_ch = defaultdict(lambda: {"hit": 0, "miss": 0, "out": 0, "calls": 0})
    audit_by_ch = defaultdict(int)
    audit_disabled = True
    for r in rows:
        ch = r.get("ch") or 0
        b = by_ch[ch]
        b["hit"] += r.get("hit", 0)
        b["miss"] += r.get("miss", 0)
        b["out"] += r.get("out", 0)
        b["calls"] += 1
        if r.get("phase") == "canon_audit":
            audit_by_ch[ch] += 1
            sent = r.get("sent") or {}
            th = sent.get("thinking")
            th_type = th.get("type") if isinstance(th, dict) else ""
            if th_type != "disabled":
                audit_disabled = False

    chs = sorted(ch for ch in by_ch if ch >= STEADY_START)
    if not chs:
        print("[错误] usage 中无 ≥%d 章数据" % STEADY_START)
        return 2
    rates = {}
    for ch in chs:
        b = by_ch[ch]
        tot = b["hit"] + b["miss"] + b["out"]
        rates[ch] = 100.0 * b["hit"] / tot if tot else 0.0

    # 稳态窗：剔除每卷首 2 章
    skip = set()
    for head in sorted(VOLUME_HEADS):
        for c in range(head, head + HEADS_PER_VOLUME):
            skip.add(c)
    steady = [c for c in chs if c not in skip]
    n_ok = sum(1 for c in steady if rates[c] >= GATE_RATE)

    # 塌陷
    collapses = []
    for i in range(1, len(chs)):
        prev, cur = chs[i - 1], chs[i]
        if prev + 1 == cur and rates[prev] - rates[cur] >= COLLAPSE_PT:
            collapses.append((cur, round(rates[prev] - rates[cur], 1)))

    # 机制判据
    audited = [c for c in chs if audit_by_ch.get(c)]
    audit_per_ch = sum(audit_by_ch.get(c, 0) for c in chs) / max(len(chs), 1)
    fast_lines = 0
    if args.fast_log and os.path.isfile(args.fast_log):
        with open(args.fast_log, encoding="utf-8", errors="replace") as f:
            fast_lines = sum(1 for l in f if "PASS 快速道" in l)
    fast_rate = fast_lines / max(len(chs), 1)
    rolled_violated = 0
    if args.events and os.path.isfile(args.events):
        for e in _load(args.events):
            if e.get("event") == "corpus_rolled" and e.get("violated"):
                rolled_violated += 1

    tot_hit = sum(by_ch[c]["hit"] for c in chs)
    tot_miss = sum(by_ch[c]["miss"] for c in chs)
    tot_out = sum(by_ch[c]["out"] for c in chs)

    print("=== P5 收车判定 ===")
    print("窗口：%d-%d（%d 章）｜稳态样本 %d（剔除卷首章 %s）"
          % (chs[0], chs[-1], len(chs), len(steady),
             ",".join(map(str, sorted(skip & set(chs)))) or "无"))
    for c in chs:
        mark = ""
        if rates[c] < GATE_RATE:
            mark = "  <-- 未达 %.0f%%" % GATE_RATE
        if c in skip:
            mark += "（卷首章，不计入稳态）"
        print("  ch%d: %5.1f%%  calls=%d%s" % (c, rates[c], by_ch[c]["calls"], mark))
    print("稳态达标：%d/%d（判据 ≥%d 章 ≥%.0f%%）→ %s"
          % (n_ok, len(steady), GATE_MIN_CHAPTERS, GATE_RATE,
             "PASS" if n_ok >= GATE_MIN_CHAPTERS and len(steady) >= GATE_MIN_CHAPTERS else "FAIL"))
    print("塌陷（≥%.0fpt）：%s" % (COLLAPSE_PT, collapses or "无"))
    print("累计综合（如实并行报告）：%.2f%%" % (100 * tot_hit / max(tot_hit + tot_miss + tot_out, 1)))
    steady_avg = sum(rates[c] for c in steady) / max(len(steady), 1)
    print("稳态窗均值：%.2f%%" % steady_avg)
    print("机制：audit %.2f 笔/章（≤%.1f）%s｜audit thinking disabled %s｜"
          "快速道 %d/%d（≥%.0f%%）%s｜corpus_rolled 违例 %d"
          % (audit_per_ch, AUDIT_MAX_PER_CH,
             "PASS" if audit_per_ch <= AUDIT_MAX_PER_CH else "FAIL",
             "PASS" if audit_disabled else "FAIL",
             fast_lines, len(chs), FAST_MIN_RATE * 100,
             "PASS" if fast_rate >= FAST_MIN_RATE else "FAIL",
             rolled_violated))

    ok = (n_ok >= GATE_MIN_CHAPTERS and len(steady) >= GATE_MIN_CHAPTERS
          and not collapses and audit_per_ch <= AUDIT_MAX_PER_CH
          and audit_disabled and fast_rate >= FAST_MIN_RATE and rolled_violated == 0)
    print("总判定：%s" % ("✅ 达标（v0.19.8 发布线）" if ok else "❌ 未达标（逐项归因）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
