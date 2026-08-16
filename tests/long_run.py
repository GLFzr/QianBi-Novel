# -*- coding: utf-8 -*-
"""长任务测试：将《改命笔记》扩写到 10 万字（可多轮续跑）

- 基于现有设定/大纲/已写章节断点续跑，按正常使用逻辑跑完整流水线
- 每轮最多写 MAX_CHAPTERS_THIS_ROUND 章（默认 4），达到本轮上限或累计 10 万字即停
- 重复运行自动续跑（pipeline_state 断点 + 已有文件跳过）
- 模型：OpenCode Go · deepseek-v4-flash · thinking enabled · effort max
- 用法：.venv/Scripts/python.exe tests/long_run.py [项目路径] [本轮章数上限]
"""
import json
import os
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from app import project
from app.core import state as st
from app.core.orchestrator import Orchestrator

# ---------- 测试约定 ----------
MODEL = "deepseek-v4-flash"
BASE = os.environ.get("QIANBI_TEST_BASE", "https://opencode.ai/zen/go/v1")
KEY = os.environ.get("QIANBI_TEST_KEY", "")
if not KEY:
    cfg_path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg0 = json.load(f)
        for c in cfg0.get("connections", []):
            if c.get("base_url", "").find("opencode") >= 0 and c.get("api_key"):
                KEY = c["api_key"]
                BASE = c.get("base_url", BASE)
                break
    except Exception:
        pass
assert KEY, "未找到 OpenCode Go Key（设 QIANBI_TEST_KEY 或 ~/.qianbi_novel/config.json）"

THINKING = "enabled"
EFFORT = "max"
CHAPTER_WORDS = 2000            # 每章目标字数（与示例细纲一致）
TOTAL_WORDS_TARGET = 100000     # 累计 10 万字达标

SRC_PROJ = os.path.join(os.getcwd(), "examples", "改命笔记")
DEFAULT_PROJ = os.path.join(os.getcwd(), "tests_output", "长测_改命笔记")
PROGRESS_LOG = os.path.join(os.getcwd(), "tests_output", "long_run_progress.log")


def mark(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROJ
    max_chapters = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    # 首次运行：从示例复制一份（不污染仓库示例）
    if not os.path.isdir(proj):
        assert os.path.isdir(SRC_PROJ), f"示例项目不存在: {SRC_PROJ}"
        import shutil
        os.makedirs(os.path.dirname(proj), exist_ok=True)
        shutil.copytree(SRC_PROJ, proj)
        mark(f"[init] 已从示例复制项目 → {proj}")

    cfg = {
        "connections": [
            {"id": "t-write", "name": f"{MODEL}（写作槽）", "provider": "custom",
             "base_url": BASE, "api_key": KEY, "model": MODEL,
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": THINKING, "reasoning_effort": EFFORT},
            {"id": "t-helper", "name": f"{MODEL}（辅助槽）", "provider": "custom",
             "base_url": BASE, "api_key": KEY, "model": MODEL,
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": THINKING, "reasoning_effort": EFFORT},
        ],
        "slots": {"writing": "t-write", "helper": "t-helper", "review": "t-helper"},
        "gates": {"strategy": "mark_continue", "deslop_max_rounds": 2,
                  "word_tolerance": 0.1, "review_enabled": True, "review_max_rounds": 1},
        "llm": {"max_retries": 1, "backoff_base": 2.0},
        "writing": {"chapter_word_target": CHAPTER_WORDS, "default_genre": "",
                    "default_platform": "番茄"},
        "last_project": "",
        "recent_projects": [],
    }

    app = QGuiApplication(sys.argv)

    def total_words():
        return sum(len(project.read_file(p)) for _, _, p in project.list_chapters(proj))

    chapters_before = len(project.list_chapters(proj))
    words_before = total_words()
    mark(f"[init] 当前 {chapters_before} 章 / {words_before} 字（目标 {TOTAL_WORDS_TARGET} 字，本轮上限 {max_chapters} 章）")

    logs = []
    fail = {"msg": ""}

    def on_log(level, msg):
        mark(f"  {msg}")

    def on_finished(reason):
        mark(f"[e2e] 流水线结束: {reason}")

    def on_failed(msg):
        fail["msg"] = msg
        mark(f"[e2e] 流水线失败: {msg}")

    orch = Orchestrator(proj, cfg)
    orch.sig_log.connect(on_log, Qt.DirectConnection)
    orch.sig_finished.connect(on_finished, Qt.DirectConnection)
    orch.sig_failed.connect(on_failed, Qt.DirectConnection)

    t0 = time.monotonic()
    mark(f"[run] 启动流水线（{MODEL} thinking={THINKING} effort={EFFORT}）…")
    orch.start()

    TIMEOUT = 100 * 60
    last_beat = time.monotonic()
    done_this_round = 0
    while orch.isRunning() and time.monotonic() - t0 < TIMEOUT:
        app.processEvents()
        time.sleep(0.2)
        if time.monotonic() - last_beat > 30:
            last_beat = time.monotonic()
            mark(f"[beat] 存活 {time.monotonic()-t0:.0f}s 本轮新章 {done_this_round} 累计 {len(project.list_chapters(proj))} 章 {total_words()} 字")
        # 每章完成后检查：达标或达到本轮上限 → 请求停止
        n = len(project.list_chapters(proj))
        if n > chapters_before + done_this_round:
            done_this_round = n - chapters_before
            mark(f"[check] 本轮已完成 {done_this_round} 章，累计 {n} 章 {total_words()} 字")
            if total_words() >= TOTAL_WORDS_TARGET or done_this_round >= max_chapters:
                orch.stop()
                mark(f"[run] 达到停止条件（{total_words()} 字 / 本轮 {done_this_round} 章），请求停止…")
    app.processEvents()

    chapters_after = len(project.list_chapters(proj))
    words_after = total_words()
    mark(f"[run] 本轮结束：新增 {chapters_after - chapters_before} 章，累计 {chapters_after} 章 / {words_after} 字，耗时 {time.monotonic()-t0:.0f}s")

    if fail["msg"]:
        print("RUN_FAILED:", fail["msg"], flush=True)
        dbg = os.path.join(proj, "pipeline_debug")
        if os.path.isdir(dbg):
            for f in sorted(os.listdir(dbg))[-3:]:
                print(f"--- pipeline_debug/{f} ---", flush=True)
                print(project.read_file(os.path.join(dbg, f))[:1500], flush=True)
        return 1

    # 汇总
    state = st.load_state(proj)
    print("\n========== 长任务本轮汇总 ==========", flush=True)
    print(f"章节: {chapters_after}（本轮 +{chapters_after - chapters_before}）", flush=True)
    print(f"字数: {words_after}（目标 {TOTAL_WORDS_TARGET}，进度 {words_after / TOTAL_WORDS_TARGET * 100:.1f}%）", flush=True)
    hist = state.get("history", [])
    if hist:
        pass_n = sum(1 for h in hist if h.get("status") == "pass")
        fix_n = sum(1 for h in hist if h.get("status") == "needs_fix")
        print(f"闸门: 通过 {pass_n} / 待修 {fix_n}", flush=True)
        deslop = sum(h.get("deslop_blocking", 0) for h in hist)
        review = sum(h.get("review_blocking", 0) for h in hist)
        print(f"累计阻断: 去味 {deslop} 处 / 审校 {review} 处", flush=True)
    print(f"tokens: {orch.router.total_tokens()} | 成本估算 ¥{orch.router.estimate_cost():.2f}", flush=True)
    print("LONG_RUN_ROUND_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
