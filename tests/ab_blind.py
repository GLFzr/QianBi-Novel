# -*- coding: utf-8 -*-
"""0.24.0 Q1-b 三臂盲评：9 稿（compact/fresh/legacy × 第3-5章）匿名乱序，
stealth 独立评委（与被测写手同模型——三臂对称故偏置恒定），长度配平。

用法：QIANBI_TEST_KEY=... python tests/ab_blind.py
"""
import json
import os
import random
import sys
import time

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

sys.path.insert(0, os.path.join(_ROOT, "tests"))
from quality_suite import RUBRIC, _ask, _client, _json_block, _length_normalize  # noqa: E402

from app import project  # noqa: E402

OUT = os.path.join(_ROOT, "tests_output", "_quality_ab_arms.json")
ARMS = ("compact", "fresh", "legacy")


def main():
    t0 = time.time()
    samples = []   # (arm, chapter, text)
    for arm in ARMS:
        proj = os.path.join(_ROOT, "tests_output", f"or_ab_{arm}")
        for n, _t, p in project.list_chapters(proj):
            if 3 <= n <= 5:
                samples.append((arm, n, project.read_file(p)))
    rng = random.Random(20241003)
    rng.shuffle(samples)
    labels = {i: f"稿-{i + 1:02d}" for i in range(len(samples))}
    truth = {labels[i]: {"arm": a, "chapter": n} for i, (a, n, _t) in enumerate(samples)}
    judge = _client(True)
    results = {}
    for i, (arm, n, text) in enumerate(samples):
        lab = labels[i]
        raw = _ask(judge, f"{RUBRIC}\n\n待评正文（{lab}）：\n{_length_normalize(text)}",
                   "ab_arms_blind")
        j = _json_block(raw) or {}
        results[lab] = {"arm": arm, "chapter": n, "scores": j.get("scores") or {},
                        "总评": j.get("总评") or ""}
        dims = {k: v for k, v in (j.get("scores") or {}).items()
                if isinstance(v, (int, float))}
        mean = round(sum(dims.values()) / len(dims), 1) if dims else None
        print(f"[{time.strftime('%H:%M:%S')}] {lab}（{arm} 第{n}章）均分 {mean}", flush=True)
    # 汇总
    summary = {}
    for arm in ARMS:
        rows = [r for r in results.values() if r["arm"] == arm]
        per = {}
        for r in rows:
            dims = [v for v in r["scores"].values() if isinstance(v, (int, float))]
            if dims:
                per.setdefault("means", []).append(round(sum(dims) / len(dims), 2))
        summary[arm] = {"means": per.get("means", []),
                        "avg": round(sum(per.get("means", [])) / max(len(per.get("means", [])), 1), 2)}
    out = {"truth": truth, "results": results, "summary": summary,
           "protocol": "长度配平[1400,3600]+乱序(seed=20241003)+stealth单评委×1发/稿"}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n=== 三臂盲评汇总（{time.time() - t0:.0f}s）===")
    for arm in ARMS:
        print(f"  {arm:8s} 章均分 {summary[arm]['means']} → 臂均 {summary[arm]['avg']}")


if __name__ == "__main__":
    main()
