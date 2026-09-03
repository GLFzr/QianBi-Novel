# -*- coding: utf-8 -*-
"""L1 金标回放探针（P4）：真审校槽对 15 条 L1 金标逐章判分

金标来源：tests/evals/gold_set.json（自 TUI evals/gold_set.json 移植）；
夹具章节：tests_output/l1_fixtures/<preset>/（make_l1_fixtures 确定性生成，
缺失时本探针自动补生成——无 LLM、可重复）。
与 TUI evals/replay.py 的差别：这里跑的是 GUI 产品审校链路
（FINAL_REVIEW_PROMPT 装配 + 多轮投票 + 引证验真 + merge_review_votes），
不是 evals 专用 judge——评测对象即生产代码。

指标：
  - 拦截率   金标 fail → 判 fail；金标 marginal → marginal/fail（≥80% 验收）
  - 误杀     金标 pass → 判 fail（≤1 条验收）
  - 引证真实率 各票 fail/marginal 条目引证过 verify_quote 的比例（≥95%）
  - 投票一致率 各章 k 票间维度等级图两两一致比例（votes≥2 时）
  - prompt-hash FINAL_REVIEW_PROMPT 模板 sha256 前 16 位（改版前后比对）

用法（opt-in，手动）：
  set QIANBI_GOLD_PROBE=1 && .venv\\Scripts\\python.exe tests/probe_review_gold.py
  set QIANBI_GOLD_PROBE_VOTES=1          # 降成本：单票
  set QIANBI_GOLD_PROBE_SAMPLE=5         # 固定种子抽样 5 条
"""
import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

from app import config as cfg_mod
from app import prompts
from app.core import stages
from app.llm import clean_llm_output
from app.llm.router import ModelRouter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_PATH = os.path.join(ROOT, "tests", "evals", "gold_set.json")
FIXTURE_BASE = os.path.join(ROOT, "tests_output", "l1_fixtures")
OUT_DIR = os.path.join(ROOT, "tests_output", "review_gold")


def _ensure_fixtures():
    """夹具缺失时用 make_l1_fixtures 确定性补生成（无 LLM）"""
    if os.path.isdir(FIXTURE_BASE):
        return
    sys.path.insert(0, os.path.join(ROOT, "tests", "evals"))
    import make_l1_fixtures
    make_l1_fixtures.generate()


def _fixture_project(preset_id: str) -> str:
    p = os.path.join(FIXTURE_BASE, preset_id, "proj", "预设测试书")
    return p if os.path.isdir(p) else ""


def _read_chapter(proj: str, chapter: int) -> str:
    for name in (f"第{chapter:03d}章.md", f"第{chapter}章.md"):
        p = os.path.join(proj, "正文", name)
        if os.path.isfile(p):
            return open(p, encoding="utf-8").read()
    return ""


class _Ctx:
    def __init__(self, proj, cfg):
        self.proj = proj
        self.cfg = cfg


def _judge_hit(gold_level: str, judge_level: str):
    """金标语义 → (是否拦截, 是否误杀)——与 TUI replay._judge_hit 一致"""
    if judge_level not in ("pass", "marginal", "fail"):
        return False, False
    if gold_level == "fail":
        return judge_level == "fail", False
    if gold_level == "marginal":
        return judge_level in ("marginal", "fail"), False
    if judge_level == "fail":
        return False, True
    return True, False


