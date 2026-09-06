# -*- coding: utf-8 -*-
"""成本台账：扫描全部历史 usage.jsonl，逐行按模型分价重算，输出完整成本表。

价格口径（DeepSeek v4 off-peak，$/M）：flash hit .007 / miss .22 / out .66；
pro hit .022 / miss .66 / out 1.98。¥ = ×7.2。
真实目录的行按日期聚类（一天=一个跑次）；bench 变体按目录=一个跑次。
"""
from __future__ import annotations

import glob
import json
import os
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_USAGE = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage", "usage.jsonl")
USD_CNY = 7.2
PRICE = {
    "flash": {"hit": 0.007e-6, "miss": 0.22e-6, "out": 0.66e-6},
    "pro": {"hit": 0.022e-6, "miss": 0.66e-6, "out": 1.98e-6},
}

# 跑次语义标注（变体目录 → 说明）
BENCH_LABELS = {
    "_prepare_home": ("种子书 prepare", "设定+卷纲+6 细纲（一次性基建）"),
    "smoke2": ("台子冒烟", "1 章微循环"),
    "base": ("E1 基线", "0.18.5 架构全流程 3 章"),
    "prose_low": ("E2 prose=low", "全流程 3 章（否决：+5%）"),
    "review_low_fast": ("E3 审校low+快速道", "全流程 3 章"),
    "audit_med": ("E4 清算 medium(杀)", "2.5 章，被外部终止"),
    "audit_high_seed": ("E5b 清算 high 基线", "固定草稿直奔清算 3 章（pro 全量）"),
    "audit_low_seed": ("E5a 清算 low", "同输入（-93% 成本）"),
    "audit_medseed": ("E7 清算 medium+16k", "同输入（检出缩水，否决）"),
    "audit_hiflash": ("E6 清算 high on flash", "同输入（确定性空流，不可行）"),
    "audit_noreason": ("E9' 清算关推理", "同输入（59% 引文不实，否决）"),
    "cascade_e9": ("E9 级联首跑", "pro 复核 bug 版（3 章全采信）"),
    "cascade_e9b": ("E9 级联修复版", "最终形态：预扫干净零 pro / 硬伤 pro 复核 flagged"),
    "review_disabled": ("E10 审校 disabled", "全流程 3 章（埋雷召回 4/4 的档位）"),
    "prose_med": ("E8 prose=medium", "全流程 3 章（+64%，强烈否决）"),
    "review_tier_home": ("审校三档埋雷", "12 票：4 颗植入缺陷 × 3 档 × 2 票 + 干净章对照"),
}


def _tier(model: str) -> str:
    return "pro" if "pro" in str(model) else "flash"


def _cost(rows) -> dict:
    hit = miss = out = reas = 0.0
    in_total = 0
    cost_usd = 0.0
    models = {}
    has_cache = False
    for r in rows:
        t = _tier(r.get("model", ""))
        models[t] = models.get(t, 0) + 1
        o = r.get("out") or 0
        out += o
        # 0.18.3 时代的行只有 in（总输入）没有 hit/miss 字段：按 miss 价计并标注
        if r.get("hit") is None or r.get("miss") is None:
            i = r.get("in") or 0
            in_total += i
            cost_usd += i * PRICE[t]["miss"] + o * PRICE[t]["out"]
            continue
        has_cache = True
        h, m = r.get("hit") or 0, r.get("miss") or 0
        hit += h
        miss += m
        in_total += h + m
        reas += r.get("reasoning") or 0
        cost_usd += h * PRICE[t]["hit"] + m * PRICE[t]["miss"] + o * PRICE[t]["out"]
    return {
        "calls": len(rows),
        "in_tok": int(in_total),
        "hit_pct": (round(hit / (hit + miss) * 100, 1) if hit + miss else 0.0) if has_cache else "无记录",
        "out_tok": int(out),
        "reasoning": int(reas),
        "usd": round(cost_usd, 4),
        "cny": round(cost_usd * USD_CNY, 3),
        "models": models,
    }


