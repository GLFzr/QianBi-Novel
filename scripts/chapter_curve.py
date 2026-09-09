# -*- coding: utf-8 -*-
"""逐章 hit% 曲线（T1/T3 长卷验收的核心产出）

usage.jsonl 只带 phase/slot，不带章号——本脚本按"每章恰调用一次"的相位作章节锚点
（prose 优先，退化到 global_summary/chapter_summary/tracking）把逐笔用量切成章段。
锚点选择与段数校验都写实数，段数≠章数即报警（不猜）。

产出口径两套价（《测试接手指南_v1.md》§1 验收线用 DS 口径，实际账单看渠道价）：
  ds = DeepSeek 官方 off-peak（hit $0.007 / miss $0.22 / out $0.66 每 M，×7.2）
  渠道价 = 该渠道价目表（tr-dsv4f：输入 ¥1 / 输出 ¥2 / 缓存读 ¥0.20 每 M）

用法：
  python scripts/chapter_curve.py --variant t1_long20
  python scripts/chapter_curve.py --variant t1_long20 --price tr --chapters 20
产物：tests_output/bench/chapter_curve_<variant>.md（并打印同表）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# W-5：盲区 token 的口径与 cost_ledger 必须同源，唯一定义在 app.usage
from app.usage import blind_spread, cache_caliber  # noqa: E402

BENCH = os.path.join(ROOT, "tests_output", "bench")
ANCHORS = ("prose", "global_summary", "chapter_summary", "tracking")
USD_CNY = 7.2
PRICES = {                       # 每百万 token 的人民币价：hit / miss(未命中输入) / out
    "ds": {"hit": 0.007 * USD_CNY, "miss": 0.22 * USD_CNY, "out": 0.66 * USD_CNY},
    "tr": {"hit": 0.20, "miss": 1.00, "out": 2.00},
    "bailian": {"hit": 0.0504, "miss": 1.584, "out": 4.752},
}


def _usage_path(variant: str) -> str:
    for p in (os.path.join(BENCH, variant, ".qianbi_novel", "usage", "usage.jsonl"),
              os.path.join(BENCH, variant + ".usage.jsonl")):
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    raise SystemExit("找不到用量文件：%s（跑次目录与切片备份皆无）" % variant)


def _rows(path: str) -> list:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                out.append({"phase": r.get("phase") or "", "slot": r.get("slot") or "",
                            "model": r.get("model") or "",
                            "hit": int(r.get("hit") or 0), "miss": int(r.get("miss") or 0),
                            "in": int(r.get("in") or 0), "out": int(r.get("out") or 0),
                            "lat": float(r.get("latency") or 0.0), "ts": r.get("ts") or "",
                            "ch": int(r.get("ch") or 0)})
    return out


def _cut_by_ch(rows: list) -> tuple:
    """按**真章号**分组（usage 行带 ch 时优先用它，不再靠"某相位每章恰一次"猜锚点）。

    同章多段合并：崩溃后重跑、或多段拼接的长跑里同一章会被写两遍——按 prose 数段会
    虚报章数（今天 T3 五段拼出 56 段 ≠ 实际 53 章就是这个坑），合并后章数诚实，
    重跑烧掉的量也如实挂在那一章上。"""
    groups, order, setup = {}, [], []
    for r in rows:
        ch = int(r.get("ch") or 0)
        if ch <= 0:
            setup.append(r)                       # 章号未知（旧行/细纲备料）
            continue
        if ch not in groups:
            groups[ch] = []
            order.append(ch)
        groups[ch].append(r)
    ordered = sorted(order)
    return setup, [groups[c] for c in ordered], ordered


def _expected_chapters(variant: str) -> int:
    m = os.path.join(BENCH, variant + ".metrics.json")
    if os.path.isfile(m):
        try:
            return len(json.load(open(m, encoding="utf-8")).get("chapters") or [])
        except (OSError, ValueError):
            return 0
    return 0


def _cut(rows: list, anchor: str) -> tuple:
    """按锚点相位切章：锚点行开启一章，其后非锚点行归入该章；首个锚点前 = 备料段。"""
    setup, segs, cur = [], [], None
    for r in rows:
        if r["phase"] == anchor:
            cur = [r]
            segs.append(cur)
        elif cur is None:
            setup.append(r)
        else:
            cur.append(r)
    return setup, segs


def _pick_anchor(rows: list, want: int) -> tuple:
    """段数等于章数的锚点才算可信；都不可信时取 prose 并报警。"""
    for a in ANCHORS:
        setup, segs = _cut(rows, a)
        if want and len(segs) == want:
            return a, setup, segs, ""
    setup, segs = _cut(rows, "prose")
    warn = "" if not want or len(segs) == want else \
        "锚点 prose 切出 %d 段 ≠ 章数 %d（备料段 %d 笔）——逐章数字按段解读" % (
            len(segs), want, len(setup))
    return "prose", setup, segs, warn


def _agg(rows: list, price: dict) -> dict:
    """三段口径（W-5，唯一定义在 app.usage.cache_caliber）：

    - **已知**：网关回了缓存明细 → hit / miss_known；
    - **盲区** `blind_tok`：什么都没回（含缺 hit 键的历史行）→ **既不进 hit% 分子也不进分母**；
    - **账面** `cost`：盲区按 miss 计（未证明命中的 token 不能算命中，保守上限）；
    - **真实** `cost_real`：盲区按**本渠道已知行的实测命中率**摊派——omen-alpha 33.7% 调用
      没回明细，账面因此比真实高 2.4 倍，两个数一起报才解释得清。

    hit_pct      = hit / 实际 prompt（含盲区，账面口径）
    hit_pct_book = hit / (hit+上报 miss)＝**只看已知行**的命中率（分渠道可裁决的那个数）"""
    hit = miss_known = out = 0
    in_true = 0
    blind = blind_tok = 0
    blind_by = {}
    for r in rows:
        h, m, b = cache_caliber(r)
        hit += h
        miss_known += m
        blind_tok += b
        in_true += h + m + b
        out += r["out"]
        if b:
            blind += 1
            key = r.get("model") or "?"
            blind_by[key] = blind_by.get(key, 0) + b
    miss_book = miss_known + blind_tok                       # 账面：盲区一律按 miss 计
    add_hit, add_miss = blind_spread(hit, miss_known, blind_tok)
    cost = (hit * price["hit"] + miss_book * price["miss"] + out * price["out"]) / 1e6
    cost_real = ((hit + add_hit) * price["hit"]
                 + (add_miss + miss_known) * price["miss"]
                 + out * price["out"]) / 1e6
    return {"calls": len(rows), "hit": hit, "miss": miss_book, "miss_known": miss_known,
            "out": out, "in": in_true, "in_true": in_true, "in_book": hit + miss_book,
            "blind": blind, "blind_tok": blind_tok, "blind_by_model": blind_by,
            "hit_pct": 100.0 * hit / max(1, in_true),
            "hit_pct_book": 100.0 * hit / max(1, hit + miss_known),
            "cost": cost, "cost_real": cost_real,
            "lat": sum(r["lat"] for r in rows) / max(1, len(rows))}


def _volumes(proj: str, nums: list) -> dict:
    """章号 → 卷号（卷界＝会话栈重置点，长卷曲线在这里必然断裂）。
    读不到工程（旧产物/清理过）就全标 0，曲线照出，只是不分卷。"""
    if not proj or not os.path.isdir(proj):
        return {}
    try:
        from app.core.history_compaction import resolve_volume
    except ImportError:
        return {}
    try:
        return {n: int(resolve_volume(proj, n) or 0) for n in nums}
    except Exception:  # noqa: BLE001  卷级大纲读不出（旧产物）→ 不分卷，曲线照出
        return {}


def _verdict(chs: list, price_name: str) -> list:
    """对《测试接手指南_v1.md》§1/§5.1 验收线逐条判：只判有证据的章段。"""
    out = []
    if not chs:
        return ["无章段，无法判定"]
    n = len(chs)
    tail = chs[-1]["cum_hit_pct"]
    out.append("卷末累计 hit%% %.1f%%（验收线 ≥97-99%%，N=%d）→ %s"
               "｜判据只看整跑累计：单章 hit%% 受盲区上报与卷界影响，一律不作裁决"
               % (tail, n, "✅" if tail >= 97.0 else ("⚠️ 体量未到 20 章，不作裁决" if n < 20 else "❌")))
    if n >= 10:
        c10 = [c for c in chs if c["num"] >= 10]
        lo = min(c["hit_pct"] for c in c10)
        out.append("第 10 章起单章 hit%% 最低 %.1f%%（验收线 ≥95%%）→ %s"
                   % (lo, "✅" if lo >= 95.0 else "❌"))
    worst_miss = max(chs, key=lambda c: c["miss"])
    out.append("单章 miss 峰值 %d tok @第%d章（预算线 ≤15k）→ %s"
               % (worst_miss["miss"], worst_miss["num"],
                  "✅" if worst_miss["miss"] <= 15000 else "❌"))
    per = sum(c["cost"] for c in chs) / n
    per_real = sum(c.get("cost_real", c["cost"]) for c in chs) / n
    out.append("章均成本（%s 价）账面 ¥%.3f／真实 ¥%.3f（验收线 DS 口径 ≤¥0.30）→ %s"
               % (price_name, per, per_real,
                  "✅" if price_name != "ds" or per <= 0.30 else "❌"))
    tot = sum(c["cost"] for c in chs)
    tot_real = sum(c.get("cost_real", c["cost"]) for c in chs)
    out.append("正文累计成本（%s 价）账面 ¥%.2f／真实 ¥%.2f"
               "（预算 ¥7.0 / 全停 ¥10.5，DS 口径对照台账）" % (price_name, tot, tot_real))
    lat = [c["lat"] for c in chs]
    out.append("章均延迟 %.1fs（首章 %.1fs → 末章 %.1fs，读税/延迟曲线看趋势）"
               % (sum(lat) / len(lat), lat[0], lat[-1]))
    blind = sum(c.get("blind", 0) for c in chs)
    blind_tok = sum(c.get("blind_tok", 0) for c in chs)
    if blind:
        out.append("📚 三段对账（W-5）：缺缓存明细的调用 %d 笔／盲区 %s tok"
                   "｜账面 ¥%.2f（盲区按 miss 计）／真实 ¥%.2f（盲区按本渠道已知行实测命中率 %s%% 摊派）"
                   "＝虚高 %.1f 倍｜hit%% 只在已知行上算：在册口径 %.1f%%、账面口径 %.1f%%"
                   % (blind, format(blind_tok, ","), tot, tot_real,
                      "%.1f" % (100.0 * sum(c["hit"] for c in chs)
                                / max(1, sum(c["hit"] + c.get("miss_known", 0)
                                             for c in chs))),
                      tot / max(0.01, tot_real),
                      chs[-1]["cum_hit_pct_book"], tail))
        by = {}
        for c in chs:
            for mdl, tok in (c.get("blind_by_model") or {}).items():
                by[mdl] = by.get(mdl, 0) + tok
        if by:
            out.append("　盲区按渠道：" + "、".join(
                "%s %s tok" % (m, format(t, ","))
                for m, t in sorted(by.items(), key=lambda kv: -kv[1])))
    # 卷界：换卷 = 新会话 = 历史一次性全 miss，这是"99% 能不能靠章数堆出来"的结构性上限
    rolls = [chs[i] for i in range(1, len(chs))
             if chs[i].get("vol", 0) and chs[i]["vol"] != chs[i - 1].get("vol", 0)]
    for r in rolls:
        prev = chs[r["num"] - 2]
        # 真换栈的指纹＝输入断崖（历史不跟随）；没跌下来说明跑次当时并未换栈
        # （W-1 前的卷号解析把区间末章号当章数 ⇒ 卷界形同虚设），别把税算在它头上
        no_reset = ("｜⚠ 未见栈重置（该卷界在跑次当时并未换栈——卷号解析 bug 或渠道沿用旧栈）"
                    if r["in"] > 0.6 * max(1, prev["in"]) else "")
        out.append("卷界 @第%d章（卷 %s→%s）：单章输入 %s → %s tok（-%.0f%%），"
                   "单章 hit%% %.1f%% → %.1f%%（换卷税＝把整卷历史重新 miss 一遍）%s"
                   % (r["num"], prev.get("vol", "?"), r["vol"], format(prev["in"], ","),
                      format(r["in"], ","),
                      100.0 * (1 - r["in"] / max(1, prev["in"])),
                      prev["hit_pct"], r["hit_pct"], no_reset))
    vols = {}
    for c in chs:
        vols.setdefault(c.get("vol", 0), []).append(c)
    for v, cs in sorted(vols.items()):
        if len(cs) >= 3:
            out.append("卷 %s（%d 章）：卷内单章 hit%% %.1f%% → %.1f%%，章末单章成本 ¥%.3f"
                       % (v or "?", len(cs), cs[0]["hit_pct"], cs[-1]["hit_pct"],
                          cs[-1]["cost"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="逐章 hit% 曲线（章节锚点切分 + 双口径计价）")
    ap.add_argument("--variant", required=True)
    ap.add_argument("--chapters", type=int, default=0, help="期望章数（缺省读 metrics.json）")
    ap.add_argument("--proj", default="", help="工程目录（卷界判据；缺省 <variant>/bench/种子书）")
    ap.add_argument("--price", default="ds", choices=sorted(PRICES), help="计价口径")
    ap.add_argument("--out", default="", help="报告路径（缺省 tests_output/bench/chapter_curve_<variant>.md）")
    a = ap.parse_args()

    # 多段拼接：T3 按指南 §5.3 要"分 3-4 夜跑"，用量散在多个段 home 里，
    # 只看最后一段会把前面几夜全丢掉 ⇒ --variant 接受逗号分隔的段名，按给定顺序拼。
    vars_ = [v.strip() for v in a.variant.split(",") if v.strip()]
    rows, srcs = [], []
    for v in vars_:
        up = _usage_path(v)
        srcs.append(os.path.relpath(up, ROOT).replace("\\", "/"))
        rows += _rows(up)
    want = a.chapters or sum(_expected_chapters(v) for v in vars_)
    price = PRICES[a.price]
    if any(int(r.get("ch") or 0) > 0 for r in rows):
        # usage 行带真章号（2026-09-09 起）→ 直接按章分组，同章多段合并；
        # 不再靠"某相位每章恰一次"猜锚点，续跑/重跑的章数也不会虚报
        setup, segs, chnos = _cut_by_ch(rows)
        anchor, warn = "ch（真章号）", ""
    else:
        anchor, setup, segs, warn = _pick_anchor(rows, want)
        chnos = list(range(1, len(segs) + 1))

    chs = []
    cum = {"hit": 0, "in": 0, "in_book": 0}
    vols = _volumes(a.proj or os.path.join(BENCH, vars_[0], "bench", "种子书"), chnos)
    for i, seg in zip(chnos, segs):
        g = _agg(seg, price)
        cum["hit"] += g["hit"]
        cum["in"] += g["in_true"]
        cum["in_book"] += g["in_book"]
        g.update(num=i, vol=vols.get(i, 0),
                 cum_hit_pct=100.0 * cum["hit"] / max(1, cum["in"]),
                 cum_hit_pct_book=100.0 * cum["hit"] / max(1, cum["in_book"]),
                 phases=sorted({r["phase"] for r in seg}))
        chs.append(g)
    pre = _agg(setup, price)

    lines = ["# 逐章成本曲线：%s（%s 价 · 锚点 %s）" % (a.variant, a.price, anchor), "",
             "用量源：`%s`｜总笔数 %d｜期望章数 %s｜备料段 %d 笔（细纲补写，¥%.3f）"
             % ("、".join(srcs), len(rows),
                want or "未给", pre["calls"], pre["cost"]), ""]
    if warn:
        lines += ["> ⚠️ " + warn, ""]
    lines += ["| 章 | 卷 | 笔数 | 输入 tok | hit tok | miss tok | hit% | 累计 hit% | ¥账面 | ¥真实 | 均延迟 s |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in chs:
        lines.append("| %d | %s | %d | %s | %s | %s | %.1f%% | %.1f%% | %.3f | %.3f | %.1f |"
                     % (c["num"], c["vol"] or "?", c["calls"], format(c["in"], ","),
                        format(c["hit"], ","),
                        format(c["miss"], ","), c["hit_pct"], c["cum_hit_pct"],
                        c["cost"], c.get("cost_real", c["cost"]), c["lat"]))
    lines += ["", "## 判据对照", ""] + ["- " + v for v in _verdict(chs, a.price)]
    txt = "\n".join(lines) + "\n"
    out = a.out or os.path.join(BENCH, "chapter_curve_%s.md" % "+".join(vars_))
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    print("→", out)


if __name__ == "__main__":
    main()
