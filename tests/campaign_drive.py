# -*- coding: utf-8 -*-
"""50 万字 × N 本 长程实弹战役驱动（OpenCode Go 免费通道专用）。

设计要点（对应 docs/0.20.4_全量测试与能力评估计划.md 的 L6 层与批次 B6/B8）：
- **顺序多本、按轮推进**：每轮起一个独立子进程（tests/long_run.py）⇒ 崩溃隔离 +
  天然断点续跑（章文件与 pipeline_state 都在盘上）；驱动只负责编排与留证。
- **只许免费模型**：spec 里每个模型 id 必须含 "free"，否则硬退出（防付费误用）。
- **主力+兜底**：连续失败达 strikes_to_fallback 换兜底模型；配额类失败退避后重试。
- **留证**：每轮原始输出落 `_scratch/campaign/rounds/<book>_r<NNN>.log`；
  进度快照落 `progress.json`；追加式人读日志 `campaign.log`。
- **可随时重启**：`python tests/campaign_drive.py --spec <spec>` 幂等续跑。

用法：
    $env:QIANBI_TEST_KEY = "<key>"
    python tests/campaign_drive.py --spec _scratch/campaign/spec.json --max-hours 8
    python tests/campaign_drive.py --spec _scratch/campaign/spec.json --book book01_悬疑代笔
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_scratch", "campaign")
ROUNDS = os.path.join(OUT, "rounds")
PROGRESS = os.path.join(OUT, "progress.json")
CAMP_LOG = os.path.join(OUT, "campaign.log")

QUOTA_MARKERS = ("free-models-per-day", "429", "Endpoint is unavailable",
                 "Model is unavailable", "insufficient", "quota")
FATAL_MARKERS = ("未找到 OpenCode Go Key", "Traceback (most recent call last)")


def mark(msg: str) -> None:
    line = "[%s] %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    os.makedirs(OUT, exist_ok=True)
    with open(CAMP_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def count_words(proj: str) -> tuple:
    """(len 口径总字数, 章数)——与 tests/long_run.py 的 total_words 同口径"""
    d = os.path.join(proj, "正文")
    total = 0
    n = 0
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".md") and not fn.startswith("."):
                n += 1
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        total += len(f.read())
                except OSError:
                    pass
    return total, n


def ensure_book(proj: str, book: dict) -> None:
    """建项目骨架 + 选题信息.md（pipeline 的立项入口，见 app/project.read_idea_info）"""
    os.makedirs(os.path.join(proj, "设定"), exist_ok=True)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
    idea = os.path.join(proj, "设定", "选题信息.md")
    if not os.path.exists(idea):
        doc = ("# 选题信息\n\n- 题材：%s\n- 平台：%s\n- 预计总字数：%d 万字\n- 灵感：%s\n"
               % (book["genre"], book.get("platform", "番茄"),
                  int(book.get("target_words", 500000) // 10000), book["idea"]))
        with open(idea, "w", encoding="utf-8") as f:
            f.write(doc)
        mark("[init] 写入选题信息 → %s" % idea)


def load_progress() -> dict:
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"started": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rounds": [], "books": {}}


def save_progress(p: dict) -> None:
    os.makedirs(OUT, exist_ok=True)
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def run_round(proj: str, chapters: int, model: str, spec: dict, log_path: str) -> dict:
    env = dict(os.environ)
    env.update({
        "QIANBI_TEST_BASE": spec.get("base_url", "https://opencode.ai/zen/go/v1"),
        "QIANBI_TEST_MODEL": model,
        "QIANBI_TEST_STREAM": "false",
        "QIANBI_TEST_MAX_TOKENS": str(spec.get("max_tokens", 32768)),
        "QIANBI_TEST_THINKING": spec.get("thinking", ""),
        "QIANBI_TEST_EFFORT": spec.get("reasoning_effort", ""),
        "QIANBI_TEST_RETRIES": str(spec.get("max_retries", 2)),
        "QIANBI_TEST_TOTAL_WORDS": str(spec.get("hard_total_words", 10 ** 9)),
        "QIANBI_TEST_ROUND_TIMEOUT_MIN": str(spec.get("round_timeout_min", 100)),
        "QIANBI_TEST_USER_ID": spec.get("session_id", "qianbi-campaign"),
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
        # 配置/用量隔离（10-14 补齐）：不设它时 usage 会写进用户真实台账
        # （C:\Users\<u>\.qianbi_novel\usage\usage.jsonl），战役的百万级 tokens 会
        # 混进用户面板；这里钉到仓库内 gitignored 目录，与 tests/or_phase1_drive.py 同款。
        "QIANBI_CONFIG_DIR": spec.get("config_dir",
                                     os.path.join(ROOT, "tests_output", "_campaign_cfg")),
    })
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        p = subprocess.run([sys.executable, os.path.join("tests", "long_run.py"),
                            proj, str(chapters)],
                           cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT,
                           timeout=int(spec.get("round_hard_timeout_min", 150)) * 60)
    dt = time.time() - t0
    with open(log_path, encoding="utf-8", errors="replace") as f:
        out = f.read()
    return {
        "rc": p.returncode, "sec": int(dt), "log": log_path,
        "done": "LONG_RUN_ROUND_DONE" in out,
        "tokens": _grep_int(out, r"tokens: (\d+)"),
        "cost": _grep_float(out, r"成本估算 ¥([\d.]+)"),
        "failed_msg": (out.strip().splitlines()[-1][:200] if p.returncode else ""),
        "text": out,
    }


def _grep_int(text: str, pat: str) -> int:
    m = re.search(pat, text)
    return int(m.group(1)) if m else 0


def _grep_float(text: str, pat: str) -> float:
    m = re.search(pat, text)
    return float(m.group(1)) if m else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--max-hours", type=float, default=8.0)
    ap.add_argument("--book", default="")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    models = [spec["model_primary"]] + list(spec.get("model_fallbacks") or [])
    for m in models:
        if "free" not in m.lower():
            print("拒绝发车：模型 %r 不含 free（本战役只许免费模型）" % m)
            return 2
    if not os.environ.get("QIANBI_TEST_KEY"):
        print("缺少 QIANBI_TEST_KEY（只经环境变量注入，不入仓）")
        return 2

    os.makedirs(ROUNDS, exist_ok=True)
    prog = load_progress()
    deadline = time.time() + args.max_hours * 3600
    books = [b for b in spec["books"] if not args.book or b["name"] == args.book]

    mark("=== 战役开始：%d 本 / 目标 %s 字/本 / 主力 %s / 兜底 %s / 上限 %.1fh ==="
         % (len(books), spec.get("target_words", 500000), models[0],
            ",".join(models[1:]) or "无", args.max_hours))

    for book in books:
        proj = os.path.join(ROOT, "tests_output", "campaign", book["name"])
        ensure_book(proj, book)
        target = int(book.get("target_words", spec.get("target_words", 500000)))
        m_idx, strikes = 0, 0
        st = prog["books"].setdefault(book["name"], {"rounds": 0, "tokens": 0, "cost": 0.0})
        while True:
            words, chs = count_words(proj)
            if words >= target:
                mark("[done] %s 达标：%d 章 / %d 字（目标 %d）" % (book["name"], chs, words, target))
                st["done"] = True
                break
            if time.time() > deadline:
                mark("[stop] 已达 --max-hours 上限；%s 停在 %d 章 / %d 字（可续跑）"
                     % (book["name"], chs, words))
                save_progress(prog)
                return 0
            model = models[m_idx]
            st["rounds"] += 1
            log_path = os.path.join(ROUNDS, "%s_r%03d.log" % (book["name"], st["rounds"]))
            mark("[round] %s #%d 起跑：%d 章 / 现有 %d 章 %d 字（缺口 %d）· %s"
                 % (book["name"], st["rounds"], spec.get("round_chapters", 4), chs, words,
                    max(0, target - words), model))
            try:
                r = run_round(proj, int(spec.get("round_chapters", 4)), model, spec, log_path)
            except subprocess.TimeoutExpired:
                r = {"rc": 124, "sec": int(spec.get("round_hard_timeout_min", 150) * 60),
                     "log": log_path, "done": False, "tokens": 0, "cost": 0.0,
                     "failed_msg": "轮级硬超时", "text": ""}
            w2, c2 = count_words(proj)
            st["tokens"] += r["tokens"]
            st["cost"] = round(st["cost"] + r["cost"], 3)
            st["words"] = w2
            st["chapters"] = c2
            st["last_rc"] = r["rc"]
            st["last_model"] = model
            st["last_sec"] = r["sec"]
            prog["rounds"].append({"book": book["name"], "round": st["rounds"], "model": model,
                                   "rc": r["rc"], "sec": r["sec"], "done": r["done"],
                                   "add_chapters": c2 - chs, "words": w2,
                                   "tokens": r["tokens"], "ts": datetime.datetime.now()
                                   .strftime("%Y-%m-%d %H:%M:%S"), "log": os.path.relpath(log_path, ROOT)})
            save_progress(prog)
            if r["done"]:
                # done 标记 = 本轮汇总已打出（章节已落盘）。注意：此时 rc 仍可能非 0——
                # 实测 0xC0000409（QThread: Destroyed while thread '' is still running）
                # 发生在**进程退出**阶段，活已干完；按失败处理只会白等退避、污染失败计数。
                if r["rc"] != 0:
                    mark("[warn] %s #%d 收尾非零退码 rc=%s（活已干完，按成功计；退出期 Qt 线程崩溃）"
                         % (book["name"], st["rounds"], r["rc"]))
                mark("[ok] %s #%d 完成：+%d 章 → %d 章 %d 字（%.0fs, %d tok, 估算 ¥%.2f）"
                     % (book["name"], st["rounds"], c2 - chs, c2, w2, r["sec"],
                        r["tokens"], r["cost"]))
                strikes = 0
                continue
            # ---- 失败处置 ----
            strikes += 1
            quota = any(k in r["text"] for k in QUOTA_MARKERS)
            wait = int(spec.get("quota_backoff_sec", 1800) if quota
                       else spec.get("fail_backoff_sec", 120))
            mark("[fail] %s #%d rc=%s 配额类=%s：%s → %ds 后重试（连续 %d 次）"
                 % (book["name"], st["rounds"], r["rc"], quota,
                    (r["failed_msg"] or "无结论行")[:120], wait, strikes))
            if strikes >= int(spec.get("strikes_to_fallback", 2)) and m_idx + 1 < len(models):
                m_idx += 1
                strikes = 0
                mark("[switch] %s 换用兜底模型：%s" % (book["name"], models[m_idx]))
            if strikes >= int(spec.get("max_consecutive_failures", 6)):
                mark("[halt] %s 连续失败 %d 次，本本暂停（进度已存，可续跑）"
                     % (book["name"], strikes))
                break
            time.sleep(min(wait, max(5, deadline - time.time())))
    save_progress(prog)
    mark("=== 战役本段结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
