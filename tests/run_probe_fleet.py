# -*- coding: utf-8 -*-
"""WP-06/WP-01 探针舰队驱动：串行跑、每支取真退码（subprocess returncode）+
探针自打结论行；任一支失败/超时/无结论行 → 本驱动非零退码（CI 门禁用）。
用法: python tests/run_probe_fleet.py <probe1> <probe2> ...

A-2（v4）：①子进程 env 钉 PYTHONIOENCODING=utf-8（GBK 控制台不再让 print 非
ASCII 字符自崩）；②stderr 与 stdout 合并留档到 .tmp_fleet_logs/<probe>.log
——红了能看到 traceback，而不是只剩一行结论。
"""
import os
import re
import subprocess
import sys
import time

PROBES = sys.argv[1:]
if not PROBES:
    print("用法: python tests/run_probe_fleet.py <probe...>", flush=True)
    sys.exit(2)
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".tmp_fleet_logs")
os.makedirs(LOG_DIR, exist_ok=True)
ENV = dict(os.environ)
ENV["PYTHONIOENCODING"] = "utf-8"   # A-2①：GBK 控制台下 probe print 非 ASCII 不再崩
results = []
for name in PROBES:
    t0 = time.time()
    log_path = os.path.join(LOG_DIR, f"{name}.log")
    try:
        p = subprocess.run([sys.executable, f"tests/{name}.py"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=220,
                           env=ENV)
        rc = p.returncode
        out = (p.stdout or "") + (p.stderr or "")   # A-2②：stderr 一起留档
    except subprocess.TimeoutExpired as e:
        rc = "TIMEOUT"
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(out)
    dt = time.time() - t0
    m = re.findall(r"(PROBE_DONE \w+|TOTAL \d+ / \d+)", out)
    conclusion = m[-1] if m else "(无结论行)"
    results.append((name, rc, conclusion, dt))
    print(f"[fleet] {name}: rc={rc} {conclusion} ({dt:.0f}s) log={log_path}", flush=True)

print("\n=== 舰队汇总 ===")
bad = []
for name, rc, conclusion, dt in results:
    print(f"{name}\trc={rc}\t{conclusion}")
    if rc != 0 or conclusion == "(无结论行)":
        bad.append(f"{name}(rc={rc},{conclusion})")
if bad:
    print("探针失败：" + "，".join(bad), flush=True)
    sys.exit(1)
print(f"PROBE_DONE PASS（{len(results)} 支全绿）", flush=True)
