# -*- coding: utf-8 -*-
"""Agent 指令黄金集评测器：规则层（L1）与 LLM 兜底（L2）的准确率/误触发/成本报告

用法：
  python scripts/agent_eval.py              # L1 报告
  python scripts/agent_eval.py --llm        # L2：规则未命中时走 LLM 兜底（真机）
  python scripts/agent_eval.py --verbose    # 逐条明细
"""
from __future__ import annotations

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

DATA = os.path.join(ROOT, "tests", "evals", "agent_instructions.json")
DEFAULT_CH = 5


def _load():
    path = DATA
    if "--holdout" in sys.argv:
        path = os.path.join(ROOT, "tests", "evals", "agent_instructions_holdout.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["cases"]


def _args_match(got: dict, want: dict) -> tuple:
    """args 关键字段匹配：精确键相等 / guidance_has 子串；返回 (ok, reason)"""
    for k, wv in (want or {}).items():
        gv = (got or {}).get(k)
        if k == "guidance_has":
            gv = (got or {}).get("guidance")
            if wv not in str(gv or ""):
                return (False, "guidance 缺「%s」（实际：%r）" % (wv, gv))
        elif isinstance(wv, bool) or isinstance(gv, bool):
            if bool(gv) != bool(wv):
                return (False, "%s: 期望 %s 实际 %s" % (k, wv, gv))
        elif gv != wv:
            return (False, "%s: 期望 %s 实际 %s" % (k, wv, gv))
    return (True, "")


def _judge(case, result, cat):
    """返回 (verdict, reason)：verdict ∈ hit / miss / false_trigger / clarify_ok / clarify_miss"""
    want_tool = case.get("tool")
    if want_tool is None:
        if cat == "C":
            return ("hard_guess", "歧义被硬猜为 %r（应澄清）" % (result,)) if result else ("hit", "")
        return ("false_trigger", "非指令被触发：%r" % (result,)) if result else ("hit", "")
    if result is None:
        return ("clarify_miss" if cat == "C" else "miss",
                "应触发 %s 却未识别" % want_tool)
    tool, args, conf = result
    if cat == "C":
        # 歧义类：识别出来了但猜错了才算错；识别为强猜也记 clarify_miss
        if tool != want_tool:
            return ("false_trigger", "歧义被猜成 %s" % tool)
        return ("clarify_miss", "歧义被硬猜（应澄清）")
    if tool != want_tool:
        return (cat == "D" and "false_trigger" or "miss", "工具错：期望 %s 实际 %s" % (want_tool, tool))
    ok, why = _args_match(args, case.get("args") or {})
    if not ok:
        return ("miss", "参数错：" + why)
    return ("hit", "")


def main():
    verbose = "--verbose" in sys.argv
    use_llm = "--llm" in sys.argv
    cases = _load()
    from app.core import agent_tools as at

    llm_calls = 0
    llm_tokens = 0
    stats = {c: {"total": 0} for c in "ABCD"}
    details = []
    client = None
    if use_llm:
        from app import config as cfg_mod, secrets
        from app.llm.client import LLMClient
        cfg = secrets.hydrate(cfg_mod.load_config())
        conn = next((c for c in cfg.get("connections", []) if c.get("api_key")
                     and c.get("id") == "cap-flash"), None) or \
            next((c for c in cfg.get("connections", []) if c.get("api_key")), None)
        client = LLMClient.from_connection(conn, max_retries=1, slot="agent_eval")

    for case in cases:
        cat = case["cat"]
        stats[cat]["total"] += 1
        result = at.parse_instruction(case["text"], default_chapter=case.get("default_chapter", DEFAULT_CH))
        if result is None and use_llm and client is not None and case["cat"] != "D":
            llm = at.parse_instruction_llm(case["text"], client,
                                           default_chapter=case.get("default_chapter", DEFAULT_CH))
            if llm is not None:
                result = llm
                llm_calls += 1
        verdict, reason = _judge(case, result, cat)
        key = {"hit": "hit", "miss": "miss", "false_trigger": "false",
               "hard_guess": "hard_guess",
               "clarify_ok": "hit", "clarify_miss": "miss"}.get(verdict, verdict)
        stats[cat][key] = stats[cat].get(key, 0) + 1
        details.append({"cat": cat, "text": case["text"][:40], "verdict": verdict,
                        "reason": reason, "got": result})

    def _rate(cat, key):
        t = stats[cat]["total"]
        return stats[cat].get(key, 0) / t * 100 if t else 0.0

    a_hit = _rate("A", "hit")
    b_hit = _rate("B", "hit")
    d_false = _rate("D", "false")
    ab_total = stats["A"]["total"] + stats["B"]["total"]
    ab_hit = (stats["A"].get("hit", 0) + stats["B"].get("hit", 0)) / ab_total * 100
    c_clarify = _rate("C", "false")   # C 类不猜 = 通过

    tag = "对抗集" if "--holdout" in sys.argv else "黄金集"
    print("== Agent 指令评测（%s · %s）==" % (tag, "L1 规则层" if not use_llm else "L1+L2 LLM兜底"))
    print("A 明确指令命中 : %5.1f%% (%d/%d)" % (a_hit, stats["A"].get("hit", 0), stats["A"]["total"]))
    print("B 口语化命中   : %5.1f%% (%d/%d)" % (b_hit, stats["B"].get("hit", 0), stats["B"]["total"]))
    print("A+B 综合理解率 : %5.1f%% (%d/%d)" % (ab_hit, stats["A"].get("hit", 0) + stats["B"].get("hit", 0), ab_total))
    print("D 误触发率     : %5.1f%% (%d/%d)  ← 红线 ≤1%%"
          % (d_false, stats["D"].get("false", 0), stats["D"]["total"]))
    c_t = stats["C"]["total"]
    print("C 歧义硬猜率   : %5.1f%% (%d/%d)  ← 越低越好"
          % (stats["C"].get("hard_guess", 0) / c_t * 100 if c_t else 0,
             stats["C"].get("hard_guess", 0), c_t))
    if use_llm:
        print("LLM 兜底调用   : %d 次" % llm_calls)
    if verbose:
        for d in details:
            if d["verdict"] != "hit":
                print("  [%s/%s] %s → %s %s" % (d["cat"], d["verdict"], d["text"], d["got"], d["reason"]))


if __name__ == "__main__":
    main()
