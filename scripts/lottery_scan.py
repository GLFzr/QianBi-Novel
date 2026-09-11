# -*- coding: utf-8 -*-
"""路由彩票事件分析器（v15 仪器，离线——不进请求路径）

DeepSeek 多副本部署下，同一前缀的请求可能落到缓存未同步的冷节点：该笔请求
几乎整体按 miss 计价（v13 ch30 deslop/review_fix 双零命中即实证）。本脚本
从 usage.jsonl 离线检测此类事件：

判定：按时间序维护「此前最大单笔命中深度」，某笔 hit < max_hit - THRESH
（缺省 100k tok）即记一次冷击事件，缺口 = max_hit - hit。

用法：
  python scripts/lottery_scan.py tests_output/bench/v15_long13/.qianbi_novel/usage/usage.jsonl
"""
import json
import sys
from collections import defaultdict

THRESH = 100_000


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    rows = []
    with open(sys.argv[1], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r.get("ts", ""))
    max_hit = 0
    events = []
    for r in rows:
        hit = r.get("hit") or 0
        if max_hit and hit < max_hit - THRESH:
            events.append({"ch": r.get("ch"), "ts": r.get("ts"),
                           "phase": r.get("phase"), "hit": hit,
                           "deficit": max_hit - hit})
        max_hit = max(max_hit, hit)
    by_ch = defaultdict(lambda: [0, 0])
    for e in events:
        by_ch[e["ch"]][0] += 1
        by_ch[e["ch"]][1] += e["deficit"]
    n_ch = len({r.get("ch") for r in rows}) or 1
    print("总笔数 %d ｜ 冷击事件 %d 次 ｜ 涉及 %d 章 ｜ 中位数 %.1f 次/章、%s tok/章"
          % (len(rows), len(events), len(by_ch),
             sorted(v[0] for v in by_ch.values())[len(by_ch) // 2] if by_ch else 0,
             f"{sorted(v[1] for v in by_ch.values())[len(by_ch) // 2]:,}" if by_ch else "0"))
    for e in events:
        print("  ch%-3s %s %-14s hit=%9s deficit=%9s"
              % (e["ch"], (e.get("ts") or "?")[11:19],
                 e["phase"], f"{e['hit']:,}", f"{e['deficit']:,}"))
    # 判据（研究文档 §C 预注册）：中位数 ≤1.5 次/章、≤40k tok/章
    med_n = (sorted(v[0] for v in by_ch.values())[len(by_ch) // 2] if by_ch else 0)
    med_tok = (sorted(v[1] for v in by_ch.values())[len(by_ch) // 2] if by_ch else 0)
    verdict = "✅ 彩票在预注册预算内" if med_n <= 1.5 and med_tok <= 40_000 \
        else "⚠️ 彩票超出预算——标注为外部因素，不计入回退决策"
    print(verdict)


if __name__ == "__main__":
    main()
