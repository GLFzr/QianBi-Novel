# -*- coding: utf-8 -*-
"""bench_queue（W0.2 挂机队列器）单测：解析/计划、全停条件、usage 备份、晨报生成

不触网、不跑真变体：执行路径全部用注入 runner / monkeypatch subprocess。运行：
    python -m pytest tests/test_bench_queue.py -q
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

import pytest

import bench_queue as bq

REAL_IS_PEAK = bq.is_peak     # 测试里要测真函数本身（autouse 夹具会替换模块属性）


# ---------- 夹具 ----------

@pytest.fixture()
def bench_dir(tmp_path, monkeypatch):
    """把 BENCH 指到临时目录：测试永不碰 tests_output/ 真实产物"""
    d = tmp_path / "bench"
    d.mkdir()
    monkeypatch.setattr(bq, "BENCH", str(d))
    return str(d)


@pytest.fixture()
def repo_dir(tmp_path):
    """伪仓库根：让 git_snapshot 的 glob 落空（无产物→跳过，绝不执行真 git）"""
    d = tmp_path / "repo"
    (d / "tests_output" / "bench").mkdir(parents=True)
    return str(d)


@pytest.fixture(autouse=True)
def off_peak(monkeypatch):
    """执行类测试与真实时钟解耦：默认恒为 off-peak（peak 行为有专测）"""
    monkeypatch.setattr(bq, "is_peak", lambda *a, **k: False)


def _write_queue(path, **kw):
    q = {"id": "t1", "budget_cny_max": 10.0,
         "variants": [{"name": "v1", "args": {}},
                      {"name": "v2", "args": {}}]}
    q.update(kw)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False)
    return str(path)


def _runner(rcs):
    """按脚本返回退出码的假 runner；记录每次调用"""
    calls = []

    def run(cmd, log_path, cwd):
        calls.append({"cmd": cmd, "log_path": log_path, "cwd": cwd})
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("fake run %d\n" % len(calls))
        return rcs[min(len(calls), len(rcs)) - 1]

    run.calls = calls
    return run


# ---------- 队列文件解析 ----------

def test_load_queue_ok(tmp_path):
    p = _write_queue(tmp_path / "q.json")
    q = bq.load_queue(p)
    assert q["id"] == "t1" and len(q["variants"]) == 2


def test_load_queue_missing_file(tmp_path):
    with pytest.raises(SystemExit, match="读不到"):
        bq.load_queue(str(tmp_path / "nope.json"))


def test_load_queue_bad_json(tmp_path):
    p = tmp_path / "q.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="合法 JSON"):
        bq.load_queue(str(p))


def test_load_queue_requires_id_and_variants(tmp_path):
    p = tmp_path / "q.json"
    p.write_text('{"budget_cny_max": 1}', encoding="utf-8")
    with pytest.raises(SystemExit, match="id"):
        bq.load_queue(str(p))
    p.write_text('{"id": "x", "variants": []}', encoding="utf-8")
    with pytest.raises(SystemExit, match="variants"):
        bq.load_queue(str(p))


def test_load_queue_validates_variant_presets(tmp_path, repo_dir):
    bad = str(tmp_path / "bad_preset.json")   # 不存在
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"id": "x", "budget_cny_max": 1,
                             "variants": [{"name": "v", "args": {"preset": bad}}]}),
                 encoding="utf-8")
    with pytest.raises(SystemExit, match="预设"):
        bq.load_queue(str(q), root=repo_dir)
    # 合法预设通过
    ok = tmp_path / "preset.json"
    ok.write_text('{"stage_params": {}}', encoding="utf-8")
    (tmp_path / "q2.json").write_text(json.dumps(
        {"id": "x", "budget_cny_max": 1,
         "variants": [{"name": "v", "args": {"preset": str(ok)}}]}), encoding="utf-8")
    assert bq.load_queue(str(tmp_path / "q2.json"))["variants"][0]["name"] == "v"


# ---------- 命令构造 ----------

def test_build_cmd():
    cmd = bq.build_cmd({"name": "v1", "args": {
        "preset": "tests/bench_variants/x.json", "chapters": 3,
        "seed_drafts": "tests_output/bench/seed_drafts",
        "user_id": "bench-v1", "extra": ["--fast-path"]}})
    assert cmd[1:4] == ["scripts/cost_bench.py", "--variant", "v1"]
    assert "--preset-params" in cmd
    assert cmd[cmd.index("--preset-params") + 1] == "@tests/bench_variants/x.json"
    assert cmd[cmd.index("--chapters") + 1] == "3"
    assert cmd[cmd.index("--seed-drafts") + 1] == "tests_output/bench/seed_drafts"
    assert cmd[cmd.index("--user-id") + 1] == "bench-v1"
    assert cmd[-1] == "--fast-path"


def test_build_cmd_minimal():
    cmd = bq.build_cmd({"name": "v", "args": {}})
    assert cmd == [sys.executable, "scripts/cost_bench.py", "--variant", "v"]


# ---------- dry-run：只打印计划，不执行 ----------

def test_dry_run_prints_plan_without_subprocess(tmp_path, bench_dir, repo_dir, monkeypatch, capsys):
    launched = []

    def no_subprocess(*a, **k):
        launched.append(a)
        raise AssertionError("dry-run 不得执行子进程")

    monkeypatch.setattr(bq.subprocess, "run", no_subprocess)
    q = _write_queue(tmp_path / "q.json", variants=[
        {"name": "v1", "args": {"preset": "tests/bench_variants/e11_span_trim.json",
                                "chapters": 3}}])
    rc = bq.main(["--queue", str(q), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "v1" in out and "--variant v1" in out
    assert launched == []
    assert os.listdir(bench_dir) == []               # 没有产生任何日志/产物


def test_peak_gate_blocks_without_force(bench_dir, repo_dir, monkeypatch):
    monkeypatch.setattr(bq, "is_peak", lambda: True)   # 覆盖 autouse 的 off-peak
    runner = _runner([0, 0])
    q = {"id": "t", "budget_cny_max": 10, "variants": [{"name": "v1", "args": {}},
                                                       {"name": "v2", "args": {}}]}
    s = bq.run_queue(q, runner=runner, bench=bench_dir, root=repo_dir)
    assert s["launched"] is False and "--force" in s["stop_reason"]
    assert runner.calls == []          # peak 拒发：一个变体都没跑
    s2 = bq.run_queue(q, runner=runner, force=True, bench=bench_dir, root=repo_dir)
    assert s2["launched"] is True and len(s2["results"]) == 2


def test_is_peak_fixed_datetimes():
    import datetime
    is_peak = REAL_IS_PEAK
    sat = datetime.datetime(2026, 9, 5, 10, 0)      # 周六
    mon_night = datetime.datetime(2026, 9, 7, 23, 0)
    mon_peak1 = datetime.datetime(2026, 9, 7, 10, 0)
    mon_off1 = datetime.datetime(2026, 9, 7, 13, 0)
    mon_peak2 = datetime.datetime(2026, 9, 7, 15, 0)
    assert is_peak(sat) is False                  # 周末全天 off-peak
    assert is_peak(mon_night) is False
    assert is_peak(mon_peak1) is True             # 9-12
    assert is_peak(mon_off1) is False             # 12-14 off-peak
    assert is_peak(mon_peak2) is True             # 14-18


# ---------- 全停条件 ----------

def test_stop_after_three_consecutive_failures(bench_dir, repo_dir):
    runner = _runner([1, 1, 1, 0, 0])
    q = {"id": "t", "budget_cny_max": None,
         "variants": [{"name": "v%d" % i, "args": {}} for i in range(1, 6)]}
    s = bq.run_queue(q, runner=runner, bench=bench_dir, root=repo_dir)
    assert len(runner.calls) == 3                    # 第 3 连败即全停，第 4 个不放行
    assert "连续 3 个变体失败" in s["stop_reason"]
    assert [r["ok"] for r in s["results"]] == [False, False, False]


def test_single_failure_skips_and_continues(bench_dir, repo_dir):
    runner = _runner([0, 1, 0, 0, 0])
    q = {"id": "t", "budget_cny_max": None,
         "variants": [{"name": "v%d" % i, "args": {}} for i in range(1, 6)]}
    s = bq.run_queue(q, runner=runner, bench=bench_dir, root=repo_dir)
    assert len(runner.calls) == 5                    # 单败不回炉也不全停
    assert [r["ok"] for r in s["results"]] == [True, False, True, True, True]
    assert s["results"][1]["brief"]                  # 失败有异常摘要
    assert s["stop_reason"] == "队列全部变体跑完"


def test_budget_overshoot_stops(bench_dir, repo_dir):
    def runner_writes_costly_metrics(cmd, log_path, cwd):
        name = cmd[cmd.index("--variant") + 1]
        with open(os.path.join(bench_dir, "%s.metrics.json" % name), "w",
                  encoding="utf-8") as f:
            json.dump({"variant": name, "cost_cny": 16.0}, f)
        return 0

    q = {"id": "t", "budget_cny_max": 10.0,       # 全停线 = 15.0
         "variants": [{"name": "v1", "args": {}}, {"name": "v2", "args": {}}]}
    s = bq.run_queue(q, runner=runner_writes_costly_metrics, bench=bench_dir, root=repo_dir)
    assert len(s["results"]) == 1                    # 第一个变体 16 > 15 → 不放行下一个
    assert "全停线" in s["stop_reason"] and s["total_cost_cny"] == pytest.approx(16.0)


def test_runner_crash_recorded_and_continues(bench_dir, repo_dir):
    def exploding_runner(cmd, log_path, cwd):
        if cmd[cmd.index("--variant") + 1] == "v1":
            raise OSError("boom")
        return 0

    q = {"id": "t", "budget_cny_max": None,
         "variants": [{"name": "v1", "args": {}}, {"name": "v2", "args": {}}]}
    s = bq.run_queue(q, runner=exploding_runner, bench=bench_dir, root=repo_dir)
    assert [r["ok"] for r in s["results"]] == [False, True]
    assert "boom" in s["results"][0]["brief"] or "runner" in s["results"][0]["brief"]


# ---------- usage 备份（0.18.4 误截断 544 行的教训） ----------

def test_backup_usage_copies_slice(bench_dir):
    usage = os.path.join(bench_dir, "v1", ".qianbi_novel", "usage")
    os.makedirs(usage)
    with open(os.path.join(usage, "usage.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"model": "deepseek-v4-flash"}\n' * 544)   # 复刻 544 行场景
    dst = bq.backup_usage("v1", bench=bench_dir)
    assert dst == os.path.join(bench_dir, "v1.usage.jsonl")
    with open(dst, encoding="utf-8") as f:
        assert sum(1 for _ in f) == 544


def test_backup_usage_missing(bench_dir):
    assert bq.backup_usage("ghost", bench=bench_dir) == ""


def test_backup_runs_after_each_variant(bench_dir, repo_dir, monkeypatch):
    """每个变体跑完立刻有 usage 切片，不是收尾才补"""
    usage = {}

    def runner(cmd, log_path, cwd):
        name = cmd[cmd.index("--variant") + 1]
        d = os.path.join(bench_dir, name, ".qianbi_novel", "usage")
        os.makedirs(d)
        with open(os.path.join(d, "usage.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"a": 1}\n')
        return 0

    seen = []
    orig = bq.backup_usage

    def spy(name, bench=""):
        p = orig(name, bench=bench)
        seen.append((name, os.path.isfile(p) if p else False))
        return p

    monkeypatch.setattr(bq, "backup_usage", spy)
    q = {"id": "t", "budget_cny_max": None,
         "variants": [{"name": "v1", "args": {}}, {"name": "v2", "args": {}}]}
    bq.run_queue(q, runner=runner, bench=bench_dir, root=repo_dir)
    assert [n for n, _ in seen] == ["v1", "v2"]        # 每变体一次、按序
    assert all(ok for _, ok in seen)


# ---------- 晨报生成 ----------

def test_metrics_cost(bench_dir):
    assert bq.metrics_cost("nope", bench=bench_dir) is None
    with open(os.path.join(bench_dir, "v1.metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"cost_cny": 1.234}, f)
    assert bq.metrics_cost("v1", bench=bench_dir) == 1.234


def test_night_report_generation(bench_dir):
    for name, cny in (("v1", 0.647), ("v2", 0.512)):
        with open(os.path.join(bench_dir, "%s.metrics.json" % name), "w",
                  encoding="utf-8") as f:
            json.dump({"variant": name, "calls": 24, "input_tok": 463394,
                       "hit_pct": 78.7, "out_tok": 99317, "reasoning_tok": 68772,
                       "cost_cny": cny, "llm_seconds": 1383.3,
                       "miss_tok": 98722, "chapters": [{"num": 1}]}, f)
    results = [{"name": "v1", "rc": 0, "ok": True, "cost_cny": 0.647,
                "log_path": "", "brief": ""},
               {"name": "v2", "rc": 1, "ok": False, "cost_cny": 0.512,
                "log_path": "", "brief": "连接超时"}]
    path = bq.gen_night_report("tq1", results, stop_reason="测试停止",
                               total_cost=1.159, budget=12.0, bench=bench_dir)
    text = open(path, encoding="utf-8").read()
    assert os.path.basename(path) == "night_report_tq1.md"
    assert "| v1 | 24 | 463,394 | 78.7% | 99,317 | 68,772 | 0.647 | OK | — |" in text
    assert "FAIL" in text and "连接超时" in text
    assert "cost¥" in text and "hit%" in text            # 对比表（--compare 同构列头）
    assert "0.647" in text and "0.512" in text
    assert "测试停止" in text


def test_night_report_without_metrics(bench_dir):
    results = [{"name": "ghost", "rc": 1, "ok": False, "cost_cny": None,
                "log_path": "", "brief": "退出码 1"}]
    path = bq.gen_night_report("tq2", results, stop_reason="全停", bench=bench_dir)
    text = open(path, encoding="utf-8").read()
    assert "| ghost |" in text and "FAIL" in text


def test_full_run_generates_report(bench_dir, repo_dir):
    runner = _runner([0, 0])
    q = {"id": "tq3", "budget_cny_max": 10,
         "variants": [{"name": "v1", "args": {}}, {"name": "v2", "args": {}}]}
    s = bq.run_queue(q, runner=runner, bench=bench_dir, root=repo_dir)
    assert s["launched"] is True and os.path.isfile(s["report_path"])
    assert os.path.basename(s["report_path"]) == "night_report_tq3.md"


# ---------- 对比表（格式对齐 cost_bench --compare） ----------

def test_compare_table_alignment(bench_dir):
    with open(os.path.join(bench_dir, "base.metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"variant": "base", "cost_cny": 0.647, "hit_pct": 78.7,
                   "miss_tok": 98722, "out_tok": 99317, "reasoning_tok": 68772,
                   "llm_seconds": 1383, "chapters": [{}, {}, {}]}, f)
    with open(os.path.join(bench_dir, "v1.metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"variant": "v1", "cost_cny": 0.323, "hit_pct": 80.1,
                   "miss_tok": 40000, "out_tok": 50000, "reasoning_tok": 30000,
                   "llm_seconds": 900, "chapters": [{}, {}, {}]}, f)
    table = bq.compare_table(bench_dir)
    lines = table.splitlines()
    assert lines[0].split()[0] == "variant" and lines[0].split()[1] == "cost¥"
    assert "(-50% vs base)" in lines[2] or "(-50% vs base)" in lines[1]


# ---------- 证据归档（tests_output 被 gitignore，缺 -f 即静默零归档）----------

def _fake_repo(tmp_path):
    """造一个只含证据文件的伪仓库：fake home 目录里塞会话栈，必须被排除"""
    root = tmp_path / "repo"
    b = root / "tests_output" / "bench"
    (b / "t1_long20" / "会话").mkdir(parents=True)
    (b / "t1_long20.chapters").mkdir(parents=True)
    (b / "t1_long20" / "会话" / "卷1_messages.jsonl").write_text("x" * 5000,
                                                                encoding="utf-8")
    (b / "t1_long20.chapters" / "第001章_锚.md").write_text("正文", encoding="utf-8")
    for fn in ("t1_long20.metrics.json", "t1_long20.usage.jsonl",
               "t1_long20.queue.log", "t1_long20.run.log", "t1_long20.notes.txt",
               "s1_volume.metrics.json"):
        (b / fn).write_text("{}", encoding="utf-8")
    return str(root)


def test_evidence_paths_keeps_only_evidence(tmp_path):
    root = _fake_repo(tmp_path)
    got = [os.path.basename(p) for p in bq.evidence_paths("t1_long20", root)]
    assert got == ["t1_long20.chapters", "t1_long20.metrics.json", "t1_long20.queue.log",
                   "t1_long20.run.log", "t1_long20.usage.jsonl"]
    assert "t1_long20" not in got and "t1_long20.notes.txt" not in got


def test_git_snapshot_force_adds_and_commits(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bq.subprocess, "run", fake_run)
    assert bq.git_snapshot("t1_long20", "t1_long20_20260907", root) == ""
    add, cmt = seen
    assert add[:4] == ["git", "add", "-f", "--"]
    assert any(p.endswith("t1_long20.chapters") for p in add)
    assert not any(p.rstrip("/\\").endswith(os.path.join("bench", "t1_long20")) for p in add)
    assert cmt[:2] == ["git", "commit"] and "5 件证据" in cmt[-1]


def test_git_snapshot_reports_empty_evidence(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path)
    monkeypatch.setattr(bq.subprocess, "run",
                        lambda *a, **k: pytest.fail("无证据文件不该动 git"))
    assert "无证据文件" in bq.git_snapshot("never_ran", "q", root)


def test_git_snapshot_treats_nothing_to_commit_as_clean(tmp_path, monkeypatch):
    root = _fake_repo(tmp_path)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        rc = 1 if cmd[1] == "commit" else 0
        return subprocess.CompletedProcess(cmd, rc, "", "nothing to commit, working tree clean")

    monkeypatch.setattr(bq.subprocess, "run", fake_run)
    assert bq.git_snapshot("t1_long20", "q", root) == ""
