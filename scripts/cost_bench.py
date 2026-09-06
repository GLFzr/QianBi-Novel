# -*- coding: utf-8 -*-
"""成本实验台（v0.18.5 优化战役）：同源种子书 + 变量预设 + 标准化消费指标

流程：
  --prepare  一次性：建种子书（核心设定+卷纲+3 份细纲）→ 快照为 bench_base/（变量共享同源）
  默认模式   克隆 bench_base → 注入变量预设（stage_params 覆盖）/快速道开关 →
             跑 N 章微循环（细纲已就位，隔离一次性调用）→ 产出 metrics.json

指标（fake home 的 usage.jsonl 全量聚合）：调用数/输入/命中%/miss/输出/推理 tok/
纯调用耗时/估算费用（off-peak v4-flash 价），外加每章 verdict 与字数、闸门轮数。

用法：
  python scripts/cost_bench.py --prepare                      # 建种子书（一次性）
  python scripts/cost_bench.py --variant base                 # 基线（3 章）
  python scripts/cost_bench.py --variant prose_low \
      --preset-params '{"prose":{"reasoning_effort":"low"}}'  # 变量
  python scripts/cost_bench.py --variant fastpath --fast-path
  python scripts/cost_bench.py --compare                      # 汇总对比表
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BENCH = os.path.join(ROOT, "tests_output", "bench")
REAL_HOME = os.path.expanduser("~")   # 模块加载时记下真实家目录（后续会被重定向）
PREPARE_HOME = os.path.join(BENCH, "_prepare_home")
BASE_DIR = os.path.join(BENCH, "bench_base")
BOOK = "种子书"
CHAPTER_WORDS = 2000
N_OUTLINES = 6          # 种子书预备的细纲数（每个变量最多跑这么多章）
PRICE = {"miss": 0.22 / 1e6, "hit": 0.007 / 1e6, "out": 0.66 / 1e6}   # v4-flash off-peak $/tok
USD_CNY = 7.2


def _mark(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _load_key():
    """Key 在凭据管理器：走 secrets.hydrate 读真机配置，优先用户指定的测试连接 cap-flash；
    同时取一条 pro 连接（audit 严格档 F1 设计：flash 首判不过升 pro）"""
    from app import config as cfg_mod
    from app import secrets
    cfg = secrets.hydrate(cfg_mod.load_config())
    conns = [c for c in cfg.get("connections", []) if c.get("api_key")]
    flash = pro = None
    for c in conns:
        if c.get("id") == "cap-flash":
            flash = c
    if flash is None:
        flash = next((c for c in conns
                      if "api.deepseek.com" in str(c.get("base_url", ""))
                      and "flash" in str(c.get("model", ""))), None)
    pro = next((c for c in conns if str(c.get("model", "")).endswith("pro")), None)
    if not flash:
        raise SystemExit("真机配置里没有可用 flash Key")
    return ({"key": flash["api_key"], "base": flash.get("base_url"), "model": flash.get("model")},
            ({"key": pro["api_key"], "base": pro.get("base_url"), "model": pro.get("model")}
             if pro else None))


def _qt():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return app, Qt


def _mk_cfg(flash, fast_path=False, pro=None):
    return {
        "connections": ([
            {"id": "t-pro", "name": "pro 严格档", "provider": "custom",
             "base_url": pro["base"], "api_key": pro["key"], "model": pro["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high"}] if pro else []) + [
            
            {"id": "t-write", "name": "flash 写作", "provider": "custom",
             "base_url": flash["base"], "api_key": flash["key"], "model": flash["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high"},
            {"id": "t-helper", "name": "flash 辅助", "provider": "custom",
             "base_url": flash["base"], "api_key": flash["key"], "model": flash["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high"},
        ],
        "slots": {"writing": "t-write", "helper": "t-helper", "review": "t-helper"},
        "gates": {"strategy": "mark_continue", "deslop_max_rounds": 2,
                  "word_tolerance": 0.1, "word_enrich_rounds": 2,
                  "review_enabled": True, "review_max_rounds": 1,
                  "review_votes": 3, "review_votes_recheck": 1,
                  "review_pass_fast": bool(fast_path)},
        "llm": {"max_retries": 2, "backoff_base": 2.0},
        "writing": {"chapter_word_target": CHAPTER_WORDS, "chapter_session": True,
                    "auto_gate": True, "default_genre": "", "default_platform": "番茄",
                    "run_mode": "pipeline"},
        "updates": {},
    }


def cmd_prepare() -> None:
    """一次性：种子书 + N 份细纲 → bench_base/"""
    from app import project
    from app.core import state as st
    from app.core import stages as st_mod
    from app.core.orchestrator import Orchestrator

    if os.path.isdir(BASE_DIR):
        _mark("bench_base 已存在，跳过 prepare（删除 %s 可重建）" % BASE_DIR)
        return
    os.makedirs(PREPARE_HOME, exist_ok=True)
    os.environ["USERPROFILE"] = PREPARE_HOME
    os.environ["HOME"] = PREPARE_HOME

    flash, pro = _load_key()
    _mark("测试连接：%s @ %s（严格档：%s）" % (flash["model"], flash["base"], (pro or {}).get("model", "无")))
    app, Qt = _qt()
    proj_root = os.path.join(PREPARE_HOME, "bench")
    from app.ui.bridge import Bridge
    bridge = Bridge()
    ok = bridge.newProject(proj_root, BOOK, "都市悬疑", "番茄", 10,
                           "主角能用一支笔改写命运的笔记")
    assert ok, "建项目失败"
    proj = os.path.join(proj_root, BOOK)
    bridge.setProjectPreset("urban_destiny")
    bridge.cfg.setdefault("writing", {})["auto_gate"] = True
    bridge.cfg.setdefault("writing", {})["chapter_session"] = True
    orch = Orchestrator(proj, bridge.cfg)

    _mark("阶段① 核心设定…")
    st_mod.stage_core_setting(orch)
    _mark("阶段② 卷纲…")
    st_mod.stage_volume_outline(orch, 10)
    for n in range(1, N_OUTLINES + 1):
        _mark("细纲 第%d章…" % n)
        state = st.load_state(proj)
        state["stage"] = st.STAGE_CH_OUTLINE
        st.save_state(proj, state)
        st_mod.stage_chapter_outlines(orch, n, n)
    shutil.copytree(proj, BASE_DIR, dirs_exist_ok=True)
    _mark("bench_base 就绪：%s" % BASE_DIR)
    _mark("prepare 用量：%d 行" % _usage_lines(PREPARE_HOME))


def _usage_lines(home: str) -> int:
    p = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    if not os.path.isfile(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in f)


def cmd_run(variant: str, chapters: int, preset_params: dict | None,
            fast_path: bool, seed_drafts: str = "") -> None:
    from app import project
    from app.core import memory
    from app.core import state as st
    from app.core import stages as st_mod
    from app.core.orchestrator import Orchestrator

    assert os.path.isdir(BASE_DIR), "先跑 --prepare"
    home = os.path.join(BENCH, variant)
    if os.path.isdir(home):
        shutil.rmtree(home)
    os.makedirs(home)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home

    flash, pro = _load_key()
    app, Qt = _qt()
    proj = os.path.join(home, "bench", BOOK)
    shutil.copytree(BASE_DIR, proj)

    cfg = _mk_cfg(flash, fast_path, pro)
    if preset_params:
        from app.presets import stage_params as genre_presets_stage_params
        # 变量预设：写进 fake home 的用户预设目录（load_preset 用户目录优先），
        # 走 genre_presets 既有校验管线——实验变量全部数据化，不动一行应用代码
        pid = "bench_" + variant
        from app.presets import user_dir
        os.makedirs(user_dir(), exist_ok=True)
        with open(os.path.join(user_dir(), pid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": pid, "name": "实验 " + variant, "version": 2,
                       "description": "cost_bench 变量预设",
                       "stage_params": preset_params}, f, ensure_ascii=False, indent=1)
        sp = genre_presets_stage_params(pid)
        _mark("变量预设 %s 生效档：%s" % (pid, json.dumps(sp, ensure_ascii=False)))
        st.save_state(proj, {"genre_preset": pid})

    def _seed_chapter(n: int):
        """确定性审计对比：单槽断点必须在每章微循环前注入对应章
        （chapter_step 全项目只有一槽，预先循环写入会被自己的后章覆盖）"""
        import hashlib
        src_md = os.path.join(seed_drafts, "第%03d.md" % n)
        if not os.path.isfile(src_md):
            raise SystemExit("种子草稿缺失: " + src_md)
        draft_rel = os.path.relpath(project.chapter_draft_path(proj, n), proj)
        os.makedirs(os.path.dirname(project.chapter_draft_path(proj, n)), exist_ok=True)
        shutil.copyfile(src_md, project.chapter_draft_path(proj, n))
        outline = memory.sanitize_chapter_refs(
            project.read_file(project.get_outline_path(proj, n)))
        fp = hashlib.sha1((outline or "").encode("utf-8")).hexdigest()[:12]
        st.save_chapter_step(proj, n, step_done="finalize",
                             draft_path=draft_rel, votes=[], outline_fp=fp)

    if seed_drafts:
        _mark("种子草稿模式：每章微循环前注入 finalize 断点（直奔清算）")

    from app.ui.bridge import Bridge
    bridge = Bridge()
    bridge.cfg.update({k: v for k, v in cfg.items() if k != "updates"})
    orch = Orchestrator(proj, bridge.cfg)

    t0 = time.monotonic()
    chapters_done = []
    for n in range(1, chapters + 1):
        if seed_drafts:
            _seed_chapter(n)
        _mark("第%d章 微循环…" % n)
        state = st.load_state(proj)
        state["stage"] = st.STAGE_PROSE
        st.save_state(proj, state)
        r = st_mod.chapter_microcycle(orch, n)
        chapters_done.append({"num": n, "title": r.get("title", ""),
                              "words": r.get("words", 0),
                              "review_blocking": r.get("review_blocking", 0)})
        _mark("第%d章完成：%s %s 字" % (n, r.get("title", ""), r.get("words", 0)))
    wall = time.monotonic() - t0

    metrics = _metrics(home, variant, chapters_done, wall)
    out = os.path.join(BENCH, "%s.metrics.json" % variant)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    # 章节文本留档（质量盲评用）
    txt_dir = os.path.join(BENCH, "%s.chapters" % variant)
    if os.path.isdir(txt_dir):
        shutil.rmtree(txt_dir)
    shutil.copytree(os.path.join(proj, "正文"), txt_dir,
                    ignore=shutil.ignore_patterns(".drafts", ".versions"))
    _mark("完成：%s（%.0fs）→ %s" % (variant, wall, out))
    _print_metrics(metrics)


def _metrics(home: str, variant: str, chapters: list, wall: float) -> dict:
    p = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    rows = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
    hit = sum(r.get("hit") or 0 for r in rows)
    miss = sum(r.get("miss") or 0 for r in rows)
    out = sum(r.get("out") or 0 for r in rows)
    reas = sum(r.get("reasoning") or 0 for r in rows)
    cost_usd = miss * PRICE["miss"] + hit * PRICE["hit"] + out * PRICE["out"]
    per = {}
    for r in rows:
        a = per.setdefault(r.get("phase", ""), {"calls": 0, "hit": 0, "miss": 0,
                                               "out": 0, "reasoning": 0, "lat": 0.0})
        a["calls"] += 1
        a["hit"] += r.get("hit") or 0
        a["miss"] += r.get("miss") or 0
        a["out"] += r.get("out") or 0
        a["reasoning"] += r.get("reasoning") or 0
        a["lat"] += r.get("latency") or 0.0
    for a in per.values():
        t = a["hit"] + a["miss"]
        a["hit_pct"] = round(a["hit"] / t * 100, 1) if t else 0.0
        a["avg_lat"] = round(a["lat"] / a["calls"], 1)
    return {
        "variant": variant,
        "calls": len(rows),
        "input_tok": hit + miss,
        "hit_tok": hit,
        "miss_tok": miss,
        "hit_pct": round(hit / (hit + miss) * 100, 1) if hit + miss else 0.0,
        "out_tok": out,
        "reasoning_tok": reas,
        "cost_usd": round(cost_usd, 4),
        "cost_cny": round(cost_usd * USD_CNY, 3),
        "llm_seconds": round(sum(r.get("latency") or 0 for r in rows), 1),
        "wall_seconds": round(wall, 1),
        "per_phase": per,
        "chapters": chapters,
    }


def _print_metrics(m: dict) -> None:
    print("\n== %s ==" % m["variant"])
    print("调用 %d | 输入 %s tok（命中 %s%%）| 输出 %s tok（推理 %s）"
          % (m["calls"], f"{m['input_tok']:,}", m["hit_pct"],
             f"{m['out_tok']:,}", f"{m['reasoning_tok']:,}"))
    print("费用 $%s ≈ ¥%s | LLM %ss / 墙钟 %ss"
          % (m["cost_usd"], m["cost_cny"], m["llm_seconds"], m["wall_seconds"]))
    for ph, a in sorted(m["per_phase"].items(), key=lambda x: -(x[1]["miss"] + x[1]["hit"])):
        print("  %-16s 笔%-3d hit %5.1f%% out %7s tok lat %ss"
              % (ph, a["calls"], a["hit_pct"], f"{a['out']:,}", a["avg_lat"]))
    for c in m["chapters"]:
        print("  第%d章 %s %s字 阻塞%s" % (c["num"], c["title"], c["words"], c["review_blocking"]))


def cmd_compare() -> None:
    files = sorted(f for f in os.listdir(BENCH) if f.endswith(".metrics.json"))
    ms = [json.load(open(os.path.join(BENCH, f), encoding="utf-8")) for f in files]
    if not ms:
        return _mark("还没有 metrics")
    base = next((m for m in ms if m["variant"] == "base"), ms[0])
    print("%-14s %8s %7s %9s %9s %9s %8s %6s"
          % ("variant", "cost¥", "hit%", "miss_tok", "out_tok", "reason_tok", "LLM秒", "章"))
    for m in ms:
        d = (m["cost_cny"] - base["cost_cny"]) / base["cost_cny"] * 100 if base["cost_cny"] else 0
        print("%-14s %8.3f %6.1f%% %9s %9s %9s %8.0f %3d  (%+.0f%% vs %s)"
              % (m["variant"], m["cost_cny"], m["hit_pct"], f"{m['miss_tok']:,}",
                 f"{m['out_tok']:,}", f"{m['reasoning_tok']:,}", m["llm_seconds"],
                 len(m["chapters"]), d, base["variant"]))


def main() -> None:
    args = sys.argv[1:]
    if "--prepare" in args:
        return cmd_prepare()
    if "--compare" in args:
        return cmd_compare()
    variant = args[args.index("--variant") + 1] if "--variant" in args else "base"
    chapters = int(args[args.index("--chapters") + 1]) if "--chapters" in args else 3
    preset = json.loads(args[args.index("--preset-params") + 1]) if "--preset-params" in args else None
    fast = "--fast-path" in args
    seed = args[args.index("--seed-drafts") + 1] if "--seed-drafts" in args else ""
    return cmd_run(variant, chapters, preset, fast, seed)


if __name__ == "__main__":
    main()
