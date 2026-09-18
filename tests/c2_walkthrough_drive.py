# -*- coding: utf-8 -*-
"""C-2 真实走查驱动（docs/WaveC执行卡_C2_v1.md 的无头执行器，可按步续跑）。

用法（在仓库根目录）：
    python tests/c2_walkthrough_drive.py <书项目路径> <命令> [参数...]

命令：status / confirm / discuss <文本> / draft / unit <起> <止> [主题] /
     outlines / open <章号> / lock / export / bugreport

- Key 一律走 keyring（hydrate 回填），本脚本不含任何凭据。
- 每次 LLM 调用经 WP-27 对话落盘自动计数（{书}/.dialogue/*.jsonl 每行一次 HTTP）。
- 预算护栏（R16）：单命令超时 7 分钟；超预算即人工停。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtGui import QGuiApplication          # noqa: E402
from PySide6.QtCore import QCoreApplication        # noqa: E402

from app.core import state as st                   # noqa: E402
from app.core import co_dialogue                   # noqa: E402
from app import dialogue_log                       # noqa: E402

TOASTS = []


def _call_count(proj: str) -> int:
    d = os.path.join(proj, ".dialogue")
    n = 0
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".jsonl"):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    n += sum(1 for ln in f if ln.strip())
    return n


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    QCoreApplication.setOrganizationName("qianbi")

    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = __import__("app.config", fromlist=["load_config"]).load_config()
    b.toast.connect(lambda kind, msg: TOASTS.append(f"[{kind}] {msg}"))

    proj = sys.argv[1].replace("file:///", "").replace("file://", "")
    cmd = sys.argv[2] if len(sys.argv) > 2 else "status"
    args = sys.argv[3:]

    if cmd != "status" or not os.path.isdir(proj):
        pass  # 项目在首个动作前按需打开
    if os.path.isdir(proj) and (not b.proj or b.proj != proj):
        b.openProject(proj)

    def stage() -> str:
        return b._get_cw_stage_key() if b.proj else "?"

    def pump_until(desc, cond, timeout=420.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.08)
        print(f"!! 超时：{desc}（{timeout:.0f}s） 最后toast: {TOASTS[-3:]}")
        return False

    def asst_len() -> int:
        s = b._cw.load()
        return len((st.ensure_cw(s).get("transcript", {}).get(stage(), []) or []))

    def wait_reply(desc):
        n0 = asst_len()
        ok = pump_until(desc + "（等 AI 回复）",
                        lambda: (not b._cw_busy) and asst_len() > n0, 420)
        print(("OK  " if ok else "FAIL ") + desc +
              f" | 转写 assistant {n0}->{asst_len()} | 累计调用 {_call_count(proj)}")
        return ok

    def wait_confirm(prev_stage, desc):
        ok = pump_until(desc + "（等总结定稿/阶段推进）",
                        lambda: (not b._cw_busy) and stage() != prev_stage, 420)
        print(("OK  " if ok else "FAIL ") + desc +
              f" | 阶段 {prev_stage} -> {stage()} | 累计调用 {_call_count(proj)}")
        return ok

    if cmd == "status":
        if not b.proj:
            print("未打开项目")
        else:
            s = b._cw.load()
            print(f"项目: {proj}")
            print(f"阶段: {stage()} | busy={b._cw_busy} | mode={st.ensure_cw(s).get('mode')}")
            print(f"转写: { {k: len(v or []) for k, v in st.ensure_cw(s).get('transcript', {}).items()} }")
            print(f"累计调用: {_call_count(proj)}")
        return 0

    if cmd == "confirm":
        prev = stage()
        b.confirmCwStage()
        if prev == st.STAGE_CW_PROJECT:
            ok = pump_until("立项确认", lambda: stage() != prev, 60)
            print(("OK  " if ok else "FAIL ") + f"立项确认 | 阶段 -> {stage()}")
        else:
            wait_confirm(prev, f"确认 {prev}")
        for t in TOASTS[-3:]:
            print("  toast", t)
        return 0

    if cmd == "discuss":
        prev_n = _call_count(proj)
        b.submitCwMessage(args[0], "discuss")
        wait_reply(f"讨论@{stage()}")
        return 0

    if cmd == "draft":
        b.generateCwDraft()
        wait_reply(f"草案@{stage()}")
        return 0

    if cmd == "unit":
        b.setCwUnitRange(int(args[0]), int(args[1]), args[2] if len(args) > 2 else "")
        for t in TOASTS[-1:]:
            print("  toast", t)
        return 0

    if cmd == "outlines":
        b.generateNextCwOutlines()
        wait_reply("生成下一批细纲")
        return 0

    if cmd == "open":
        b.openChapter(int(args[0]))
        print(f"openChapter({args[0]}) _cur_num={b._cur_num}")
        return 0

    if cmd == "lock":
        b.confirmChapterLocked()
        pump_until("锁定闸门回执", lambda: len(TOASTS) > 0, 30)
        for t in TOASTS[-3:]:
            print("  toast", t)
        return 0

    if cmd == "export":
        p = b.exportProjectOpts("txt", "\n\n", 1)
        print("导出:", p or "（失败，见 toast）")
        for t in TOASTS[-2:]:
            print("  toast", t)
        return 0

    if cmd == "bugreport":
        p = b.createBugReport()
        print("报障包:", p)
        return 0

    print(f"未知命令 {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
