# -*- coding: utf-8 -*-
"""雷章召回重放量具（v16 P0 / C1 资产化）：雷集 → 双通道 → 召回判定，一键重放

v1 散件（review_tier_probe.py）的资产化取代版。纪律来源：工作指南 v3——
「任何影响审校/清算的改动，雷章召回 B01/B02/C01/D01 不降」；v16 总案 P0——
A1 的 thinking-disabled 没有本量具的召回数据不许落地。

设计：
- 雷源：tests/planted_defects/defects.json（雷集 v2）。默认召回门 = legacy 四雷
  B01/B02/C01/D01；queue 里 defects 可扩全集。
- 通道：review（六维终审：build_final_review_prompt + parse_final_review_v2 +
  引文验真）与 audit（设定清算：canon_audit.audit_chapter，程序侧 pattern/引证
  复核在环）。
- 判定：每颗雷独立植入一章（单雷归因无歧义；内存注入不落盘）；votes 票独立
  采样；命中 = 标记串出现在该通道产物 JSON（review items / audit violations+
  pattern_hits+cross_issues+triage）。干净对照查假阳性：review 出 fail 级条目、
  audit 报 violations 即假阳性。
- 队列（presets+queue）：queue JSON 定义场景（默认 = thinking-disabled 门档 +
  thinking-on 对照档，同跑次 A/B 消跨跑漂移）；逐场景串行，每场景独立子进程
  （app.config.CONFIG_DIR 是 import 时绑定——同进程多 fake home 会串台，
  t3/cost_bench 单进程单 home 的既成约束在此以子进程隔离延续）。
- 门（--gate --baseline）：逐 (雷, 通道) 召回率不得低于基线，任何回归 exit 1；
  植入失败（锚点失配等）视量具失灵，无论是否 --gate 一律 exit 1。
- 仪器安全：全程 fake home（真机台账零写入；Key 走凭据管理器，机器级不受
  home 影响——cost_bench 同款已验证流程：先设 env 后 import）；父进程收车
  断言真机台账行数不变，变了 exit 2（V8 台账污染事故安全网）。

用法：
  python scripts/mine_replay.py --queue tests/bench_variants/queue_mine_gate.json --dry-run
  python scripts/mine_replay.py --queue tests/bench_variants/queue_mine_gate.json
  python scripts/mine_replay.py --queue ... --gate \
      --baseline tests_output/bench/mine_replay/<id>/results.json
  python scripts/mine_replay.py --list

退出码：0=通过（或仅报告）；1=召回回归/植入失败/假阳性；2=用法/队列 schema/
真机台账污染；3=预算熔断（部分结果已存盘）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.planted_defects import load_defects  # noqa: E402
from scripts.plant_defects import apply_defect  # noqa: E402

BENCH = os.path.join(ROOT, "tests_output", "bench")
BASE_BOOK = os.path.join(BENCH, "bench_base")
BOOK = "种子书"
OUT_DIR = os.path.join(BENCH, "mine_replay")
# 模块导入时（env 尚未篡改）绑定真机台账路径——子进程里也如此，安全网才成立
REAL_USAGE = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage", "usage.jsonl")

GATE_DEFECTS = ["B01", "B02", "C01", "D01"]   # legacy 召回门四雷（工作指南 v3）
CHANNELS = ("review", "audit")

# 每颗雷的唯一标记串（命中判定用）：v1 探针同款口径——标记必须是 inject.text 的
# 子串（单测钉死），且种子书正文里自然不存在（干净对照天然可查假阳性）。
DEFAULT_MARKS = {
    "A01": "晾衣绳上的水滴了七天",
    "A02": "野球场",
    "B01": "改日再算",
    "B02": "蒋霸",
    "C01": "让父亲在昨夜的高速上活下来",
    "C02": "催动了一回听痕术",
    "C03": "第五回动用听痕术",
    "D01": "老周",
    "D02": "尾号 7392",
    "E01": "刀疤堵在巷口",
    "E02": "讲道理",
    "F01": "他不知道的是",
    "F02": "沉沉睡去",
    "F03": "他望向楼上的窗",
}

# off-peak flash 价（USD/tok，¥=$×7.2；与 cost_ledger.PRICE 同源，本地复制以免
# 量具 import 拉起 app 依赖——单测裸导入）
PRICE_FLASH = {"hit": 0.007e-6, "miss": 0.22e-6, "out": 0.66e-6}
USD_CNY = 7.2

# audit 通道预扫可见正文上限（与 canon_audit.AUDIT_PROMPT prose[:6000] 钉住）
AUDIT_PROSE_CAP = 6000


def _mark(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _row_count(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


# ---------- 队列文件（presets+queue） ----------

def validate_queue(queue: dict, check_paths: bool = True) -> dict:
    """schema 校验 + 缺省值填充。违规 SystemExit（发车前拦截，不让变量静默丢失）。"""
    if not isinstance(queue, dict):
        raise SystemExit("queue 文件必须是 JSON 对象")
    for key in ("id", "scenarios"):
        if key not in queue:
            raise SystemExit("queue 缺字段：%s" % key)
    if not queue["scenarios"] or not isinstance(queue["scenarios"], list):
        raise SystemExit("queue.scenarios 必须是非空数组")
    if not all(isinstance(s.get("name"), str) and s["name"] for s in queue["scenarios"]):
        raise SystemExit("每个 scenario 必须有非空 name")
    names = [s["name"] for s in queue["scenarios"]]
    if len(set(names)) != len(names):
        raise SystemExit("scenario name 重复：%s" % names)
    defects = queue.get("defects") or GATE_DEFECTS
    all_defs = {d["id"]: d for d in load_defects()["defects"]}
    bad = [d for d in defects if d not in all_defs]
    if bad:
        raise SystemExit("未知雷 id：%s（可用：%s）" % (", ".join(bad), ", ".join(sorted(all_defs))))
    channels = queue.get("channels") or list(CHANNELS)
    bad_ch = [c for c in channels if c not in CHANNELS]
    if bad_ch:
        raise SystemExit("未知通道：%s（可用：%s）" % (", ".join(bad_ch), "/".join(CHANNELS)))
    marks = dict(DEFAULT_MARKS)
    marks.update(queue.get("marks") or {})
    for d in defects:
        if d not in marks:
            raise SystemExit("雷 %s 无标记串（queue.marks 必须补齐）" % d)
        if marks[d] not in all_defs[d]["inject"]["text"]:
            raise SystemExit("雷 %s 的标记串不是 inject.text 子串：%r" % (d, marks[d]))
    votes = int(queue.get("votes") or 2)
    if votes < 1:
        raise SystemExit("votes 必须 ≥1")
    src = queue.get("source_drafts") or ""
    nums = queue.get("chapter_nums") or [2]
    if check_paths:
        base = src if os.path.isabs(src) else os.path.join(ROOT, src)
        if not os.path.isdir(base):
            raise SystemExit("source_drafts 不存在：%s" % src)
        for n in nums:
            if not os.path.isfile(os.path.join(base, "第%03d.md" % n)):
                raise SystemExit("source_drafts 缺 第%03d.md：%s" % (n, src))
        if not os.path.isdir(BASE_BOOK):
            raise SystemExit("bench_base 不存在（先跑 cost_bench --prepare）：" + BASE_BOOK)
    queue.setdefault("flash_conn", "ds-official-flash")
    queue.setdefault("budget_cny_max", 3.0)
    queue["_defects"] = defects
    queue["_channels"] = channels
    queue["_votes"] = votes
    queue["_marks"] = marks
    queue["_chapter_nums"] = nums
    return queue


def load_queue(path: str, check_paths: bool = True) -> dict:
    with open(path, encoding="utf-8") as f:
        try:
            queue = json.load(f)
        except ValueError as e:
            raise SystemExit("queue 文件不是合法 JSON：%s (%s)" % (path, e))
    return validate_queue(queue, check_paths=check_paths)


def plan_calls(queue: dict) -> dict:
    """纯离线：发车计划（调用数/预算/场景明细），--dry-run 与单测共用。"""
    calls = 0
    per_scenario = []
    for s in queue["scenarios"]:
        defects = s.get("defects") or queue["_defects"]
        channels = s.get("channels") or queue["_channels"]
        votes = s.get("votes") or queue["_votes"]
        n_ch = len(queue["_chapter_nums"])
        planted = len(defects) * n_ch * len(channels) * votes
        clean = n_ch * len(channels) * votes
        calls += planted + clean
        per_scenario.append({"name": s["name"], "defects": defects, "channels": channels,
                             "votes": votes, "calls": planted + clean})
    return {"calls": calls, "budget_cny_max": queue["budget_cny_max"],
            "scenarios": per_scenario}


# ---------- 用量与计价 ----------

def _usage_rows():
    """当前 home 的 usage 全量行（必须在 env 就位、app 导入之后调用）。"""
    from app import config as cfg_mod
    p = os.path.join(cfg_mod.CONFIG_DIR, "usage", "usage.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _row_cost(row: dict) -> float:
    return (row.get("hit", 0) * PRICE_FLASH["hit"]
            + row.get("miss", 0) * PRICE_FLASH["miss"]
            + row.get("out", 0) * PRICE_FLASH["out"]) * USD_CNY


def _usage_delta(rows_before: int) -> dict:
    rows = _usage_rows()
    agg = {"calls": 0, "in": 0, "out": 0, "hit": 0, "miss": 0,
           "reasoning": 0, "cost_cny": 0.0}
    for r in rows[rows_before:]:
        agg["calls"] += 1
        for k in ("in", "out", "hit", "miss", "reasoning"):
            agg[k] += int(r.get(k) or 0)
        agg["cost_cny"] += _row_cost(r)
    agg["cost_cny"] = round(agg["cost_cny"], 4)
    return agg


# ---------- 场景子进程：单场景执行（独立进程 = 独立 app 导入与 home 绑定） ----------

def _review_client(cfg: dict, overrides: dict):
    """review 槽客户端（与 canon_audit._client_for 同源构造）+ 场景参数覆盖层。"""
    from app import config as cfg_mod
    from app.llm.client import LLMClient
    conn = cfg_mod.slot_connection(cfg, cfg_mod.SLOT_REVIEW)
    client = LLMClient.from_connection(conn or {}, max_retries=1, slot="review")
    if overrides:
        client._overrides = lambda _ph, _o=dict(overrides): dict(_o)
    return client


def run_review(proj: str, cfg: dict, num: int, prose: str, overrides: dict,
               marks: list) -> dict:
    from app.core import stages
    client = _review_client(cfg, overrides)
    prompt = stages.build_final_review_prompt(proj, cfg, num, prose)
    t0 = time.monotonic()
    rows0 = len(_usage_rows())
    raw = client.chat_stream(prompt, temperature=0.2, phase="review")
    lat = round(time.monotonic() - t0, 1)
    v2 = stages.verify_review_quotes(prose, stages.parse_final_review_v2(raw))
    items = v2.get("items") or []
    blob = json.dumps(items, ensure_ascii=False)
    return {"verdict": v2.get("verdict"),
            "n_items": len(items),
            "n_fail": sum(1 for i in items if i.get("level") == "fail"),
            "quote_real": "%d/%d" % (sum(1 for i in items if i.get("quote") and i.get("quote_verified")),
                                     sum(1 for i in items if i.get("quote"))),
            "caught": [m for m in marks if m in blob],
            "latency": lat,
            "usage": _usage_delta(rows0)}


def run_audit(proj: str, cfg: dict, num: int, prose: str, overrides: dict,
              marks: list) -> dict:
    from app.core import canon_audit
    client = _review_client(cfg, overrides)

    class _Router:  # 注入点：audit_chapter 经 router.client("review") 取客户端
        def __init__(self, c):
            self._c = c

        def client(self, _slot):
            return self._c

    rows0 = len(_usage_rows())
    t0 = time.monotonic()
    report = canon_audit.audit_chapter(proj, num, prose, cfg, router=_Router(client))
    lat = round(time.monotonic() - t0, 1)
    blob = json.dumps({"violations": report.get("violations"),
                       "pattern_hits": report.get("pattern_hits"),
                       "cross_issues": report.get("cross_issues"),
                       "triage": report.get("triage")}, ensure_ascii=False)
    return {"failed": bool(report.get("failed")),
            "n_violations": len(report.get("violations") or []),
            "n_pattern": len(report.get("pattern_hits") or []),
            "error": report.get("error", ""),
            "caught": [m for m in marks if m in blob],
            "latency": lat,
            "usage": _usage_delta(rows0)}


RUNNERS = {"review": run_review, "audit": run_audit}


def _build_cfg(queue: dict):
    """cfg 构造与 cost_bench 同源（_mk_cfg），叠加 queue.preset 的 writing/gates。"""
    from scripts.cost_bench import _load_key, _mk_cfg, load_preset_spec
    flash, _pro = _load_key(prefer_id=queue.get("flash_conn", ""))
    cfg = _mk_cfg(flash)
    preset = queue.get("preset") or ""
    if preset:
        p_path = preset if os.path.isabs(preset) else os.path.join(ROOT, preset)
        _sp, gates, writing = load_preset_spec("@" + p_path)
        if gates:
            cfg.setdefault("gates", {}).update(gates)
        if writing:
            cfg.setdefault("writing", {}).update(writing)
    return cfg


def _read_source(src: str, num: int) -> str:
    base = src if os.path.isabs(src) else os.path.join(ROOT, src)
    with open(os.path.join(base, "第%03d.md" % num), encoding="utf-8", newline="") as f:
        return f.read()


def _clean_fp(channel: str, rec: dict) -> bool:
    """干净对照假阳性：review 出 fail 级条目 / audit 报 violations 即假阳性。"""
    if channel == "review":
        return bool(rec.get("n_fail"))
    return bool(rec.get("n_violations"))


def cmd_scene(queue_path: str, scene_name: str, out_dir: str, budget_cny: float) -> int:
    """跑单场景（子进程入口）：fake home + 干净对照 + 逐雷植入 + 双通道。"""
    queue = load_queue(queue_path)
    scene = next((s for s in queue["scenarios"] if s["name"] == scene_name), None)
    if scene is None:
        raise SystemExit("场景不存在：%s" % scene_name)
    all_defs = {d["id"]: d for d in load_defects()["defects"]}
    defects = scene.get("defects") or queue["_defects"]
    channels = scene.get("channels") or queue["_channels"]
    votes = scene.get("votes") or queue["_votes"]
    overrides = scene.get("overrides") or {}
    home = os.path.join(out_dir, "home_" + scene_name)
    os.makedirs(home)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home
    proj = os.path.join(home, "bench", BOOK)
    shutil.copytree(BASE_BOOK, proj)
    cfg = _build_cfg(queue)
    _mark("场景 %s（雷 %d 颗 × 通道 %s × %d 票，覆盖层 %s）"
          % (scene_name, len(defects), "/".join(channels), votes,
             json.dumps(overrides, ensure_ascii=False)))

    fragment = {"scenario": scene_name, "calls": [], "plant_failures": [],
                "spent_cny": 0.0, "aborted": False}
    spent = 0.0
    runners = RUNNERS

    def _fire(kind, d_id, n, prose, marks):
        nonlocal spent
        if spent > budget_cny:
            fragment["aborted"] = True
            return
        rec = runners[ch](proj, cfg, n, prose, overrides, marks)
        u = rec.pop("usage")
        spent += u["cost_cny"]
        entry = dict(scenario=scene_name, kind=kind, defect=d_id, chapter=n,
                     channel=ch, vote=v, usage=u)
        if kind == "clean":
            entry["fp"] = _clean_fp(ch, rec)
        entry.update(rec)
        fragment["calls"].append(entry)
        if kind == "clean":
            _mark("  [clean %s #%d] %s fp=%s ¥%.3f"
                  % (ch, v, json.dumps({k: rec[k] for k in rec if k != "caught"},
                                       ensure_ascii=False), entry["fp"], u["cost_cny"]))
        else:
            _mark("  [%s %s #%d] caught=%s ¥%.3f"
                  % (d_id, ch, v, rec["caught"], u["cost_cny"]))

    # 干净对照（假阳性检查）→ 逐雷植入；雷失败计 plant_failures（量具失灵可见）
    for n in queue["_chapter_nums"]:
        clean = _read_source(queue["source_drafts"], n)
        for ch in channels:
            for v in range(votes):
                _fire("clean", "", n, clean, [])
        for d_id in defects:
            try:
                planted, _added, _rep = apply_defect(clean, all_defs[d_id])
            except ValueError as e:
                fragment["plant_failures"].append(
                    {"scenario": scene_name, "defect": d_id, "chapter": n, "error": str(e)})
                _mark("  [植入失败] %s × 第%03d：%s" % (d_id, n, e))
                continue
            for ch in channels:
                for v in range(votes):
                    _fire("planted", d_id, n, planted, [queue["_marks"][d_id]])
        if fragment["aborted"]:
            break

    fragment["spent_cny"] = round(spent, 4)
    from app import config as cfg_mod
    src_usage = os.path.join(cfg_mod.CONFIG_DIR, "usage", "usage.jsonl")
    if os.path.isfile(src_usage):   # 场景 usage 切片备份（证据集）
        shutil.copy2(src_usage, os.path.join(out_dir, "usage_%s.jsonl" % scene_name))
    frag_path = os.path.join(out_dir, "fragment_%s.json" % scene_name)
    with open(frag_path, "w", encoding="utf-8") as f:
        json.dump(fragment, f, ensure_ascii=False, indent=1)
    _mark("场景 %s 完成：¥%.3f%s（fragment=%s）"
          % (scene_name, spent, "（熔断中止）" if fragment["aborted"] else "",
             os.path.basename(frag_path)))
    if fragment["plant_failures"]:
        return 1
    return 3 if fragment["aborted"] else 0


# ---------- 父进程：编排、聚合、预算熔断、安全网 ----------

def cmd_run(queue_path: str, gate: bool, baseline_path: str) -> int:
    queue = load_queue(queue_path)
    plan = plan_calls(queue)
    out_dir = os.path.join(OUT_DIR, queue["id"])
    os.makedirs(out_dir, exist_ok=True)
    real_before = _row_count(REAL_USAGE)
    _mark("发车：queue=%s 场景=%d 计划调用=%d 预算上限=¥%.2f（真机台账 %d 行）"
          % (queue["id"], len(queue["scenarios"]), plan["calls"],
             plan["budget_cny_max"], real_before))

    results = {"queue_id": queue["id"], "queue_file": os.path.basename(queue_path),
               "plan": plan, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
               "calls": [], "plant_failures": [], "budget_aborted": False,
               "real_ledger_rows": {"before": real_before}}
    spent = 0.0
    for scene in queue["scenarios"]:
        if spent > queue["budget_cny_max"]:
            results["budget_aborted"] = True
            _mark("预算熔断：已花 ¥%.2f，跳过剩余场景" % spent)
            break
        cmd = [sys.executable, os.path.abspath(__file__), "--queue", queue_path,
               "--_scene", scene["name"], "--_out-dir", out_dir,
               "--_budget-cny", "%.2f" % max(0.0, queue["budget_cny_max"] - spent)]
        proc = subprocess.run(cmd, cwd=ROOT)
        frag_path = os.path.join(out_dir, "fragment_%s.json" % scene["name"])
        if os.path.isfile(frag_path):
            with open(frag_path, encoding="utf-8") as f:
                frag = json.load(f)
            results["calls"].extend(frag["calls"])
            results["plant_failures"].extend(frag["plant_failures"])
            spent += frag["spent_cny"]
            if frag.get("aborted"):
                results["budget_aborted"] = True
                break
        elif proc.returncode not in (0, 3):
            _mark("场景 %s 无产物且退出码 %d（疑似启动失败），中止（宁缺毋假）"
                  % (scene["name"], proc.returncode))
            results["scene_failures"] = results.get("scene_failures", []) + [scene["name"]]
            break

    results["spent_cny"] = round(spent, 4)
    results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    real_after = _row_count(REAL_USAGE)
    results["real_ledger_rows"]["after"] = real_after
    out_path = os.path.join(out_dir, "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    _write_summary(out_dir, results)
    _mark("结果已存：%s（summary.md 同目录）" % out_path)
    if real_after != real_before:
        _mark("[严重] 真机台账行数变化 %d → %d：量具污染真机台账（V8 安全网，exit 2）"
              % (real_before, real_after))
        return 2
    if results["plant_failures"]:
        return 1
    if gate:
        return cmd_gate(out_path, baseline_path)
    return 0


# ---------- 判定与汇总 ----------

def recall_table(results: dict) -> dict:
    """逐 (雷, 通道) 召回率：caught 票 / 有效票。{key: (rate, {caught, votes})}。"""
    agg = {}
    for c in results["calls"]:
        if c.get("kind") != "planted":
            continue
        key = "%s/%s" % (c["defect"], c["channel"])
        e = agg.setdefault(key, {"caught": 0, "votes": 0})
        e["votes"] += 1
        if c.get("caught"):
            e["caught"] += 1
    return {k: (round(v["caught"] / v["votes"], 3) if v["votes"] else 0.0, v)
            for k, v in agg.items()}


def clean_fp_table(results: dict) -> list:
    return [{"scenario": c["scenario"], "chapter": c["chapter"], "channel": c["channel"],
             "vote": c["vote"]}
            for c in results["calls"] if c.get("kind") == "clean" and c.get("fp")]


def gate_regressions(new: dict, old: dict) -> list:
    """逐 (雷, 通道) 召回率对比；新 < 旧 即回归（工作指南口径「不降」）。"""
    new_t, old_t = recall_table(new), recall_table(old)
    return [{"defect_channel": key, "old": old_t[key][0], "new": new_t[key][0]}
            for key in sorted(set(new_t) & set(old_t))
            if new_t[key][0] < old_t[key][0]] + \
           [{"defect_channel": key, "old": "（基线无）", "new": new_t[key][0]}
            for key in sorted(set(new_t) - set(old_t))]


def cmd_gate(results_path: str, baseline_path: str) -> int:
    if not baseline_path or not os.path.isfile(baseline_path):
        _mark("--gate 需要 --baseline 指向历史 results.json（收到：%r）" % baseline_path)
        return 2
    with open(results_path, encoding="utf-8") as f:
        new = json.load(f)
    with open(baseline_path, encoding="utf-8") as f:
        old = json.load(f)
    regs = gate_regressions(new, old)
    fps = clean_fp_table(new)
    table_new, table_old = recall_table(new), recall_table(old)
    _mark("雷章门判定：基线=%s" % os.path.basename(baseline_path))
    for key in sorted(set(table_new) | set(table_old)):
        old_r = table_old.get(key, (None, {}))[0]
        _mark("  %-12s 基线=%s → 本次=%.2f%s"
              % (key, "—" if old_r is None else "%.2f" % old_r,
                 table_new[key][0] if key in table_new else 0,
                 "  [回归]" if any(r["defect_channel"] == key for r in regs) else ""))
    if fps:
        _mark("假阳性 %d 笔：%s" % (len(fps), json.dumps(fps, ensure_ascii=False)))
    if regs:
        _mark("门判定：不通过（召回回归 %d 项，exit 1）" % len(regs))
        return 1
    if fps:
        _mark("门判定：不通过（干净对照假阳性，exit 1）")
        return 1
    _mark("门判定：通过（召回不降 + 零假阳性）")
    return 0


def _write_summary(out_dir: str, results: dict) -> None:
    table = recall_table(results)
    fps = clean_fp_table(results)
    lines = ["# 雷章召回重放 · %s" % results["queue_id"], "",
             "- 起止：%s → %s" % (results["started"], results["finished"]),
             "- 实花：¥%.3f / 预算上限 ¥%.2f%s"
             % (results.get("spent_cny", 0), results["plan"]["budget_cny_max"],
                "（**熔断中止**）" if results.get("budget_aborted") else ""),
             "- 植入失败：%d 处%s" % (len(results.get("plant_failures", [])),
                                     "（量具失灵，须修）" if results.get("plant_failures") else ""),
             "- 假阳性：%d 笔%s" % (len(fps), "（**门不通过**）" if fps else ""), "",
             "| 雷/通道 | 召回 | 票数 |", "|---|---|---|"]
    for key, (rate, v) in sorted(table.items()):
        lines.append("| %s | %.2f | %d/%d |" % (key, rate, v["caught"], v["votes"]))
    if results.get("plant_failures"):
        lines += ["", "## 植入失败", ""]
        lines += ["- %s × 第%03d：%s" % (p["defect"], p["chapter"], p["error"])
                  for p in results["plant_failures"]]
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------- dry-run / list / CLI ----------

def cmd_dry_run(queue_path: str) -> int:
    queue = load_queue(queue_path)
    plan = plan_calls(queue)
    _mark("dry-run：queue=%s 场景=%d 计划调用=%d 预算上限=¥%.2f"
          % (queue["id"], len(queue["scenarios"]), plan["calls"], plan["budget_cny_max"]))
    for s in plan["scenarios"]:
        _mark("  场景 %s：雷 %s × 章 %s × 通道 %s × %d 票 = %d 笔"
              % (s["name"], ",".join(s["defects"]), queue["_chapter_nums"],
                 "/".join(s["channels"]), s["votes"], s["calls"]))
    all_defs = {d["id"]: d for d in load_defects()["defects"]}
    failures = 0
    for n in queue["_chapter_nums"]:
        clean = _read_source(queue["source_drafts"], n)
        _mark("  第%03d.md：%d 字%s" % (n, len(clean),
              "（超 audit 预扫可见上限 %d，尾部落雷不可见）" % AUDIT_PROSE_CAP
              if len(clean) > AUDIT_PROSE_CAP else ""))
        for d_id in queue["_defects"]:
            if queue["_marks"][d_id] in clean:
                _mark("  [失败] %s 标记串天然存在于干净稿（干净对照必假阳性，换标记）：%r"
                      % (d_id, queue["_marks"][d_id]))
                failures += 1
            try:
                planted, _added, _rep = apply_defect(clean, all_defs[d_id])
            except ValueError as e:
                _mark("  [失败] %s × 第%03d：植入失败：%s" % (d_id, n, e))
                failures += 1
                continue
            if queue["_marks"][d_id] not in planted:
                _mark("  [失败] %s × 第%03d：植入后标记串不可见（量具失灵）" % (d_id, n))
                failures += 1
    if failures:
        _mark("dry-run 失败：植入失灵 %d 处（exit 1）" % failures)
        return 1
    _mark("dry-run 通过：植入演练 %d 处全部成功，零 API"
          % (len(queue["_defects"]) * len(queue["_chapter_nums"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="雷章召回重放量具（v16 P0）：雷集→review/audit 双通道→召回判定")
    ap.add_argument("--queue", help="队列文件（presets+queue）")
    ap.add_argument("--dry-run", action="store_true", help="零 API：校验+植入演练+计划")
    ap.add_argument("--gate", action="store_true", help="与基线对比召回（须配 --baseline）")
    ap.add_argument("--baseline", default="", help="基线 results.json 路径")
    ap.add_argument("--list", action="store_true", help="列出雷集（转发 plant_defects）")
    ap.add_argument("--_scene", help=argparse.SUPPRESS)   # 子进程入口：单场景
    ap.add_argument("--_out-dir", help=argparse.SUPPRESS)
    ap.add_argument("--_budget-cny", default="3.0", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.list:
        from scripts.plant_defects import cmd_list
        return cmd_list()
    if args._scene:   # 子进程：跑单场景
        out_dir = args._out_dir or os.path.join(OUT_DIR, "_adhoc")
        os.makedirs(out_dir, exist_ok=True)
        return cmd_scene(args.queue, args._scene, out_dir, float(args._budget_cny))
    if not args.queue:
        ap.error("需要 --queue <队列文件>（--list 可单用）")
        return 2
    if args.gate and not args.baseline:
        ap.error("--gate 需要同时给 --baseline <历史 results.json>")
        return 2
    if args.dry_run:
        return cmd_dry_run(args.queue)
    return cmd_run(args.queue, args.gate, args.baseline)


if __name__ == "__main__":
    sys.exit(main())
