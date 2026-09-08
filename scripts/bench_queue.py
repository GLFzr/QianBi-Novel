#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""挂机队列器（W0.2 / 工作指南 §5）：夜间逐变体串行跑 cost_bench，备份+归档+晨报

行为规范（§5.2，即本文件的 DoD）：
  1. 逐变体串行执行 cost_bench.py --variant <v> ...；每变体跑完立即
     usage 备份切片（0.18.4 误截断 544 行的教训），再启动下一个；
  2. 单变体失败：捕获、日志落 <variant>.queue.log、跳过继续下一个
     （一夜不因一个变体报废）；
  3. 全停条件只有两个：连续 3 个变体失败（疑似平台/网络级故障）、
     或累计成本（各变体 metrics.json 的 cost_cny）超队列预算 ×1.5；
  4. 收尾产出晨报 tests_output/bench/night_report_<queue_id>.md：
     每变体一行 + 对比表（直接读 *.metrics.json 自算，格式对齐 cost_bench --compare）；
  5. 每变体完成即 git add -f 证据集（<variant>.metrics.json / .usage.jsonl / 跑志 /
     <variant>.chapters 正文）&& git commit（产物即证据——5 章 e2e 被 rmtree 的教训；
     tests_output/ 整目录在 .gitignore 里，**必须 -f** 否则 git 直接拒绝、静默零归档；
     fake home 会话栈几 MB 且可再生，刻意不入库；失败只警告不阻断）。

发车检查（§5.1 自动化项）：git 非干净只警告；peak 时段（工作日 9-12/14-18 点）
拒绝发车，--force 才继续。

用法：
  python scripts/bench_queue.py --queue tests/bench_variants/queue_r1.json --dry-run
  python scripts/bench_queue.py --queue tests/bench_variants/queue_r1.json           # 实跑
  python scripts/bench_queue.py --queue ... --force                                  # peak 强行发车

队列文件 schema：
  {"id": "r1_20260907", "budget_cny_max": 12.0,
   "variants": [{"name": "e11_span_trim",
                 "args": {"preset": "tests/bench_variants/e11_span_trim.json",
                          "chapters": 3,
                          "seed_drafts": "tests_output/bench/seed_drafts",
                          "extra": ["--fast-path"]}}]}
