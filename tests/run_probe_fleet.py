# -*- coding: utf-8 -*-
"""WP-06 探针舰队驱动：串行跑、每支取真退码（subprocess returncode）+ 探针自打结论行。
用法: python tests/run_probe_fleet.py <probe1> <probe2> ...
"""
import re
import subprocess
import sys
import time

PROBES = sys.argv[1:]
results = []
for name in PROBES:
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, f"tests/{name}.py"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=220,
                           env=None)
        rc = p.returncode
        out = p.stdout or ""
    except subprocess.TimeoutExpired:
        rc = "TIMEOUT"
        out = ""
    dt = time.time() - t0
    m = re.findall(r"(PROBE_DONE \w+|TOTAL \d+ / \d+)", out)
    conclusion = m[-1] if m else "(无结论行)"
    results.append((name, rc, conclusion, dt))
    print(f"[fleet] {name}: rc={rc} {conclusion} ({dt:.0f}s)", flush=True)

print("\n=== 舰队汇总 ===")
for name, rc, conclusion, dt in results:
    print(f"{name}\trc={rc}\t{conclusion}")
