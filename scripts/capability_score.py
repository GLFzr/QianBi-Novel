# -*- coding: utf-8 -*-
"""能力评分卡复算器（0.20.4 全量测试与能力评估计划的执行件）。

读 `docs/0.20.4_判据表.json`，按其中的权重/目标/证据等级复算能力分，输出
Markdown 记分卡；可另存 JSON 供批次报告引用。

计分（与计划 §3.2 一致）：
    子项得分 = 权重 × f(实测/目标) × 证据折减
    f(min_ratio) = min(1, 实测/目标)
    f(max_ratio) = min(1, 目标/实测)；目标=0 时 f = max(0, 1-实测)；实测<=0 → 1
    f(boolean)   = 1 if 实测>=1 else 0
    证据折减 = E1 1.0 / E2 0.7 / E3 0.0
    域得分封顶：该域 red_gates 非空时 = min(域得分, cap_if_red_gate × 域权重)
    等级：<40 L1 / 40-59 L2 / 60-79 L3 / 80-89 L4 / >=90 L5

用法：
    .venv/Scripts/python.exe scripts/capability_score.py
    .venv/Scripts/python.exe scripts/capability_score.py --json _scratch/score.json
    .venv/Scripts/python.exe scripts/capability_score.py --measure fixes.json   # 修好后再复算
    .venv/Scripts/python.exe scripts/capability_score.py --fail-under 60        # CI 门禁用

--measure 文件格式：{"D1.1": 0.995, "J-01": "green", ...}（子项 id 或判据 id）
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
DEFAULT_CRITERIA = os.path.join(ROOT, "docs", "0.20.4_判据表.json")
DISCOUNT = {"E1": 1.0, "E2": 0.7, "E3": 0.0}


def f_min_ratio(actual: float, target: float) -> float:
    if target <= 0:
        return 1.0 if actual >= 0 else 0.0
    return min(1.0, actual / target)


def f_max_ratio(actual: float, target: float) -> float:
    if actual <= 0:
        return 1.0
    if target <= 0:
        return max(0.0, 1.0 - actual)
    return min(1.0, target / actual)


def f_boolean(actual: float, target: float) -> float:
    return 1.0 if actual >= 1.0 else 0.0


KINDS = {"min_ratio": f_min_ratio, "max_ratio": f_max_ratio, "boolean": f_boolean}


def level_of(total: float, levels: list) -> dict:
    for lv in levels:
        if lv["min"] <= total <= lv["max"]:
            return lv
    return levels[-1]


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", default=DEFAULT_CRITERIA)
    ap.add_argument("--measure", default="")
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--fail-under", type=float, default=None)
    args = ap.parse_args()

    crit = load(args.criteria)
    overrides = load(args.measure) if args.measure else {}

    rows, total, capped_total = [], 0.0, 0.0
    for dom in crit["domains"]:
        raw = 0.0
        for m in dom["metrics"]:
            cur = float(overrides.get(m["id"], m["current"]))
            fn = KINDS[m["kind"]]
            disc = DISCOUNT.get(m.get("grade", "E1"), 1.0)
            score = float(m["weight"]) * fn(cur, float(m["target"])) * disc
            m["_score"] = round(score, 3)
            m["_current_used"] = cur
            raw += score
        cap = dom.get("cap_if_red_gate")
        final = raw
        if dom.get("red_gates") and cap is not None:
            final = min(raw, float(cap) * float(dom["weight"]))
        rows.append((dom, raw, final))
        total += raw
        capped_total += final

    lv = level_of(capped_total, crit["scoring"]["levels"])
    print("# 0.20.4 能力评分卡（复算于 %s）\n" % crit.get("generated", "?"))
    print("| 域 | 权重 | 原始分 | 计分 | 红门 |")
    print("|---|---|---|---|---|")
    for dom, raw, final in rows:
        red = "、".join(dom.get("red_gates") or []) or "—"
        mark = "（封顶）" if abs(final - raw) > 1e-9 else ""
        print("| %s %s | %d | %.2f | **%.2f**%s | %s |" % (
            dom["id"], dom["name"], dom["weight"], raw, final, mark, red))
    print("| **合计** | **%d** | %.2f | **%.2f** | |" % (
        sum(d["weight"] for d, _, _ in rows), total, capped_total))
    print("\n**总分 %.1f / 100 → %s（%s）**" % (capped_total, lv["level"], lv["name"]))

    gates = crit.get("gates", [])
    if gates:
        stat = {}
        for g in gates:
            cur = str(overrides.get(g["id"], g["current"]))
            stat[cur] = stat.get(cur, 0) + 1
        print("\n判据态：%s（共 %d 条；绿 %d / 黄 %d / 红 %d）" % (
            "，".join("%s %d" % (k, v) for k, v in sorted(stat.items())), len(gates),
            stat.get("green", 0), stat.get("yellow", 0), stat.get("red", 0)))
        reds = [g["id"] for g in gates
                if str(overrides.get(g["id"], g["current"])) == "red"]
        if reds:
            print("红门清单：%s" % "、".join(reds))

    if args.json_out:
        out = {
            "criteria_version": crit.get("version"),
            "generated": crit.get("generated"),
            "total_raw": round(total, 2),
            "total": round(capped_total, 2),
            "level": lv["level"],
            "level_name": lv["name"],
            "domains": [
                {
                    "id": d["id"], "name": d["name"], "weight": d["weight"],
                    "raw": round(raw, 2), "score": round(final, 2),
                    "red_gates": d.get("red_gates") or [],
                    "metrics": [
                        {"id": m["id"], "name": m["name"], "weight": m["weight"],
                         "target": m["target"], "current_used": m["_current_used"],
                         "grade": m.get("grade"), "score": m["_score"]}
                        for m in d["metrics"]
                    ],
                }
                for d, raw, final in rows
            ],
            "gates": [
                {"id": g["id"], "current": str(overrides.get(g["id"], g["current"]))}
                for g in gates
            ],
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("\nJSON 已写出：%s" % args.json_out)

    if args.fail_under is not None and capped_total < args.fail_under:
        print("\nFAIL：总分 %.1f < 门限 %.1f" % (capped_total, args.fail_under))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
