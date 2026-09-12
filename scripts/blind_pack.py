# -*- coding: utf-8 -*-
"""盲评样本包打包/聚合仪器（v16 P4b；协议=20260911_0517 同款）

pack：把各变体指定章拷成匿名 样本-NNN.md（seed 洗牌），blind_map.json 落在包外层
（评委不可见），包内零来源信息。
aggregate：读 votes_JA/JB + blind_map → 逐样本加权分（双评平均）、逐变体总分/
地板/最大单维跌幅、**引文逐字验真**（evidence_quote 必须是样本文件子串）、
判定（对照 v16 3.2：D2/D4 ≥ -0.5、总分 ≥ -0.5）→ 报告 md。

用法：
  python scripts/blind_pack.py pack --id 20260913_v16 \
      --variants v15_long30=<正文目录>:2,5,8 anchor_baseline=<目录>:1,2,3
  python scripts/blind_pack.py aggregate --id 20260913_v16 \
      [--baseline-var anchor_baseline]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLIND_DIR = os.path.join(ROOT, "tests_output", "bench", "blind_eval")

DIMS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"]
WEIGHTS = {"D1": 12, "D2": 12, "D3": 10, "D4": 12, "D5": 8,
           "D6": 10, "D7": 10, "D8": 10, "D9": 8, "D10": 8}
GATE_DIMS = ("D2", "D4")   # 质量门一票否决维
GATE_FLOOR = -0.5          # 判据：D2/D4 ≥ -0.5、总分 ≥ -0.5
TOTAL_FLOOR = -0.5


def _pkg(id_: str) -> str:
    return os.path.join(BLIND_DIR, id_)


def _norm(text: str) -> str:
    """引文验一容归一：去空白差异（跨换行引用常见），保留实词序列。"""
    return re.sub(r"\s+", "", text or "")


# ---------- pack ----------

def cmd_pack(id_: str, variants: list, seed: int) -> int:
    pkg = _pkg(id_)
    if os.path.isdir(pkg):
        print("[错误] 包已存在（删除可重建）：%s" % pkg)
        return 2
    os.makedirs(pkg)
    entries = []   # (variant, chapter, path)
    for spec in variants:
        m = re.match(r"^(.+?)=(.+):([\d,]+)$", spec)
        if not m:
            print("[错误] --variants 格式：名=目录:章号逗号列表（收到 %r）" % spec)
            return 2
        vname, src, nums = m.group(1), m.group(2), m.group(3)
        if not os.path.isabs(src):
            src = os.path.join(ROOT, src)
        for n in [int(x) for x in nums.split(",") if x.strip()]:
            hits = sorted(glob.glob(os.path.join(src, "第%03d章*.md" % n))) or \
                sorted(glob.glob(os.path.join(src, "第%03d_*.md" % n)))
            if not hits:
                print("[错误] %s 缺 第%d 章文件（%s）" % (vname, n, src))
                return 2
            entries.append((vname, n, hits[0]))
    order = list(range(len(entries)))
    random.Random(seed).shuffle(order)
    blind_map = {}
    manifest = []
    for i, idx in enumerate(order, start=1):
        vname, n, path = entries[idx]
        sample = "样本-%03d.md" % i
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        with open(os.path.join(pkg, sample), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        blind_map[sample] = vname
        manifest.append({"sample": sample, "variant": vname, "chapter": n,
                         "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    with open(os.path.join(BLIND_DIR, id_ + ".blind_map.json"), "w", encoding="utf-8") as f:
        json.dump(blind_map, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(BLIND_DIR, id_ + ".manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"id": id_, "seed": seed, "samples": manifest}, f,
                  ensure_ascii=False, indent=1)
    print("[done] 包=%s 样本=%d（map/manifest 在包外层，评委不可见）"
          % (pkg, len(entries)))
    for e in manifest:
        print("  %s <- %s ch%d" % (e["sample"], e["variant"], e["chapter"]))
    return 0


# ---------- aggregate ----------

def _weighted(vote: dict) -> tuple:
    """加权总分（10 分制）与逐维分 dict。缺维按 0 计并返回缺维清单。"""
    dims = {d["dim"]: d for d in vote.get("dims", [])}
    missing = [d for d in DIMS if d not in dims]
    total = sum(WEIGHTS[d] * dims[d]["score"] for d in DIMS if d in dims) / 100.0
    return total, {d: dims[d]["score"] for d in DIMS if d in dims}, missing


def _verify_quotes(vote: dict, pkg: str) -> list:
    """引文逐字验真：evidence_quote（空白归一后）必须是样本文本子串。"""
    path = os.path.join(pkg, vote.get("sample", ""))
    try:
        with open(path, encoding="utf-8") as f:
            text = _norm(f.read())
    except OSError:
        return ["样本缺失:" + vote.get("sample", "")]
    bad = []
    for d in vote.get("dims", []):
        q = _norm(d.get("evidence_quote", ""))
        if not q or q not in text:
            bad.append("%s:%s" % (d.get("dim"), (d.get("evidence_quote") or "")[:20]))
    return bad


def cmd_aggregate(id_: str, baseline_var: str) -> int:
    pkg = _pkg(id_)
    map_path = os.path.join(BLIND_DIR, id_ + ".blind_map.json")
    if not os.path.isdir(pkg) or not os.path.isfile(map_path):
        print("[错误] 包或 map 不存在：%s" % id_)
        return 2
    with open(map_path, encoding="utf-8") as f:
        blind_map = json.load(f)
    votes_all = []
    for j in ("JA", "JB"):
        p = os.path.join(BLIND_DIR, id_ + ".votes_%s.json" % j)
        if not os.path.isfile(p):
            print("[错误] 缺票：%s" % p)
            return 2
        with open(p, encoding="utf-8") as f:
            votes_all.extend(json.load(f))

    # 逐样本聚合（双评平均）+ 引文验真
    per_sample = {}
    quote_violations = []
    for v in votes_all:
        s = v.get("sample")
        total, dims, missing = _weighted(v)
        bad = _verify_quotes(v, pkg)
        if bad:
            quote_violations.append({"judge": v.get("judge_id"), "sample": s, "bad": bad})
        e = per_sample.setdefault(s, {"scores": [], "dims": [], "dispute": False,
                                      "missing": missing})
        e["scores"].append(total)
        e["dims"].append(dims)
    rows = []
    for s, e in sorted(per_sample.items()):
        if len(e["scores"]) != 2:
            rows.append({"sample": s, "variant": blind_map.get(s, "?"), "score": None,
                         "chapter": None, "votes": len(e["scores"]),
                         "dispute": True, "missing": e["missing"], "judge_dims": e["dims"]})
            continue
        a, b = e["dims"]
        dispute = any(abs(a[d] - b[d]) >= 3 for d in DIMS)
        rows.append({"sample": s, "variant": blind_map.get(s, "?"),
                     "score": round(sum(e["scores"]) / 2, 2), "votes": 2,
                     "dispute": dispute, "missing": e["missing"], "judge_dims": e["dims"]})

    # 逐变体聚合
    by_var = {}
    for r in rows:
        if r["score"] is None:
            continue
        by_var.setdefault(r["variant"], []).append(r)
    summary = []
    for vname, rs in sorted(by_var.items()):
        scores = [r["score"] for r in rs]
        dim_avgs = {d: round(sum(r2["judge_dims"][0].get(d, 0) + r2["judge_dims"][1].get(d, 0)
                                 for r2 in rs) / (2 * len(rs)), 2) for d in DIMS}
        summary.append({"variant": vname, "n": len(rs),
                        "total": round(sum(scores) / len(scores), 2),
                        "floor": round(min(scores), 2),
                        "dim_avgs": dim_avgs})

    base = next((s for s in summary if s["variant"] == baseline_var), None)
    lines = ["# 质量盲评报告（评委子代理票 · rubric v2 · %s）" % id_, "",
             "票源：%s.votes_JA/JB.json ｜ 样本包：%s ｜ 基线：%s"
             % (id_, pkg, baseline_var), ""]
    verdict_ok = True
    for s in summary:
        if base and s["variant"] != baseline_var:
            d_total = round(s["total"] - base["total"], 2)
            d2 = round(s["dim_avgs"]["D2"] - base["dim_avgs"]["D2"], 2)
            d4 = round(s["dim_avgs"]["D4"] - base["dim_avgs"]["D4"], 2)
            worst_dim = max(DIMS, key=lambda d: base["dim_avgs"][d] - s["dim_avgs"][d])
            d_worst = round(base["dim_avgs"][worst_dim] - s["dim_avgs"][worst_dim], 2)
            ok = (d2 >= GATE_FLOOR and d4 >= GATE_FLOOR and d_total >= TOTAL_FLOOR)
            verdict_ok = verdict_ok and ok
            lines.append("| %s | 总分 %.2f (%+.2f) | 地板 %.2f | 样本 %d | "
                         "D2 %+.2f / D4 %+.2f | 最大单维跌幅 %.1f（%s） | 判定：%s |"
                         % (s["variant"], s["total"], d_total, s["floor"], s["n"],
                            d2, d4, d_worst, worst_dim,
                            "✅ 通过" if ok else "❌ 不通过"))
        elif base:
            lines.append("| %s | 总分 %.2f (基线) | 地板 %.2f | 样本 %d | — | 判定：基线 |"
                         % (s["variant"], s["total"], s["floor"], s["n"]))
        else:
            lines.append("| %s | 总分 %.2f | 地板 %.2f | 样本 %d | — | 判定：（无基线） |"
                         % (s["variant"], s["total"], s["floor"], s["n"]))
    lines += ["", "## 逐样本", "", "| 样本 | 变体 | 分 | 票 | 分歧 |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %d | %s |"
                     % (r["sample"], r["variant"],
                        "%.2f" % r["score"] if r["score"] is not None else "缺票",
                        r["votes"], "是" if r["dispute"] else ""))
    if quote_violations:
        lines += ["", "## 引文验真违规（%d 条）" % len(quote_violations), ""]
        for qv in quote_violations:
            lines.append("- %s %s：%s" % (qv["judge"], qv["sample"], "；".join(qv["bad"])))
    lines += ["", "总判定：%s（判据：D2/D4 ≥ %.1f、总分 ≥ %.1f；引文违规 %d 条）"
              % ("✅ 通过" if verdict_ok and not quote_violations else "❌ 不通过",
                 GATE_FLOOR, TOTAL_FLOOR, len(quote_violations))]
    out = os.path.join(BLIND_DIR, "quality_report_blind_%s.md" % id_)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("[done] 报告：%s" % out)
    for ln in lines:
        if ln.startswith(("|", "总判定")):
            print("  " + ln)
    return 0 if verdict_ok and not quote_violations else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="盲评样本包打包/聚合仪器（v16 P4b）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("pack")
    p1.add_argument("--id", required=True)
    p1.add_argument("--variants", nargs="+", required=True,
                    help="名=目录:章号逗号列表（可多个）")
    p1.add_argument("--seed", type=int, default=7)
    p2 = sub.add_parser("aggregate")
    p2.add_argument("--id", required=True)
    p2.add_argument("--baseline-var", default="anchor_baseline")
    args = ap.parse_args(argv)
    if args.cmd == "pack":
        return cmd_pack(args.id, args.variants, args.seed)
    return cmd_aggregate(args.id, args.baseline_var)


if __name__ == "__main__":
    sys.exit(main())
