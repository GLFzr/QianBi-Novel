# -*- coding: utf-8 -*-
"""成本实验台（v0.18.5 优化战役）：同源种子书 + 变量预设 + 标准化消费指标

流程：
  --prepare  一次性：建种子书（核心设定+卷纲+3 份细纲）→ 快照为 bench_base/（变量共享同源）
  默认模式   克隆 bench_base → 注入变量预设（stage_params 覆盖）/快速道开关 →
             跑 N 章微循环（细纲已就位，隔离一次性调用；缺失的章现场生成，S4-d）
             → 产出 metrics.json

指标（fake home 的 usage.jsonl 全量聚合）：调用数/输入/命中%/miss/输出/推理 tok/
纯调用耗时/估算费用（off-peak v4-flash 价），外加每章 verdict 与字数、闸门轮数。

用法：
  python scripts/cost_bench.py --prepare                      # 建种子书（一次性）
  python scripts/cost_bench.py --variant base                 # 基线（3 章）
  python scripts/cost_bench.py --variant prose_low \
      --preset-params '{"prose":{"reasoning_effort":"low"}}'  # 变量
  python scripts/cost_bench.py --variant fastpath --fast-path
  python scripts/cost_bench.py --compare                      # 汇总对比表
  python scripts/cost_bench.py --compare --phase prose        # 按相位跨变体下钻
  python scripts/cost_bench.py --variant e11_span_trim \
      --preset-params @tests/bench_variants/e11_span_trim.json
  python scripts/cost_bench.py --variant iso --user-id bench-iso
  python scripts/cost_bench.py --variant ext --ext-helper qwen  # 摘要三相位外迁（需 QIANBI_BENCH_QWEN_KEY）

preset-params 取值：内联 JSON、@文件路径、或存在的 .json 文件路径。
文件格式支持实验预设 {"stage_params":{...},"gates":{...}}，也兼容纯 stage_params 字典。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
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
# W-5：盲区 token 口径三工具同源（metrics / chapter_curve / cost_ledger）
# ⚠️ 此处禁止模块级 import app.usage：会在 USERPROFILE 重定向前把
# 真机 usage 路径焊进模块常量（2026-09-10 V8 冒烟事故）。用函数内延迟导入。

BENCH = os.path.join(ROOT, "tests_output", "bench")
REAL_HOME = os.path.expanduser("~")   # 模块加载时记下真实家目录（后续会被重定向）
PREPARE_HOME = os.path.join(BENCH, "_prepare_home")
BASE_DIR = os.path.join(BENCH, "bench_base")
BOOK = "种子书"
CHAPTER_WORDS = 2000
N_OUTLINES = 6          # 种子书预备的细纲数（每个变量最多跑这么多章）
# --chapters 上限（S4-d：细纲按需生成后放开到 40）。T3 六十章压力终验用
# QIANBI_BENCH_MAX_CHAPTERS=60 抬升——缺省仍 40，免得悄悄放开全部长测的闸。
MAX_CHAPTERS = int(os.environ.get("QIANBI_BENCH_MAX_CHAPTERS", "").strip() or 40)
# 章内断点步序（与 app/core/stages.py 的 _ORDER 同序，改那边要改这里）：
# --seed-drafts 用它决定"从哪一步之后续跑"——续跑会把注入的草稿当正文读，
# 所以停在 draft 会让 扩写/压缩(trim)/去味/审校 全部在雷稿上真跑（T4a/T4b 需要），
# 停在 finalize 则只剩清算（历史上 --seed-drafts 的语义，保持不变）。
SEED_STEPS = ("assemble", "draft", "enrich", "scan", "deslop", "review", "finalize")
PRICE = {"miss": 0.22 / 1e6, "hit": 0.007 / 1e6, "out": 0.66 / 1e6}   # v4-flash off-peak $/tok（历史口径，等价 TIER_PRICE["flash"]）
# 分档计价（对齐 docs/成本台账.md 头部口径）：逐行按其 model 分价——
# 统一按 flash 计价会低估 pro 行（台账已修、实验台跟上的差异）
TIER_PRICE = {
    "flash": {"hit": 0.007 / 1e6, "miss": 0.22 / 1e6, "out": 0.66 / 1e6},
    "pro": {"hit": 0.022 / 1e6, "miss": 0.66 / 1e6, "out": 1.98 / 1e6},
}
USD_CNY = 7.2


def _tier_of(model) -> str:
    return "pro" if "pro" in str(model) else "flash"


def _mark(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# 测试渠道优先级（用户裁决 2026-09-10）：omen → 百炼 → DS 官方 deepseek-flash；
# TR 余额耗尽（402）殿后。
# 渠道 = 缓存域（N2）：切换会使 hit% 断裂，只在整卷边界切，且日志/晨报必须标注切换点。
TEST_CONN_PRIORITY = ["ocgo-omen", "bailian-flash", "ds-official-flash", "tr-dsv4f"]


def _pick_flash_conn(conns: list, prefer_id: str = ""):
    """flash 连接选择（纯函数，可单测）：按 TEST_CONN_PRIORITY 取第一条带 Key 的；
    --flash-conn 给定则钉死指定连接（不存在/无 Key 明确报错，不静默回退）。"""
    conns = [c for c in conns if c.get("api_key")]
    if prefer_id:
        pinned = next((c for c in conns if c.get("id") == prefer_id), None)
        if not pinned:
            raise SystemExit(f"--flash-conn 指定的连接 {prefer_id!r} 不存在或无 Key；"
                             f"现有带 Key 连接: {[c.get('id') for c in conns]}")
        return pinned, "钉定 --flash-conn"
    for cid in TEST_CONN_PRIORITY:
        for c in conns:
            if c.get("id") == cid:
                return c, "优先级链 %s" % " → ".join(TEST_CONN_PRIORITY)
    # 三条优先连接全缺：老逻辑兜底（cap-flash → DS 官方 flash），渠道变化要显式可见
    for c in conns:
        if c.get("id") == "cap-flash":
            return c, "兜底 cap-flash（优先级链三条全缺）"
    return next((c for c in conns
                 if "api.deepseek.com" in str(c.get("base_url", ""))
                 and "flash" in str(c.get("model", ""))), None), "兜底 DS 官方 flash"


def _load_key(prefer_id: str = "", pro_conn: str = ""):
    """Key 在凭据管理器：secrets.hydrate 按连接 id 领养。**必须读真机配置**——
    REAL_HOME 在模块加载时钉住；env 重定向到 fake home 后 load_config 只会给出
    出厂连接表，用户自建连接（ds-official-flash 等）不在其中，hydrate 无从领养
    （2026-09-12 P4a 发车失败定案：fake home 下 pinned 连接报「不存在或无 Key」）。
    凭据库（keyring）本身与 home 无关，hydrate 在真机配置 dict 上照常工作。
    flash：_pick_flash_conn 优先级链（tr-dsv4f → bailian-flash → ocgo-omen）；
    pro：**缺省不挂**（全线去 Pro，用户裁决 2026-09-07），仅 --pro-conn <id> 显式
    钉定（audit 严格档 F1 设计：flash 首判不过升 pro）。"""
    from app import secrets
    real_cfg = os.path.join(REAL_HOME, ".qianbi_novel", "config.json")
    try:
        with open(real_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"真机配置读不到（_load_key 需要它找 Key）: {real_cfg} ({e})")
    cfg = secrets.hydrate(cfg)
    conns = [c for c in cfg.get("connections", []) if c.get("api_key")]
    flash, how = _pick_flash_conn(conns, prefer_id)
    if not flash:
        raise SystemExit("真机配置里没有可用 flash Key；现有带 Key 连接: "
                         f"{[c.get('id') for c in conns]}")
    _mark("测试渠道：%s（%s @ %s）——%s" % (flash.get("id"), flash.get("model"),
                                          flash.get("base_url"), how))
    pro = None
    if pro_conn:
        pinned = next((c for c in conns if c.get("id") == pro_conn), None)
        if not pinned:
            raise SystemExit(f"--pro-conn 指定的连接 {pro_conn!r} 不存在或无 Key；"
                             f"现有带 Key 连接: {[c.get('id') for c in conns]}")
        pro = pinned
    return ({"key": flash["api_key"], "base": flash.get("base_url"), "model": flash.get("model")},
            ({"key": pro["api_key"], "base": pro.get("base_url"), "model": pro.get("model")}
             if pro else None))


def _state_mutate(proj: str, **kv) -> None:
    """pipeline_state 单键更新（load→mutate→save）。v16 5.1 A1 事故定案：save_state
    是**整文件覆盖**——传 {"genre_preset": pid} 会抹掉 state 里其余全部键，_phase_flags
    读空 → 清算 in_session 等旗标静默失效（v15 30 章 173 笔独立单发的真凶）。
    任何「只改一个键」的写入必须走本函数，禁止手写 save_state(proj, {单键 dict})。"""
    from app.core import state as _st
    state = _st.load_state(proj)
    state.update(kv)
    _st.save_state(proj, state)


def _qt():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    return app, Qt


def _ext_helper_cfg(kind: str) -> dict:
    """E4.1 摘要系外迁连接（OpenAI 兼容）：Key 从环境变量读，缺则拒绝空跑"""
    if kind == "qwen":
        env = "QIANBI_BENCH_QWEN_KEY"
        base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = os.environ.get("QIANBI_BENCH_QWEN_MODEL", "qwen-flash")
    elif kind == "doubao":
        env = "QIANBI_BENCH_DOUBAO_KEY"
        base = "https://ark.cn-beijing.volces.com/api/v3"
        model = os.environ.get("QIANBI_BENCH_DOUBAO_MODEL", "doubao-1.5-lite-32k-250415")
    else:
        raise SystemExit("--ext-helper 只支持 qwen | doubao")
    key = os.environ.get(env, "")
    if not key:
        raise SystemExit("--ext-helper %s 需要环境变量 %s（未设置，拒绝空跑）" % (kind, env))
    return {"id": "t-ext", "name": "ext %s（摘要外迁）" % kind, "provider": "custom",
            "base_url": base, "api_key": key, "model": model,
            "temperature": 0.7, "max_tokens": 65536, "timeout": 900}


def _mk_cfg(flash, fast_path=False, pro=None, user_id: str = "", ext: dict | None = None):
    return {
        "connections": ([
            {"id": "t-pro", "name": "pro 严格档", "provider": "custom",
             "base_url": pro["base"], "api_key": pro["key"], "model": pro["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high",
             "user_id": user_id}] if pro else []) + [

            {"id": "t-write", "name": "flash 写作", "provider": "custom",
             "base_url": flash["base"], "api_key": flash["key"], "model": flash["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high",
             "user_id": user_id},
            {"id": "t-helper", "name": "flash 辅助", "provider": "custom",
             "base_url": flash["base"], "api_key": flash["key"], "model": flash["model"],
             "temperature": 0.7, "max_tokens": 65536, "timeout": 900,
             "thinking": "enabled", "reasoning_effort": "high",
             "user_id": user_id},
        ] + ([dict(ext, user_id=user_id)] if ext else []),
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


def load_preset_spec(val: str) -> tuple:
    """--preset-params 取值解析：内联 JSON / @文件 / 存在的 .json 路径 → (stage_params, gates)

    实验预设落盘格式 {"stage_params": {...}, "gates": {...}, "writing": {...}}；也兼容纯
    stage_params 字典（历史用法 '{"prose":{...}}'）。解析失败 SystemExit，不让变量静默丢失。
    Returns: (stage_params, gates, writing)
    """
    if val is None:
        return None, None, None
    s = val.strip()
    data = None
    if s.startswith("@") or s.lower().endswith(".json"):
        path = s[1:] if s.startswith("@") else s
        if not os.path.isfile(path):
            raise SystemExit("--preset-params 文件不存在: " + path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            raise SystemExit("--preset-params 文件不是合法 JSON: %s (%s)" % (path, e))
    else:
        try:
            data = json.loads(s)
        except ValueError as e:
            raise SystemExit("--preset-params 不是合法 JSON: %s" % e)
    if not isinstance(data, dict):
        raise SystemExit("--preset-params 需要 JSON 对象")
    if ("stage_params" in data or "gates" in data or "writing" in data):
        sp = data.get("stage_params") if isinstance(data.get("stage_params"), dict) else None
        gt = data.get("gates") if isinstance(data.get("gates"), dict) else None
        wr = data.get("writing") if isinstance(data.get("writing"), dict) else None
        return sp, gt, wr
    return data, None, None


def _merge_ext_slots(preset_params: dict | None) -> dict:
    """E4.1：摘要系三相位外迁到 t-ext——仅在变体预设未显式配置这些相位时 setdefault
    （genre/变体显式配置优先，外迁开关绝不覆盖实验变量本身）"""
    sp = dict(preset_params or {})
    for ph in ("tracking", "chapter_summary", "global_summary"):
        if ph not in sp:
            sp[ph] = {"slot": "t-ext"}
    return sp


def _ensure_outline(proj: str, n: int, orch) -> bool:
    """S4-d（长卷能力）：本章细纲缺失时现场生成（stage_chapter_outlines n..n）。

    正常路径（--prepare 已备 1-6 章细纲）文件齐全 → 零额外调用、行为不变；
    --chapters N（N>6）的长卷跑按章现补细纲，使章数上限放开到 MAX_CHAPTERS。
    返回是否触发了生成（供测试断言调用时机：微循环前、逐章至多一次）。
    """
    from app import project
    from app.core import state as st
    from app.core import stages as st_mod
    if os.path.isfile(project.get_outline_path(proj, n)):
        return False
    # v13（writing.outline_in_session）：细纲生成挂进本章会话骑冻结头——
    # 这里必须让路（独立单发每章全额 miss + 全额输出，正是要省的那笔）。
    try:
        if bool(((orch.cfg or {}).get("writing", {}) or {}).get("outline_in_session", False)):
            return False
    except AttributeError:
        pass
    _mark("第%d章 细纲缺失，现场生成…" % n)
    state = st.load_state(proj)
    state["stage"] = st.STAGE_CH_OUTLINE
    st.save_state(proj, state)
    st_mod.stage_chapter_outlines(orch, n, n)
    return True


def _seed_proj(seed_home: str) -> str:
    """种子态工程目录：给目录（含 正文/）直接用，否则按变体名解析
    `tests_output/bench/<名>/bench/<BOOK>`——T2 以 T1 卷终态为种子续写。"""
    if os.path.isdir(seed_home):
        cand = seed_home
    else:
        cand = os.path.join(BENCH, seed_home, "bench", BOOK)
    if not os.path.isdir(os.path.join(cand, "正文")):
        raise SystemExit("--seed-home 解析不到工程目录（缺 正文/）：%s" % cand)
    return cand


def _seed_preset_name(src_proj: str) -> str:
    """续写必须复现的题材预设名——权威来源是**栈里那条 system**，不是 state 的预设名。

    卷会话恢复要求首条 system 与当前全书前缀逐字节一致（`volume_session.load`），而预设名
    就渲染在里面（`【题材预设：X】`）。换成 "实验 <新变体>" → 旧栈被拒、静默退回空栈，
    "从既有卷终态续写" 的前提就没了（T2 两臂 / 跨渠道校定全靠它）。
    state 里的 genre_preset 名每 seed 一跳就被换掉、追不到原始标签，故直接从栈里抠。
    变体身份仍由 id=bench_<variant>、user_id、metrics 承担，不受影响。
    """
    files = sorted(glob.glob(os.path.join(src_proj, "会话", "卷*_messages.jsonl")))
    for fn in reversed(files):
        try:
            with open(fn, encoding="utf-8") as f:
                first = json.loads(f.readline())
        except (OSError, ValueError):
            continue
        if not isinstance(first, dict) or first.get("role") != "system":
            continue
        m = re.search(r"【题材预设：(.*)】", first.get("content", ""))
        if m:
            return m.group(1)
    return ""


def cmd_run(variant: str, chapters: int, preset_params: dict | None,
            fast_path: bool, seed_drafts: str = "", user_id: str = "",
            ext: dict | None = None, gates: dict | None = None,
            writing: dict | None = None, no_pro: bool = False,
            flash_conn: str = "", pro_conn: str = "",
            seed_home: str = "", start: int = 1,
            outlines_only: bool = False, seed_from: str = "finalize") -> None:
    from app import project
    from app.core import memory
    from app.core import state as st
    from app.core import stages as st_mod
    from app.core.orchestrator import Orchestrator

    src = _seed_proj(seed_home) if seed_home else BASE_DIR
    assert os.path.isdir(src), "先跑 --prepare"
    home = os.path.join(BENCH, variant)
    if os.path.isdir(home):
        shutil.rmtree(home)
    os.makedirs(home)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home

    flash, pro = _load_key(prefer_id=flash_conn, pro_conn=pro_conn)
    if no_pro:
        if pro_conn:
            raise SystemExit("--no-pro 与 --pro-conn 冲突：缺省已无 Pro，"
                             "要挂严格档只给 --pro-conn <id>")
        pro = None   # 无 Pro 组合：清算预扫 flash+low 直采，无严格档兜底连接
    app, Qt = _qt()
    proj = os.path.join(home, "bench", BOOK)
    shutil.copytree(src, proj)
    if seed_home:
        _mark("种子态=%s，从第%d章续写到第%d章" % (src, start, chapters))

    if ext:
        preset_params = _merge_ext_slots(preset_params)
    cfg = _mk_cfg(flash, fast_path, pro, user_id=user_id, ext=ext)
    if gates:
        cfg.setdefault("gates", {}).update(gates)
    if writing:
        cfg.setdefault("writing", {}).update(writing)
    if preset_params:
        from app.presets import stage_params as genre_presets_stage_params
        # 变量预设：写进 fake home 的用户预设目录（load_preset 用户目录优先），
        # 走 genre_presets 既有校验管线——实验变量全部数据化，不动一行应用代码
        pid = "bench_" + variant
        from app.presets import user_dir
        # 题材预设名会渲染进 system 前缀：续写必须沿用，否则旧卷栈被拒（见 _seed_preset_name）
        label = (_seed_preset_name(src) if seed_home else "") or ("实验 " + variant)
        os.makedirs(user_dir(), exist_ok=True)
        with open(os.path.join(user_dir(), pid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": pid, "name": label, "version": 2,
                       "description": "cost_bench 变量预设",
                       "stage_params": preset_params}, f, ensure_ascii=False, indent=1)
        sp = genre_presets_stage_params(pid)
        _mark("变量预设 %s 生效档：%s" % (pid, json.dumps(sp, ensure_ascii=False)))
        if seed_home:
            _mark("题材预设名沿用种子「%s」（进 system 前缀，换名会退回空栈）" % label)
        _state_mutate(proj, genre_preset=pid)

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
        st.save_chapter_step(proj, n, step_done=seed_from,
                             draft_path=draft_rel, votes=[], outline_fp=fp)

    if seed_drafts:
        if seed_from not in SEED_STEPS:
            raise SystemExit("--seed-drafts-from 只认 %s，收到 %r"
                             % (" / ".join(SEED_STEPS), seed_from))
        _mark("种子草稿模式：每章微循环前注入 %r 断点（此后各步在雷稿上真跑；"
              "finalize = 历史语义，只剩清算）" % seed_from)

    from app.ui.bridge import Bridge
    bridge = Bridge()
    bridge.cfg.update({k: v for k, v in cfg.items() if k != "updates"})
    orch = Orchestrator(proj, bridge.cfg)

    # v15（writing.outline_pregen）：开书前批量预生成细纲并冻结——细纲是头部
    # 最大合法成分（v13 实测占语料头 53%），从「逐章 miss+out」变「ch1 起全员命中」。
    # 预生成走既有 stage_chapter_outlines 批量路径（失败拆半递归已有）；
    # 运行中禁止重写已冻结细纲（改头=全头作废），G4 话术在流水线内条件化。
    if ((cfg.get("writing", {}) or {}).get("outline_pregen", False)):
        _pregen_end = int((cfg.get("writing", {}) or {}).get("outline_pregen_end", 36) or 36)
        _mark("细纲预生成：第 1-%d 章（冻结纪律：运行中不改已冻结细纲）…" % _pregen_end)
        from app.core import stages as _st_mod
        _state_mutate(proj, stage=st.STAGE_CH_OUTLINE)
        _st_mod.stage_chapter_outlines(orch, 1, _pregen_end)

    if outlines_only:
        for n in range(start, chapters + 1):
            _ensure_outline(proj, n, orch)
        _mark("细纲补齐 %d-%d（不出正文）→ %s" % (start, chapters, proj))
        return

    t0 = time.monotonic()
    chapters_done = []
    for n in range(start, chapters + 1):
        if seed_drafts:
            _seed_chapter(n)
        _ensure_outline(proj, n, orch)   # S4-d：细纲缺失时现场生成（长卷 N>6 可跑）
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
    # U1-c：span 修订事件计数并入 metrics（T4b「回退率」判据从此可从产物读出）
    _span_path = os.path.join(proj, "追踪", "span_stats.jsonl")
    if os.path.isfile(_span_path):
        _agg = {}
        for _line in open(_span_path, encoding="utf-8"):
            try:
                _r = json.loads(_line)
                _p = _r.get("phase") or "?"
                _e = _r.get("event") or "?"
                _agg.setdefault(_p, {}).setdefault(_e, 0)
                _agg[_p][_e] += 1
            except ValueError:
                continue
        if _agg:
            metrics["span_stats"] = _agg
    # W-3：卷栈降级事件计数（整栈作废/坏行截尾/取会话失败此前只有一行 warn，
    # 跑完一本书就查不出来了）——按事件给出次数、丢弃轮数/token 与一次 miss 的钱
    _ev_path = os.path.join(proj, "追踪", "session_events.jsonl")
    _ev = {}
    if os.path.isfile(_ev_path):
        with open(_ev_path, encoding="utf-8") as _fh:
            for _line in _fh:
                try:
                    _r = json.loads(_line)
                except ValueError:
                    continue
                _d = _ev.setdefault(_r.get("event") or "?",
                                    {"n": 0, "turns": 0, "tok": 0, "cost": 0.0})
                _d["n"] += 1
                _d["turns"] += int(_r.get("turns") or 0)
                _d["tok"] += int(_r.get("tok") or 0)
                _d["cost"] = round(_d["cost"] + float(_r.get("cost") or 0), 4)
    if _ev:
        metrics["session_events"] = _ev
    _iso = _agg_vote_iso(os.path.join(proj, "追踪", "vote_fingerprints.jsonl"))
    if _iso:
        metrics["vote_iso"] = _iso
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


def _agg_vote_iso(path: str) -> dict:
    """W-6 判据：票间**同构率**（降票前必须先看这个数）。

    按章把 k 张票两两配对：`identical_bytes`＝整票逐字相同（真复读），
    `identical_levels`＝六维等级向量相同（哪怕文字不同，判定也没多一分信息）。
    iso_pct 高 ⇒ k 票退化成一票多打，该降；低 ⇒ 票确实各自独立。"""
    if not os.path.isfile(path):
        return {}
    by = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            by.setdefault(int(r.get("ch") or 0), []).append(r)
    pairs = sha = lvl = chs = echo = 0
    for rs in by.values():
        echo += sum(1 for r in rs if r.get("echo"))
        if len(rs) < 2:
            continue
        chs += 1
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                pairs += 1
                if rs[i].get("sha1") == rs[j].get("sha1"):
                    sha += 1
                if (rs[i].get("levels") or {}) == (rs[j].get("levels") or {}):
                    lvl += 1
    if not pairs:
        return {}
    return {"chapters": chs, "pairs": pairs, "identical_bytes": sha,
            "identical_levels": lvl, "iso_pct": round(100.0 * lvl / pairs, 1),
            "echo_votes": echo}


def _metrics(home: str, variant: str, chapters: list, wall: float) -> dict:
    from app.usage import blind_spread, cache_caliber  # 延迟导入：见模块级注释
    p = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    rows = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
    hit = sum(r.get("hit") or 0 for r in rows)
    miss = sum(r.get("miss") or 0 for r in rows)
    out = sum(r.get("out") or 0 for r in rows)
    reas = sum(r.get("reasoning") or 0 for r in rows)
    # 分档计价：逐行按其 model 分价（"pro" in model → pro 价，否则 flash 价），
    # 顶层 cost 为分档加总（台账口径；旧版统一 flash 价会低估 pro 行）。
    # W-5：网关没回缓存明细的行＝**盲区**，既不按命中也不按未命中上报；
    # 顶层 cost_usd 是**账面**（盲区按 miss 计，保守），cost_usd_real 按该档
    # 自身实测命中率摊派。旧实现把盲区输入当免费（虚低），与 chapter_curve（虚高）
    # 相反——三工具现在同源 app.usage.cache_caliber。
    cost_usd = 0.0
    blind_total = 0
    retry_calls = 0
    retry_usd = 0.0     # W-4：白付（带 st 的行）单独列账，不再让重试预算成为账面黑洞
    per_tier = {"flash": {"calls": 0, "hit": 0, "miss": 0, "blind": 0, "out": 0,
                          "cost_usd": 0.0},
                "pro": {"calls": 0, "hit": 0, "miss": 0, "blind": 0, "out": 0,
                        "cost_usd": 0.0}}
    per = {}
    for r in rows:
        tier = _tier_of(r.get("model", ""))
        pr = TIER_PRICE[tier]
        h, m, b = cache_caliber(r)
        blind_total += b
        o = r.get("out") or 0
        c = h * pr["hit"] + (m + b) * pr["miss"] + o * pr["out"]
        cost_usd += c
        if str(r.get("st") or "").strip():
            retry_calls += 1
            retry_usd += c
        pt = per_tier[tier]
        pt["calls"] += 1
        pt["hit"] += h
        pt["miss"] += m
        pt["blind"] += b
        pt["out"] += o
        pt["cost_usd"] += c
        a = per.setdefault(r.get("phase", ""), {"calls": 0, "hit": 0, "miss": 0,
                                               "out": 0, "reasoning": 0, "lat": 0.0})
        a["calls"] += 1
        a["hit"] += h
        a["miss"] += m + b          # 账面口径：盲区摊到 miss 上
        a["out"] += o
        a["reasoning"] += r.get("reasoning") or 0
        a["lat"] += r.get("latency") or 0.0
        # 相位级也按分档记：--compare --phase 的 cost_cny 才不会重蹈统一 flash 价
        tt = a.setdefault("tier_tok", {}).setdefault(tier, {"hit": 0, "miss": 0, "out": 0})
        tt["hit"] += h
        tt["miss"] += m + b
        tt["out"] += o
        a["cost_usd"] = a.get("cost_usd", 0.0) + c
    for a in per.values():
        t = a["hit"] + a["miss"]
        a["hit_pct"] = round(a["hit"] / t * 100, 1) if t else 0.0
        a["avg_lat"] = round(a["lat"] / a["calls"], 1)
        a["cost_usd"] = round(a.get("cost_usd", 0.0), 4)
    cost_real = 0.0
    for tier, pt in per_tier.items():
        pt["cost_usd"] = round(pt["cost_usd"], 4)
        add_h, add_m = blind_spread(pt["hit"], pt["miss"], pt["blind"])
        pr = TIER_PRICE[tier]
        pt["cost_usd_real"] = round(
            (pt["hit"] + add_h) * pr["hit"] + (pt["miss"] + add_m) * pr["miss"]
            + pt["out"] * pr["out"], 4)
        cost_real += pt["cost_usd_real"]
    in_true = hit + miss + blind_total
    return {
        "variant": variant,
        "calls": len(rows),
        "input_tok": in_true,
        "hit_tok": hit,
        "miss_tok": miss,
        "blind_tok": blind_total,
        "blind_pct": round(blind_total / in_true * 100, 1) if in_true else 0.0,
        "hit_pct": round(hit / (hit + miss) * 100, 1) if hit + miss else 0.0,
        "out_tok": out,
        "reasoning_tok": reas,
        "cost_usd": round(cost_usd, 4),
        "cost_cny": round(cost_usd * USD_CNY, 3),
        "cost_usd_real": round(cost_real, 4),
        "cost_cny_real": round(cost_real * USD_CNY, 3),
        "retry_calls": retry_calls,
        "retry_spend_cny": round(retry_usd * USD_CNY, 3),
        "llm_seconds": round(sum(r.get("latency") or 0 for r in rows), 1),
        "wall_seconds": round(wall, 1),
        "per_tier": per_tier,
        "per_phase": per,
        "chapters": chapters,
    }


def _print_metrics(m: dict) -> None:
    print("\n== %s ==" % m["variant"])
    print("调用 %d | 输入 %s tok（命中 %s%%／盲区 %s tok＝%s%%）| 输出 %s tok（推理 %s）"
          % (m["calls"], f"{m['input_tok']:,}", m["hit_pct"],
             f"{m.get('blind_tok', 0):,}", m.get("blind_pct", 0.0),
             f"{m['out_tok']:,}", f"{m['reasoning_tok']:,}"))
    # 爆炸章护栏（v12 教训）：清算输出/章超 8k = 难对账章的思考失控信号，出声不静默
    chs_n = len(m.get("chapters") or []) or 1
    for ph, b in (m.get("per_phase") or {}).items():
        out_per_ch = (b.get("out") or 0) / chs_n
        if out_per_ch > 8000:
            print("⚠️ %s 输出 %s tok/章（>%s/章×8k 阈值）——难对账/难生成章的思考失控信号，"
                  "查 metrics.json per_phase 与该章清算/细纲产物"
                  % (ph, f"{int(out_per_ch):,}", f"{chs_n}"))
    pt = m.get("per_tier") or {}
    if pt.get("pro", {}).get("calls"):
        print("分档：flash %d 笔 $%s | pro %d 笔 $%s"
              % (pt["flash"]["calls"], pt["flash"]["cost_usd"],
                 pt["pro"]["calls"], pt["pro"]["cost_usd"]))
    print("费用（账面）$%s ≈ ¥%s | （真实，盲区按本档命中率摊派）$%s ≈ ¥%s"
          " | LLM %ss / 墙钟 %ss"
          % (m["cost_usd"], m["cost_cny"], m.get("cost_usd_real", m["cost_usd"]),
             m.get("cost_cny_real", m["cost_cny"]),
             m["llm_seconds"], m["wall_seconds"]))
    for ph, a in sorted(m["per_phase"].items(), key=lambda x: -(x[1]["miss"] + x[1]["hit"])):
        print("  %-16s 笔%-3d hit %5.1f%% out %7s tok lat %ss"
              % (ph, a["calls"], a["hit_pct"], f"{a['out']:,}", a["avg_lat"]))
    for c in m["chapters"]:
        print("  第%d章 %s %s字 阻塞%s" % (c["num"], c["title"], c["words"], c["review_blocking"]))


def _phase_cost_cny(a: dict) -> tuple:
    """相位成本（元）。旧 metrics 无相位级分档时回退统一 flash 价并打 * 标注"""
    if a.get("cost_usd") is not None and "tier_tok" in a:
        return round(a["cost_usd"] * USD_CNY, 3), ""
    tt = a.get("tier_tok")
    if isinstance(tt, dict):
        c = sum(v["hit"] * TIER_PRICE[t]["hit"] + v["miss"] * TIER_PRICE[t]["miss"]
                + v["out"] * TIER_PRICE[t]["out"] for t, v in tt.items())
        return round(c * USD_CNY, 3), ""
    c = (a["hit"] * PRICE["hit"] + a["miss"] * PRICE["miss"] + a["out"] * PRICE["out"]) * USD_CNY
    return round(c, 3), "*"


def cmd_compare(phase: str = "") -> None:
    files = sorted(f for f in os.listdir(BENCH) if f.endswith(".metrics.json"))
    ms = [json.load(open(os.path.join(BENCH, f), encoding="utf-8")) for f in files]
    if not ms:
        return _mark("还没有 metrics")
    if phase:
        print("%-16s %6s %9s %7s %8s %9s"
              % ("variant", "calls", "out_tok", "hit%", "avg_lat", "cost¥"))
        stars = False
        for m in ms:
            a = (m.get("per_phase") or {}).get(phase)
            if not a:
                print("%-16s %s" % (m["variant"], "—（该变体无此相位）"))
                continue
            cny, star = _phase_cost_cny(a)
            stars = stars or bool(star)
            print("%-16s %6d %9s %6.1f%% %7.1fs %8s%s"
                  % (m["variant"], a["calls"], f"{a['out']:,}", a["hit_pct"],
                     a.get("avg_lat", 0.0), cny, star))
        if stars:
            print("* 旧 metrics 无相位级分档，按统一 flash 价回算（只影响历史变体）")
        return
    base = next((m for m in ms if m["variant"] == "base"), ms[0])
    print("%-14s %8s %7s %6s %9s %9s %9s %8s %6s"
          % ("variant", "cost¥", "hit%", "盲区%", "miss_tok", "out_tok", "reason_tok",
             "LLM秒", "章"))
    starred = False
    for m in ms:
        d = (m["cost_cny"] - base["cost_cny"]) / base["cost_cny"] * 100 if base["cost_cny"] else 0
        bp = float(m.get("blind_pct") or 0.0)
        star = "*" if bp >= 5.0 else " "
        starred = starred or bool(star)
        print("%-14s %8.3f %6.1f%%%s %6.1f%% %9s %9s %9s %8.0f %3d  (%+.0f%% vs %s)"
              % (m["variant"], m["cost_cny"], m["hit_pct"], star, bp,
                 f"{m['miss_tok']:,}",
                 f"{m['out_tok']:,}", f"{m['reasoning_tok']:,}", m["llm_seconds"],
                 len(m["chapters"]), d, base["variant"]))
    if starred:
        print("* 盲区 ≥5%（网关大面积没回 prompt_tokens_details）：cost¥ 是**账面**口径"
              "（盲区按 miss 计），与盲区率不同的渠道**不可直接互比**；"
              "同渠道内部对比仍然有效。")
    phases = sorted(set().union(*[set(m.get("per_phase") or {}) for m in ms])) if ms else []
    print("可用相位（--compare --phase <名> 逐变体下钻）：%s" % " ".join(phases))


def _parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="cost_bench.py",
        description="成本实验台：同源种子书 + 变量预设 + 标准化消费指标（off-peak 分档计价）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python scripts/cost_bench.py --prepare\n"
               "  python scripts/cost_bench.py --variant base\n"
               "  python scripts/cost_bench.py --variant e11_span_trim --preset-params @tests/bench_variants/e11_span_trim.json\n"
               "  python scripts/cost_bench.py --compare\n"
               "  python scripts/cost_bench.py --compare --phase prose\n")
    ap.add_argument("--prepare", action="store_true", help="一次性：建种子书 + 细纲 → bench_base/")
    ap.add_argument("--variant", default="base", help="变体名（产物落 tests_output/bench/<名>.*）")
    ap.add_argument("--chapters", type=int, default=3,
                    help="结束章（含；默认 3；上限 %d，超出部分细纲按需生成，S4-d）。"
                         "配 --start 即续写区间 start..chapters" % MAX_CHAPTERS)
    ap.add_argument("--start", type=int, default=1,
                    help="起始章（缺省 1；>1 须配 --seed-home 从既有卷终态续写，T2 用）")
    ap.add_argument("--seed-home", dest="seed_home", default="",
                    help="种子态：变体名或其工程目录（T2 以 T1 卷终态为种子，替代 bench_base）")
    ap.add_argument("--outlines-only", dest="outlines_only", action="store_true",
                    help="只补齐 start..chapters 的细纲即退出（T2 两臂共读同一批细纲的前置）")
    ap.add_argument("--preset-params", dest="preset_params", default=None,
                    help="变量预设：内联 JSON、@文件路径或存在的 .json 路径"
                         "（文件支持 {\"stage_params\":.., \"gates\":..}）")
    ap.add_argument("--fast-path", dest="fast_path", action="store_true",
                    help="审校 pass_fast 快速道开关")
    ap.add_argument("--seed-drafts", dest="seed_drafts", default="",
                    help="固定草稿目录（每章注入断点后续跑；缺省 finalize＝直奔清算）")
    ap.add_argument("--seed-drafts-from", dest="seed_drafts_from", default="finalize",
                    help="配合 --seed-drafts：注入草稿后从哪一步之后续跑。"
                         "T4a/T4b 用 draft 才能让 扩写/压缩/去味/审校 在雷稿上真跑"
                         "（可选 %s）" % " / ".join(SEED_STEPS))
    ap.add_argument("--user-id", dest="user_id", default="",
                    help="写入测试连接的 user_id（API `user` 字段）。"
                         "⚠️ 2026-09-07 实测它**不是缓存隔离**：tr-dsv4f 上换 user_id 仍复用"
                         "跨进程的缓存前缀，缓存域只由「渠道+字节」决定——隔离一律靠 fake home")
    ap.add_argument("--flash-conn", dest="flash_conn", default="",
                    help="钉写作/辅助槽的连接 id；缺省走优先级链 "
                         "tr-dsv4f → bailian-flash → ocgo-omen（用户裁决 2026-09-07，"
                         "自动取第一条带 Key 的，选择打印进日志）")
    ap.add_argument("--pro-conn", dest="pro_conn", default="",
                    help="显式钉定严格档 pro 连接 id；缺省不挂（全线去 Pro）")
    ap.add_argument("--no-pro", dest="no_pro", action="store_true",
                    help="无 Pro 组合（现已是缺省行为，保留参数只为兼容旧队列 spec）")
    ap.add_argument("--ext-helper", dest="ext_helper", choices=["qwen", "doubao"], default=None,
                    help="E4.1 摘要三相位外迁（Key 读 QIANBI_BENCH_QWEN_KEY / QIANBI_BENCH_DOUBAO_KEY）")
    ap.add_argument("--compare", action="store_true", help="汇总对比表（读 tests_output/bench/*.metrics.json）")
    ap.add_argument("--phase", default="", help="配合 --compare：按相位名跨变体下钻")
    return ap.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.prepare:
        return cmd_prepare()
    if args.compare:
        return cmd_compare(args.phase)
    preset_params, gates, writing = load_preset_spec(args.preset_params)
    ext = _ext_helper_cfg(args.ext_helper) if args.ext_helper else None
    # S4-d：章数上限 MAX_CHAPTERS（细纲按需生成，超出 --prepare 储备的长卷可跑）
    chapters = max(1, min(int(args.chapters), MAX_CHAPTERS))
    start = max(1, min(int(args.start), chapters))
    if start > 1 and not args.seed_home:
        raise SystemExit("--start >1 必须配 --seed-home（否则第 1..N 章会被跳过）")
    return cmd_run(args.variant, chapters, preset_params, args.fast_path,
                   args.seed_drafts, user_id=args.user_id, ext=ext, gates=gates,
                   writing=writing, no_pro=args.no_pro,
                   flash_conn=args.flash_conn, pro_conn=args.pro_conn,
                   seed_home=args.seed_home, start=start,
                   outlines_only=args.outlines_only, seed_from=args.seed_drafts_from)


if __name__ == "__main__":
    main()
