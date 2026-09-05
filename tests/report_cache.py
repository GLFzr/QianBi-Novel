# -*- coding: utf-8 -*-
"""缓存命中报表（体验轮 P1 可观测性）：读 usage.jsonl，按天/按 phase 聚合命中率与费用

数据源：~/.qianbi_novel/usage/usage.jsonl（与 app/usage.py 的落盘路径一致）。
每行含 ts/ymd/slot/model/in/out/latency + hit/miss/phase（后三列为 P1 新增；
旧文件缺列时按 0/空兜底——命中率分母为 0 时显示 "-"，不参与告警）。

用法（纯标准库，无第三方依赖）：
    python tests/report_cache.py                # 全量
    python tests/report_cache.py --last 7       # 最近 7 天
    python tests/report_cache.py --phase outline

指标口径：
- 加权命中率 = Σhit / (Σhit + Σmiss)（非各行命中率平均）
- 费用：命中部分按 CACHE_HIT_IN 单价，其余输入按 PRICES 未命中价，输出按 PRICES 输出价；
  无命中记录（hit=0）时与 app/usage.cost_of 口径一致
- 加权命中率低于 HIT_RATE_WARN 时输出告警行
"""
import argparse
import datetime
import json
import os
import sys

# 价目表（元/百万 tokens）——按 DeepSeek 官网当时牌价调整
# 匹配规则与 app/usage.py 一致：tag 为模型名子串（不区分大小写）即命中，否则用 _default
# 每档为 (输入未命中/普通输入价, 输出价)
PRICES = {"flash": (1.0, 2.0), "mini": (1.0, 2.0), "_default": (2.0, 8.0)}
CACHE_HIT_IN = 0.5      # 缓存命中输入单价（元/百万 tokens）
HIT_RATE_WARN = 0.80    # 加权命中率告警阈值

USAGE_DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage")
USAGE_FILE = os.path.join(USAGE_DIR, "usage.jsonl")


def cost_of(model: str, tin: int, tout: int, hit: int = 0) -> float:
    """按价目表估算单行成本（元）；hit 部分走缓存命中价，其余走普通输入价"""
    model = (model or "").lower()
    for tag, rates in PRICES.items():
        if tag != "_default" and tag in model:
            in_rate, out_rate = rates
            break
    else:
        in_rate, out_rate = PRICES["_default"]
    hit = min(max(int(hit or 0), 0), int(tin or 0))
    return hit / 1e6 * CACHE_HIT_IN + (tin - hit) / 1e6 * in_rate + tout / 1e6 * out_rate


def load_rows(path: str) -> list:
    """读入全部记录（容忍坏行：跳过）"""
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except OSError as e:
        print(f"读取失败: {e}")
    return rows


def _stat() -> dict:
    return {"calls": 0, "in": 0, "out": 0, "hit": 0, "miss": 0, "cost": 0.0}


def aggregate(rows: list, keyfunc) -> dict:
    """按 keyfunc 分组聚合：tokens / 命中 / 费用"""
    stats = {}
    for r in rows:
        tin = int(r.get("in", 0) or 0)
        tout = int(r.get("out", 0) or 0)
        hit = int(r.get("hit", 0) or 0)
        miss = int(r.get("miss", 0) or 0)
        s = stats.setdefault(keyfunc(r), _stat())
        s["calls"] += 1
        s["in"] += tin
        s["out"] += tout
        s["hit"] += hit
        s["miss"] += miss
        s["cost"] += cost_of(r.get("model", ""), tin, tout, hit)
    return stats


def rate_of(s: dict):
    """加权命中率；无命中数据（分母 0）返回 None"""
    denom = s["hit"] + s["miss"]
    return (s["hit"] / denom) if denom else None


def _fmt_rate(s: dict) -> str:
    r = rate_of(s)
    return "-" if r is None else f"{r:.1%}"


def print_table(title: str, stats: dict, total: dict):
    print(f"\n== {title} ==")
    print(f"{'键':<14}{'调用':>6}{'输入':>12}{'命中':>12}{'未命中':>12}"
          f"{'命中率':>8}{'输出':>12}{'费用元':>10}")
    for k, s in stats.items():
        print(f"{str(k):<14}{s['calls']:>6}{s['in']:>12}{s['hit']:>12}{s['miss']:>12}"
              f"{_fmt_rate(s):>8}{s['out']:>12}{s['cost']:>10.4f}")
    print(f"{'总计':<14}{total['calls']:>6}{total['in']:>12}{total['hit']:>12}"
          f"{total['miss']:>12}{_fmt_rate(total):>8}{total['out']:>12}{total['cost']:>10.4f}")


def collect_alerts(groups: list) -> list:
    """groups: [(标签, stat)]；返回命中率低于阈值的 (标签, 命中率) 列表"""
    alerts = []
    for label, s in groups:
        r = rate_of(s)
        if r is not None and r < HIT_RATE_WARN:
            alerts.append((label, r))
    return alerts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="缓存命中报表（按天/按 phase 聚合）")
    ap.add_argument("--last", type=int, default=0, metavar="N",
                    help="只统计最近 N 天（含今天）")
    ap.add_argument("--phase", default="", metavar="名",
                    help="只统计指定 phase（精确匹配；旧数据 phase 为空）")
    args = ap.parse_args(argv)

    if not os.path.exists(USAGE_FILE):
        print(f"未找到用量文件: {USAGE_FILE}")
        return 0

    rows = load_rows(USAGE_FILE)
    total_lines = len(rows)
    if args.last and rows:
        cutoff = (datetime.date.today()
                  - datetime.timedelta(days=max(args.last, 1) - 1)).strftime("%Y-%m-%d")
        rows = [r for r in rows if (r.get("ymd") or "") >= cutoff]
    if args.phase:
        rows = [r for r in rows if (r.get("phase") or "") == args.phase]

    print(f"数据源: {USAGE_FILE}")
    print(f"记录: 全部 {total_lines} 行，过滤后 {len(rows)} 行"
          f"（--last {args.last or '全部'}  --phase {args.phase or '全部'}）")
    if not rows:
        print("过滤后无记录。")
        return 0

    total = aggregate(rows, lambda r: "all")["all"]
    by_day = aggregate(rows, lambda r: r.get("ymd") or "?")
    print_table("按天", dict(sorted(by_day.items())), total)

    by_phase = aggregate(rows, lambda r: r.get("phase") or "(未记录)")
    # 按 调用数 降序，最常用的 phase 在前
    print_table("按 phase", dict(sorted(by_phase.items(),
                                        key=lambda kv: (-kv[1]["calls"], kv[0]))), total)

    alerts = collect_alerts([("总计", total)]
                            + [(f"日期 {k}", s) for k, s in by_day.items()]
                            + [(f"phase {k}", s) for k, s in by_phase.items()])
    if alerts:
        print(f"\n[告警] 加权命中率低于 {HIT_RATE_WARN:.0%}：")
        for label, r in alerts:
            print(f"  {label}: {r:.1%}")
    else:
        print(f"\n命中率均不低于 {HIT_RATE_WARN:.0%}，无告警。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