def _rows(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _chapters_of(variant: str):
    p = os.path.join(ROOT, "tests_output", "bench", "%s.metrics.json" % variant)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return len(json.load(f).get("chapters") or [])
    except Exception:
        return None


def main():
    ledger = []   # (类别, 名称, 说明, metrics)

    # 1) bench 变体
    for d in sorted(glob.glob(os.path.join(ROOT, "tests_output", "bench", "*"))):
        name = os.path.basename(d)
        if name in ("_prepare_home",) or not os.path.isdir(d):
            pass
        rows = _rows(os.path.join(d, ".qianbi_novel", "usage", "usage.jsonl"))
        if rows and name in BENCH_LABELS:
            label, note = BENCH_LABELS[name]
            ledger.append(("实验台", label + "（%s）" % name, note, _cost(rows)))

    # 2) 5ch e2e 留存
    rows = _rows(os.path.join(ROOT, "tests_output", "5ch_e2e", "usage_run.jsonl"))
    if rows:
        ledger.append(("真机全流程", "5 章端到端（run4 留存）",
                       "0.18.5+ 架构 5 章共写全流程，verdict 全过", _cost(rows)))

    # 3) 真实目录：按日期聚类
    real = _rows(REAL_USAGE)
    by_day = {}
    for r in real:
        by_day.setdefault(str(r.get("ymd") or r.get("ts", "")[:10]), []).append(r)
    day_labels = {
        "2026-08-31": ("能力轮验收跑", "0.18.3 架构 · 执灯人夜行档案（含审校六维/清算/追踪全链）"),
        "2026-09-05": ("0.18.4 发版验收", "双层前缀架构 · 6 章（57 笔全量埋点的那次）"),
        "2026-09-06": ("Agent 化与档位实验", "agent_eval L2 兜底 + review_tier 探测 + 级联首日"),
    }
    for day in sorted(by_day):
        label, note = day_labels.get(day, (day, "真机调用"))
        ledger.append(("真实目录", "%s（%s）" % (label, day), note, _cost(by_day[day])))

    # 输出
    total_calls = sum(m["calls"] for _c, _n, _s, m in ledger)
    total_cny = sum(m["cny"] for _c, _n, _s, m in ledger)
    lines = ["# 成本台账（全部真机调用，逐行按模型分价重算）", "",
             "> 价格口径：DeepSeek v4 off-peak——flash 输入 hit $0.007 / miss $0.22 / 输出 $0.66；",
             "> pro 输入 hit $0.022 / miss $0.66 / 输出 $1.98（每百万 token，¥=$×7.2）。",
             "> 每行 usage 记录按其模型分价——修正了早期 metrics 按统一 flash 价低估 pro 行的问题。",
             ""]
    cur = None
    for cat, name, note, m in ledger:
        if cat != cur:
            lines.append("## %s" % cat)
            lines.append("")
            lines.append("| 跑次 | 章 | 调用 | 输入 tok | 命中 | 输出 tok | 推理 tok | 成本 ¥ | 模型分布 |")
            lines.append("|---|---|---|---|---|---|---|---|---|")
            cur = cat
        models = " / ".join("%s×%d" % (k, v) for k, v in sorted(m["models"].items()))
        ch = _chapters_of(name) if cat == "实验台" else None
        hit_s = m["hit_pct"] if isinstance(m["hit_pct"], str) else "%s%%" % m["hit_pct"]
        lines.append("| %s | %s | %d | %s | %s | %s | %s | %.3f | %s |"
                     % (name, str(ch) if ch else "—", m["calls"], f"{m['in_tok']:,}",
                        hit_s, f"{m['out_tok']:,}", f"{m['reasoning']:,}", m["cny"], models))
        if note:
            lines.append("  ^ ^ %s" % note)
    lines.append("")
    lines.append("**合计**：%d 笔真机调用，约 **¥%.2f**（全部实验 + 验收 + 探针）。" % (total_calls, total_cny))
    lines.append("")
    lines.append("## 实验有效性注记（读表前必看）")
    lines.append("")
    lines.append("- **E1-E4 跑在「全 pro」事故配置下**（模型分布 pro×24/28 如实记录）：当时实验台")
    lines.append("  _mk_cfg 的 pro 连接拼接存在 Python 运算符优先级 bug（`A if pro else [] + [...]`），")
    lines.append("  三条连接只剩 pro——E1「基线」实际是全 pro 底色，¥1.943/3 章不代表 0.18.5 默认配置。")
    lines.append("  E5b 起修复（flash×9/pro×3），其审校/追踪相位才是 flash。E2/E3 的对比结论方向不变")
    lines.append("  （同底色下变量对照），但绝对成本数值不可与修复后的变体直接互比。")
    lines.append("- **E5b vs E9b 是同输入同模式的清算对照**：跑级成本 ¥0.879 → ¥0.281（-68%，含追踪/摘要");
    lines.append("  等其他相位噪声）；**相位级**（只看 canon_audit 相位）pro 全量 47.3k tok → flash 预扫")
    lines.append("  14.1k + pro 复核 3.7k，**-82%**——两个口径都对，正文引用注明层级。")
    lines.append("- **单章成本演进（诚实口径，注意字数目标不可直接比）**：0.18.3 能力轮 ~¥0.26/章")
    lines.append("  （2000 字目标 + off-peak）；0.18.4 验收 ¥0.78/章（3000 字目标 + 细纲 41k 输出时代）；")
    lines.append("  0.19 五章端到端 ¥0.33/章（2500 字目标 + 级联前架构）；0.19 级联后清算环节 -68%，")
    lines.append("  全流程预计 ~¥0.25/章（待正式对照跑）。")
    lines.append("- 全部调用走 off-peak 时段（除 09-05 验收部分白天），若含 peak 价成本更高。")
    out = os.path.join(ROOT, "docs", "成本台账.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[-14:]))
    print("→", out)


if __name__ == "__main__":
    main()