"""
from __future__ import annotations

import argparse
import datetime
import glob
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
BENCH = os.path.join(ROOT, "tests_output", "bench")
STOP_CONSEC_FAILS = 3          # §5.2 全停条件一：连续失败数
BUDGET_OVERSHOOT = 1.5         # §5.2 全停条件二：累计成本 > 预算 ×1.5
PEAK_WINDOWS = ((9, 12), (14, 18))   # 工作日 peak 时段（off-peak 之外的全价窗）


def _mark(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _rel(path: str, root: str = ROOT) -> str:
    """相对路径显示；跨盘符（Windows）等 relpath 失败时退回原路径"""
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


# ---------- 队列文件（§5.1 检查单的自动化部分） ----------

def load_queue(path: str, root: str = ROOT) -> dict:
    """读 + 校验队列文件：schema 违规 / 预设 JSON 不合法 → SystemExit（发车前拦截）"""
    try:
        with open(path, encoding="utf-8") as f:
            q = json.load(f)
    except OSError as e:
        raise SystemExit("队列文件读不到: %s (%s)" % (path, e))
    except ValueError as e:
        raise SystemExit("队列文件不是合法 JSON: %s (%s)" % (path, e))
    if not isinstance(q, dict) or not str(q.get("id") or "").strip():
        raise SystemExit("队列文件缺 id（跑次标识）: " + path)
    if not isinstance(q.get("variants"), list) or not q["variants"]:
        raise SystemExit("队列文件 variants 为空或不是列表: " + path)
    budget = q.get("budget_cny_max")
    if budget is not None and not isinstance(budget, (int, float)):
        raise SystemExit("budget_cny_max 需要数字（或 null＝不限）: " + path)
    for i, entry in enumerate(q["variants"]):
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            raise SystemExit("variants[%d] 缺 name" % i)
        args = entry.get("args") or {}
        if not isinstance(args, dict):
            raise SystemExit("variants[%d].args 需要对象" % i)
        preset = args.get("preset")
        if preset:
            ppath = preset if os.path.isabs(preset) else os.path.join(root, preset)
            try:
                with open(ppath, encoding="utf-8") as f:
                    json.load(f)
            except OSError as e:
                raise SystemExit("variants[%d] 预设打不开: %s (%s)" % (i, ppath, e))
            except ValueError as e:
                raise SystemExit("variants[%d] 预设不是合法 JSON: %s (%s)" % (i, ppath, e))
    return q


def build_cmd(entry: dict) -> list:
    """变体 → cost_bench 命令行（cwd=仓库根执行）。preset 走 @文件（可复现落盘）"""
    args = entry.get("args") or {}
    cmd = [sys.executable, "scripts/cost_bench.py", "--variant", entry["name"]]
    if args.get("preset"):
        cmd += ["--preset-params", "@" + args["preset"]]
    if args.get("chapters") is not None:
        cmd += ["--chapters", str(args["chapters"])]
    if args.get("seed_drafts"):
        cmd += ["--seed-drafts", args["seed_drafts"]]
    if args.get("user_id"):
        cmd += ["--user-id", args["user_id"]]
    cmd += [str(x) for x in (args.get("extra") or [])]
    return cmd


def is_peak(dt: datetime.datetime | None = None) -> bool:
    """工作日 9-12 / 14-18 点为 peak（周末全天 off-peak）"""
    dt = dt or datetime.datetime.now()
    if dt.weekday() >= 5:
        return False
    return any(lo <= dt.hour < hi for lo, hi in PEAK_WINDOWS)


# ---------- 每变体收尾（备份 → 归档） ----------

def backup_usage(name: str, bench: str = "") -> str:
    """usage.jsonl → <bench>/<name>.usage.jsonl（跑完立即切片，防误截断/误清理）"""
    bench = bench or BENCH
    src = os.path.join(bench, name, ".qianbi_novel", "usage", "usage.jsonl")
    if not os.path.isfile(src):
        return ""
    dst = os.path.join(bench, "%s.usage.jsonl" % name)
    shutil.copyfile(src, dst)
    return dst


EVIDENCE_SUFFIXES = (".metrics.json", ".usage.jsonl", ".queue.log", ".run.log")


def evidence_paths(name: str, root: str = ROOT) -> list:
    """变体的证据集（进版本库的部分）：指标/用量切片/跑志 + 盲评正文目录。
    刻意排除 `tests_output/bench/<name>/` 整个 fake home——那是几 MB 的会话栈与
    断点态，可再生也不是结论依据。"""
    out = []
    for p in sorted(glob.glob(os.path.join(root, "tests_output", "bench", name + "*"))):
        base = os.path.basename(p)
        if base == name + ".chapters" and os.path.isdir(p):
            out.append(p)
        elif os.path.isfile(p) and base.endswith(EVIDENCE_SUFFIXES):
            out.append(p)
    return out


def git_snapshot(name: str, queue_id: str, root: str = ROOT) -> str:
    """git add -f 证据集 && git commit；失败只返回警告不抛。

    `.gitignore` 里 tests_output/ 整目录被忽略，**没有 -f 时 git add 直接拒绝**——
    曾经的实现因此静默零归档（E1：`git add --dry-run` 报 ignored）。"""
    paths = evidence_paths(name, root)
    if not paths:
        return "git 归档跳过：tests_output/bench/%s* 无证据文件（指标/用量/正文）" % name
    try:
        add = subprocess.run(["git", "add", "-f", "--"] + paths, cwd=root,
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        if add.returncode != 0:
            return "git add 失败（不阻断）: %s" % (add.stderr or add.stdout).strip()[:200]
        msg = "bench(%s): %s（%d 件证据）" % (queue_id, name, len(paths))
        cmt = subprocess.run(["git", "commit", "-m", msg], cwd=root,
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        if cmt.returncode != 0:
            out = (cmt.stderr or cmt.stdout).strip()
            if "nothing to commit" in out:      # 同变体重跑且产物未变，不是故障
                return ""
            return "git commit 失败（不阻断）: %s" % out[:200]
        return ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return "git 归档异常（不阻断）: %s" % e


def metrics_cost(name: str, bench: str = ""):
    """读 <name>.metrics.json 的 cost_cny；没有 metrics 返回 None"""
    bench = bench or BENCH
    p = os.path.join(bench, "%s.metrics.json" % name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("cost_cny")
    except (OSError, ValueError):
        return None


# ---------- 执行 ----------

def default_runner(cmd: list, log_path: str, cwd: str) -> int:
    """跑一个变体，stdout/stderr 落日志文件，返回退出码"""
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.run(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT)
    return proc.returncode


def _log_tail(log_path: str, n: int = 3) -> str:
    """异常摘要：日志最后 n 行非空内容压成一行"""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
    except OSError:
        return ""
    return " / ".join(lines[-n:])[:300]


# U1-d：瞬时故障判定与退避参数（2026-09-08 凌晨 503 教训：单变体队列标 FAIL 即整队
# 收车，一夜白等）。日志尾部 5xx/网络异常 → 退避后原样重发（长卷续跑走 t3_resume
# 驱动，本重试只救常规体量变体的瞬时故障）。
TRANSIENT_RETRIES = int(os.environ.get("QIANBI_QUEUE_TRANSIENT_RETRIES", "1"))
TRANSIENT_BACKOFF_S = int(os.environ.get("QIANBI_QUEUE_TRANSIENT_BACKOFF_S", "120"))
_TRANSIENT_HINTS = ("503", "SERVICE_BUSY", "502", "504", "429", "timed out",
                    "Timeout", "ConnectionError", "UNEXPECTED_EOF")


def _log_is_transient(log_path: str, n: int = 6) -> bool:
    """日志尾部 n 行含 5xx/网络关键词 → 疑似瞬时故障（可退避重试）"""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
    except OSError:
        return False
    tail = "\n".join(lines[-n:])
    return any(h in tail for h in _TRANSIENT_HINTS)


def run_queue(queue: dict, runner=None, dry_run: bool = False, force: bool = False,
              bench: str = "", root: str = ROOT) -> dict:
    """主循环：逐变体执行 + 备份 + 归档 + 两个全停条件 + 晨报"""
    bench = bench or BENCH
    runner = runner or default_runner
    qid = queue["id"]
    budget = queue.get("budget_cny_max")
    os.makedirs(bench, exist_ok=True)

    if dry_run:
        print("== 队列计划（dry-run，不执行）%s ==" % qid)
        print("预算上限：¥%s（全停线 ×%.1f = ¥%.1f）"
              % (budget if budget is not None else "不限",
                 BUDGET_OVERSHOOT, (budget or 0) * BUDGET_OVERSHOOT))
        for i, entry in enumerate(queue["variants"], 1):
            print("[%d/%d] %s" % (i, len(queue["variants"]), entry["name"]))
            print("  cmd: %s" % " ".join(build_cmd(entry)))
            log = os.path.join(bench, "%s.queue.log" % entry["name"])
            print("  log: %s" % _rel(log, root))
            print("  跑完即备份 usage → tests_output/bench/%s.usage.jsonl，"
                  "随后 git commit（失败仅警告）" % entry["name"])
        print("收尾：night_report_%s.md（逐变体 + 对比表）" % qid)
        return {"queue_id": qid, "results": [], "stop_reason": "dry-run（未执行）",
                "total_cost_cny": 0.0, "report_path": "", "launched": False}

    if is_peak() and not force:
        _mark("当前是工作日 peak 时段（9-12/14-18 点，全价）——拒绝发车；"
              "确认要跑请加 --force（或等 off-peak：工作日 18-24 / 0-9 / 12-14 点与周末）")
        return {"queue_id": qid, "results": [], "stop_reason": "peak 时段未发车（需 --force）",
                "total_cost_cny": 0.0, "report_path": "", "launched": False}

    if subprocess.run(["git", "status", "--porcelain"], cwd=root,
                      capture_output=True, encoding="utf-8",
                      errors="replace").stdout.strip():
        _mark("警告：git 工作区不干净（§5.1 检查单项）——继续执行，但今晚产物与代码改动将混在一起")

    results = []
    total_cost = 0.0
    consec_fails = 0
    stop_reason = ""
    for i, entry in enumerate(queue["variants"], 1):
        name = entry["name"]
        _mark("[%d/%d] 变体 %s 开始…" % (i, len(queue["variants"]), name))
        cmd = build_cmd(entry)
        log_path = os.path.join(bench, "%s.queue.log" % name)
        try:
            rc = runner(cmd, log_path, root)
        except Exception as e:  # noqa: BLE001  队列器自身不因单变体崩
            rc = -1
            with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                lf.write("\n[bench_queue] runner 异常: %r\n" % e)
        # U1-d 瞬时故障退避重试：日志尾部命中 5xx/网络关键词 → 退避后原样重发
        if rc != 0 and TRANSIENT_RETRIES > 0 and _log_is_transient(log_path):
            for attempt in range(1, TRANSIENT_RETRIES + 1):
                _mark("变体 %s 疑似瞬时故障（5xx/网络）——退避 %ds 后重发（第 %d/%d 次）"
                      % (name, TRANSIENT_BACKOFF_S * attempt, attempt, TRANSIENT_RETRIES))
                time.sleep(TRANSIENT_BACKOFF_S * attempt)
                try:
                    rc = runner(cmd, log_path, root)
                except Exception as e:  # noqa: BLE001
                    rc = -1
                    with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                        lf.write("\n[bench_queue] 重试 runner 异常: %r\n" % e)
                if rc == 0:
                    with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                        lf.write("\n[bench_queue] 第 %d 次重试成功\n" % attempt)
                    break
        ok = rc == 0
        # 跑完立即备份 usage（0.18.4 误截断 544 行的教训），再归档再谈下一个
        bak = backup_usage(name, bench)
        if bak:
            _mark("usage 已备份切片 → %s" % _rel(bak, root))
        else:
            _mark("警告：%s 没有可备份的 usage.jsonl" % name)
        warn = git_snapshot(name, qid, root)
        if warn:
            _mark(warn)
        cost = metrics_cost(name, bench)
        if cost is not None:
            total_cost += float(cost or 0)
        tail = _log_tail(log_path)
        results.append({"name": name, "rc": rc, "ok": ok, "cost_cny": cost,
                        "log_path": log_path,
                        "brief": "" if ok else (tail or "退出码 %s" % rc)})
        _mark("变体 %s %s（成本 ¥%s）" % (name, "完成" if ok else "失败（跳过继续）",
                                          cost if cost is not None else "无 metrics"))
        consec_fails = 0 if ok else consec_fails + 1
        if consec_fails >= STOP_CONSEC_FAILS:
            stop_reason = "连续 %d 个变体失败，疑似平台/网络级故障，全停" % consec_fails
            break
        if cost is not None and budget is not None \
                and total_cost > float(budget) * BUDGET_OVERSHOOT:
            stop_reason = ("累计成本 ¥%.3f 超全停线（预算 ¥%s × %.1f = ¥%.1f）"
                           % (total_cost, budget, BUDGET_OVERSHOOT,
                              float(budget) * BUDGET_OVERSHOOT))
            break

    if not stop_reason:
        stop_reason = "队列全部变体跑完" if results else "队列没有变体"
    report = gen_night_report(qid, results, stop_reason=stop_reason,
                              total_cost=total_cost, budget=budget, bench=bench, root=root)
    return {"queue_id": qid, "results": results, "stop_reason": stop_reason,
            "total_cost_cny": total_cost, "report_path": report, "launched": True}


# ---------- 收尾：晨报 ----------

def compare_table(bench: str = "") -> str:
    """读 <bench>/*.metrics.json 自算对比表（格式对齐 cost_bench --compare 现有输出）"""
    bench = bench or BENCH
    files = sorted(f for f in os.listdir(bench) if f.endswith(".metrics.json"))
    if not files:
        return "（还没有 metrics）"
    ms = []
    for f in files:
        try:
            with open(os.path.join(bench, f), encoding="utf-8") as fh:
                ms.append(json.load(fh))
        except (OSError, ValueError):
            continue
    if not ms:
        return "（metrics 全部不可读）"
    base = next((m for m in ms if m.get("variant") == "base"), ms[0])
    out = ["%-14s %8s %7s %9s %9s %9s %8s %6s"
           % ("variant", "cost¥", "hit%", "miss_tok", "out_tok", "reason_tok", "LLM秒", "章")]
    for m in ms:
        bc = base.get("cost_cny") or 0
        d = (m.get("cost_cny", 0) - bc) / bc * 100 if bc else 0
        out.append("%-14s %8.3f %6.1f%% %9s %9s %9s %8.0f %3d  (%+.0f%% vs %s)"
                   % (m.get("variant", "?"), m.get("cost_cny", 0), m.get("hit_pct", 0),
                      f"{m.get('miss_tok', 0):,}", f"{m.get('out_tok', 0):,}",
                      f"{m.get('reasoning_tok', 0):,}", m.get("llm_seconds", 0),
                      len(m.get("chapters") or []), d, base.get("variant", "?")))
    return "\n".join(out)


def gen_night_report(qid: str, results: list, stop_reason: str = "",
                     total_cost: float = 0.0, budget=None, bench: str = "",
                     root: str = ROOT) -> str:
    """晨报：每变体一行 + 对比表 → tests_output/bench/night_report_<qid>.md"""
    bench = bench or BENCH
    lines = ["# 夜间队列晨报 · %s" % qid, "",
             "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "- 预算：¥%s / 全停线（×%.1f）¥%s"
             % (budget if budget is not None else "不限", BUDGET_OVERSHOOT,
                ("%.1f" % (float(budget) * BUDGET_OVERSHOOT)) if budget is not None else "不限"),
             "- 停止原因：%s" % stop_reason,
             "- 本次队列累计成本：¥%.3f" % total_cost,
             "",
             "## 逐变体", "",
             "| 变体 | 调用 | 输入 tok | hit% | 输出 tok | 推理 tok | 成本¥ | 状态 | 异常摘要 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        m = None
        p = os.path.join(bench, "%s.metrics.json" % r["name"])
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                m = None
        if m:
            row = ("| %s | %s | %s | %s%% | %s | %s | %s | %s | %s |"
                   % (r["name"], m.get("calls", "—"), f"{m.get('input_tok', 0):,}",
                      m.get("hit_pct", "—"), f"{m.get('out_tok', 0):,}",
                      f"{m.get('reasoning_tok', 0):,}", m.get("cost_cny", "—"),
                      "OK" if r["ok"] else "FAIL", r.get("brief") or "—"))
        else:
            row = ("| %s | — | — | — | — | — | — | %s | %s |"
                   % (r["name"], "OK（无 metrics？人工核对）" if r["ok"] else "FAIL",
                      r.get("brief") or "退出码 %s" % r["rc"]))
        lines.append(row)
    lines += ["", "## 对比表（全部 metrics，格式对齐 cost_bench --compare）", "",
              "```", compare_table(bench), "```", ""]
    out = os.path.join(bench, "night_report_%s.md" % qid)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bench_queue.py",
        description="挂机队列器（W0.2）：夜间逐变体串行跑 cost_bench，备份+归档+晨报")
    ap.add_argument("--queue", required=True, help="队列 JSON 路径（schema 见文件头）")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="只打印执行计划，不跑不变更任何产物")
    ap.add_argument("--force", action="store_true",
                    help="peak 时段（工作日 9-12/14-18 点）强行发车")
    args = ap.parse_args(argv)

    queue = load_queue(args.queue, root=ROOT)
    os.makedirs(BENCH, exist_ok=True)
    summary = run_queue(queue, dry_run=args.dry_run, force=args.force, bench=BENCH, root=ROOT)
    if args.dry_run:
        return 0
    if not summary["launched"]:
        _mark("未发车：%s" % summary["stop_reason"])
        return 2
    _mark("队列结束：%s｜累计 ¥%.3f｜晨报 → %s"
          % (summary["stop_reason"], summary["total_cost_cny"],
             _rel(summary["report_path"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
