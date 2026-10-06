# -*- coding: utf-8 -*-
"""0.24.0 待修章批量修复驱动（无人值守跑完 need_human 章）。

用产品自有 RepairWorker（一键修复同一代码路径：定向修复+最小差异+同一性验收），
多 pass 迭代直到 collect_needs_fix 清空或达到轮次上限。

用法：QIANBI_TEST_KEY=... python tests/repair_drive.py [max_pass=3]
"""
import os
import sys
import time

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

PROJ = os.path.join(_ROOT, "tests_output", "or_二测_改命笔记")
BASE_URL = os.environ.get("QIANBI_TEST_BASE", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("QIANBI_TEST_MODEL", "space-bunny-free")
KEY = os.environ.get("QIANBI_TEST_KEY", "").strip()
MAX_PASS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    assert KEY, "需要 QIANBI_TEST_KEY"
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QEventLoop, QTimer
    app = QGuiApplication(sys.argv)

    from app import config as cfg_mod
    from app.core import state as st
    from app.ui.bridge import ChapterRepairWorker as RepairWorker, collect_needs_fix

    cfg = {"connections": [{
        "id": "oc", "name": "OpenCode Go free", "provider": "custom",
        "base_url": BASE_URL, "api_key": KEY, "model": MODEL,
        "stream": False, "max_tokens": 32768, "timeout": 900,
        "thinking": "", "reasoning_effort": "high",
        "user_id": "qianbi-repair",
    }], "slots": {"writing": "oc", "helper": "oc", "review": "oc"},
        "dialogue_log": {"enabled": False}}

    for p in range(1, MAX_PASS + 1):
        state = st.load_state(PROJ)
        pending = collect_needs_fix(state)
        nhh = sorted(int(k) for k in (state.get("chapter_need_human") or {}))
        log(f"== pass {p}/{MAX_PASS}：待修 {len(pending)} 章，need_human {len(nhh)} 章"
            f"（{nhh[:12]}{'…' if len(nhh) > 12 else ''}）==")
        if not pending:
            log("全部清空 ✓")
            break
        nums = [r["num"] for r in pending]
        worker = RepairWorker(cfg, PROJ, nums)
        results = {}
        loop = QEventLoop()

        def on_done(num, ok, detail):
            results[num] = (ok, detail)
            log(f"  第 {num} 章：{'✓' if ok else '✗'} {detail}")

        def on_log(m):
            log(f"    {m}")

        def on_all(ok, fail):
            log(f"-- pass {p} 完成：成功 {ok} / 失败 {fail}")
            QTimer.singleShot(200, loop.quit)

        worker.sig_chapter_done.connect(on_done, Qt.DirectConnection)
        worker.sig_log.connect(on_log, Qt.DirectConnection)
        worker.sig_all_done.connect(on_all, Qt.DirectConnection)
        worker.start()
        killer = QTimer()
        killer.setSingleShot(True)
        killer.timeout.connect(lambda: (log("pass 超时（3h）"), loop.quit()))
        killer.start(180 * 60 * 1000)
        loop.exec()
        worker.wait(5000)

    state = st.load_state(PROJ)
    pending = collect_needs_fix(state)
    nhh = sorted(int(k) for k in (state.get("chapter_need_human") or {}))
    log(f"== 最终：待修 {len(pending)} 章，need_human {len(nhh)} 章 {nhh} ==")
    for r in pending:
        log(f"  第 {r['num']} 章 status={r.get('status')} verdict={r.get('verdict')} "
            f"blocking={len(r.get('blocking') or [])}")


if __name__ == "__main__":
    main()