def main():
    if os.environ.get("QIANBI_GOLD_PROBE") != "1":
        print("跳过：L1 金标回放为 opt-in（真 LLM 成本）。"
              "设 QIANBI_GOLD_PROBE=1 手动运行。")
        return 0

    cfg = cfg_mod.load_config()
    if not cfg_mod.slot_connection(cfg, cfg_mod.SLOT_REVIEW):
        print("SKIP：审校槽未绑定连接")
        return 0
    _ensure_fixtures()
    router = ModelRouter(cfg)
    client = router.client(cfg_mod.SLOT_REVIEW)
    gates = cfg.get("gates", {})
    votes = int(os.environ.get("QIANBI_GOLD_PROBE_VOTES")
                or gates.get("review_votes", 3))
    temp = gates.get("review_temperature", 0.2)

    gold = json.load(open(GOLD_PATH, encoding="utf-8"))
    l1 = [r for r in gold if r.get("type") == "l1"]
    sample_n = int(os.environ.get("QIANBI_GOLD_PROBE_SAMPLE") or 0)
    if 0 < sample_n < len(l1):
        import random
        l1 = random.Random(20260828).sample(l1, sample_n)
        print(f"抽样 {sample_n} 条（固定种子）")

    prompt_hash = hashlib.sha256(prompts.FINAL_REVIEW_PROMPT.encode()).hexdigest()[:16]
    print(f"L1 金标回放：{len(l1)} 条 · votes={votes} · temp={temp}"
          f" · prompt-hash={prompt_hash} · 审校槽={router.slot_display(cfg_mod.SLOT_REVIEW)}")

    cache = {}      # (preset, chapter) -> {"verdict","dims","votes":[parsed...]}
    results = []
    hit = miss = fk = nd = 0
    quote_total = quote_ok = 0
    pair_total = pair_same = 0

    for r in l1:
        preset, chap, dim = r.get("source_preset", ""), r.get("source_chapter", 0), r.get("dim", "")
        key = (preset, chap)
        if key not in cache:
            proj = _fixture_project(preset)
            prose = _read_chapter(proj, chap) if proj else ""
            if len(prose) < 100:
                cache[key] = {"error": "no_fixture"}
            else:
                print(f"  审校 {preset} ch{chap}（{len(prose)} 字 × {votes} 票）…", flush=True)
                ctx = _Ctx(proj, cfg)
                prompt = stages._build_final_review_prompt(ctx, chap, prose)
                parsed_list = []
                for i in range(votes):
                    raw = client.chat_stream(prompt, on_chunk=None, temperature=temp)
                    raw = clean_llm_output(raw)
                    parsed = stages.verify_review_quotes(prose, stages.parse_final_review_v2(raw))
                    parsed_list.append(parsed)
                    for it in parsed.get("items", []):
                        q = (it.get("quote") or "").strip()
                        if q and it.get("level") in ("fail", "marginal"):
                            quote_total += 1
                            quote_ok += 1 if it.get("quote_verified") else 0
                    if i < votes - 1 and votes > 1:
                        print(f"    第 {i + 1}/{votes} 票：{parsed.get('verdict') or '格式未识别'}"
                              f"（fail={parsed['summary']['fail']}）", flush=True)
                if votes > 1:
                    for a in range(votes):
                        for b in range(a + 1, votes):
                            pair_total += 1
                            pair_same += 1 if stages._votes_identical(parsed_list[a], parsed_list[b]) else 0
                merged = stages.merge_review_votes(parsed_list) if votes > 1 else parsed_list[0]
                cache[key] = {
                    "verdict": merged.get("verdict"),
                    "dims": {it["dim"]: it for it in merged.get("items", [])},
                    "summary": merged.get("summary"),
                }
            st = cache[key]
            if st.get("error"):
                print(f"    夹具缺失：{preset} ch{chap}")
            else:
                print(f"    聚合：{st['verdict']}（fail={st['summary']['fail']}）")

        st = cache[key]
        rec = {"id": r.get("id"), "preset": preset, "chapter": chap, "dim": dim,
               "gold_level": r.get("level"), "judge_level": None, "verdict": "NO_DATA"}
        if st.get("error") or dim not in st.get("dims", {}):
            nd += 1
            rec["reason"] = st.get("error", "维度缺失（解析未报该维）")
        else:
            jl = st["dims"][dim].get("level", "pass")
            rec["judge_level"] = jl
            rec["judge_quote"] = (st["dims"][dim].get("quote", "") or "")[:80]
            ok, false_kill = _judge_hit(r.get("level"), jl)
            if false_kill:
                fk += 1
                rec["verdict"] = "FALSE_KILL"
            elif ok:
                hit += 1
                rec["verdict"] = "HIT"
            else:
                miss += 1
                rec["verdict"] = "MISS"
        results.append(rec)

    total = len(l1)
    rate = hit / total if total else 0.0
    quote_rate = quote_ok / quote_total if quote_total else 1.0
    agree_rate = pair_same / pair_total if pair_total else None
    accept = rate >= 0.8 and fk <= 1 and quote_rate >= 0.95
    summary = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "prompt_hash": prompt_hash, "votes": votes,
        "total": total, "hit": hit, "miss": miss, "false_kill": fk, "no_data": nd,
        "rate": round(rate, 4),
        "quote_truth_rate": round(quote_rate, 4),
        "vote_agreement": round(agree_rate, 4) if agree_rate is not None else None,
        "accept": bool(accept), "results": results,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    fname = f"judge_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json.dump(summary, open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(summary, open(os.path.join(OUT_DIR, "l1_judge_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print("\n" + "=" * 64)
    print(f"L1 金标回放：拦截 {hit}/{total}（{rate:.1%}） 误杀={fk} 无数据={nd}")
    print(f"引证真实率 {quote_rate:.1%}（{quote_ok}/{quote_total}）"
          + (f"  投票一致率 {agree_rate:.1%}" if agree_rate is not None else ""))
    print(f"验收（拦截≥80% 且 误杀≤1 且 引证真实率≥95%）：{'PASS' if accept else 'FAIL'}")
    for rec in results:
        if rec["verdict"] != "HIT":
            print(f"  - {rec['id']} {rec['dim']} gold={rec['gold_level']} "
                  f"judge={rec.get('judge_level')} → {rec['verdict']} {rec.get('reason', '')}")
    print("=" * 64)
    return 0 if accept else 1


if __name__ == "__main__":
    sys.exit(main())
