# -*- coding: utf-8 -*-
"""Wave C 走查证据收集器（C-2/C-4 配套，R16 自证）。

用法：用户在应用内走查（全程对话落盘默认开）之后，运行：
    python tests/collect_walkthrough_evidence.py <书项目目录>
输出到 <书项目目录>/walkthrough_evidence/：
  - 调用清单.csv        每行一次 HTTP 请求（ts/章/相位/槽位/模型/outcome/attempt/耗时/token）
  - base_url_model 清单.txt   本次真发起过请求的 base_url+model 去重清单（R16 自证）
  - 汇总.txt            调用次数 / token / 金额估算（按用户提供的单价，缺省不计价）
注意：dialogue JSONL 落盘时已过 secrets.redact_text；本脚本不新增任何请求。
"""
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def collect(proj: str, price_per_1m_prompt: float = None,
            price_per_1m_completion: float = None) -> dict:
    d = os.path.join(proj, ".dialogue")
    rows = []
    for fn in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        for ln in open(fn, encoding="utf-8"):
            if not ln.strip():
                continue
            e = json.loads(ln)
            u = e.get("usage") or {}
            rows.append({
                "ts": e.get("ts", ""),
                "chapter": e.get("chapter", 0),
                "phase": e.get("phase", ""),
                "slot": e.get("slot", ""),
                "model": e.get("model", ""),
                "outcome": e.get("outcome", ""),
                "attempt": e.get("attempt", 0),
                "latency_s": e.get("latency_s", 0),
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "total_tokens": u.get("total_tokens", 0),
            })
    combos = sorted({(r["slot"], r["model"]) for r in rows if r["model"] or r["slot"]})
    tok_p = sum(int(r["prompt_tokens"] or 0) for r in rows)
    tok_c = sum(int(r["completion_tokens"] or 0) for r in rows)
    cost = None
    if price_per_1m_prompt is not None and price_per_1m_completion is not None:
        cost = tok_p / 1e6 * price_per_1m_prompt + tok_c / 1e6 * price_per_1m_completion
    return {"rows": rows, "combos": combos, "calls": len(rows),
            "prompt_tokens": tok_p, "completion_tokens": tok_c, "cost": cost}


def write_report(proj: str, price_p=None, price_c=None) -> str:
    res = collect(proj, price_p, price_c)
    out_dir = os.path.join(proj, "walkthrough_evidence")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "调用清单.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res["rows"][0].keys()) if res["rows"] else
                           ["ts", "chapter", "phase", "slot", "model", "outcome",
                            "attempt", "latency_s", "prompt_tokens",
                            "completion_tokens", "total_tokens"])
        w.writeheader()
        w.writerows(res["rows"])

    with open(os.path.join(out_dir, "base_url_model_清单.txt"), "w", encoding="utf-8") as f:
        f.write("本次真发起过请求的 base_url+model 清单（去重）：\n")
        for slot, model in res["combos"]:
            f.write(f"  slot={slot or '-'}  model={model or '-'}\n")

    cost_line = ("金额：未计价（提供单价后重跑可算）" if res["cost"] is None
                 else f"金额估算：¥{res['cost']:.4f}")
    with open(os.path.join(out_dir, "汇总.txt"), "w", encoding="utf-8") as f:
        f.write(f"调用次数：{res['calls']}\n"
                f"prompt tokens：{res['prompt_tokens']}\n"
                f"completion tokens：{res['completion_tokens']}\n{cost_line}\n")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python tests/collect_walkthrough_evidence.py <书项目目录> "
              "[每百万 prompt 单价] [每百万 completion 单价]", flush=True)
        sys.exit(2)
    proj = sys.argv[1]
    pp = float(sys.argv[2]) if len(sys.argv) > 2 else None
    pc = float(sys.argv[3]) if len(sys.argv) > 3 else None
    out = write_report(proj, pp, pc)
    print(f"证据已写入 {out}", flush=True)
    sys.exit(0)
