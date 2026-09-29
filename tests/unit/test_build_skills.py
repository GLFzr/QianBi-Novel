# -*- coding: utf-8 -*-
"""E7 skills 导出管线单测（0.23.0）

覆盖：
- 三包产物齐全（SKILL.md/scripts/references/tests 金标 + 顶层 VERSION/marketplace）
- 版本号单源：产物版本 == app/__init__.__version__
- 单源 vendoring：随包引擎/码表与上游源码逐字节一致
- 金标可复现：生成的 CLI 实跑输出 == 构建期金标（deslop/bridge/state-card）
- 构建确定性：两次构建产物逐字节一致；--check 无漂移 / 改动后报漂移
"""
import io
import json
import os
import subprocess
import sys

import pytest

from app import __version__

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_skills  # noqa: E402 - scripts/ 路径注入后导入导出管线

PYTHONDONTWRITEBYTECODE_ENV = dict(os.environ,
                                   PYTHONDONTWRITEBYTECODE="1")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("skills_out"))
    summary = build_skills.build(out, build_skills.read_version())
    return out, summary


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _run_cli(python_file, *args, timeout=120):
    return subprocess.run(
        [sys.executable, python_file, *args], capture_output=True,
        text=True, encoding="utf-8", timeout=timeout,
        env=PYTHONDONTWRITEBYTECODE_ENV)


# ---------------- 产物结构 ----------------

class TestArtifacts:
    def test_three_packages_complete(self, built):
        out, _ = built
        for pkg in ("qianbi-deslop", "qianbi-bridge-codes",
                    "qianbi-state-card"):
            assert os.path.isfile(os.path.join(out, pkg, "SKILL.md"))
            assert os.path.isdir(os.path.join(out, pkg, "scripts"))
            assert os.path.isdir(os.path.join(out, pkg, "tests"))
        for rel in ("VERSION", "README.md", ".claude-plugin/marketplace.json",
                    "qianbi-deslop/references/rule-basis.md",
                    "qianbi-deslop/scripts/deslop_check.py",
                    "qianbi-bridge-codes/references/code-table.md",
                    "qianbi-bridge-codes/scripts/bridge_route.py",
                    "qianbi-state-card/references/state-card-schema.md",
                    "qianbi-state-card/scripts/state_card_validate.py"):
            assert os.path.isfile(os.path.join(out, rel)), rel

    def test_version_single_source(self, built):
        out, _ = built
        assert _read(os.path.join(out, "VERSION")).strip() == __version__
        for pkg in ("qianbi-deslop", "qianbi-bridge-codes",
                    "qianbi-state-card"):
            md = _read(os.path.join(out, pkg, "SKILL.md"))
            assert md.startswith("---\n")
            assert "version: %s" % __version__ in md

    def test_summary_counts_live(self, built):
        _out, summary = built
        # 规则/码表数量从上游源码 live 抽取，非硬编码
        assert summary["qianbi-deslop"]["rules"] == len(
            build_skills.extract_rule_ids(
                build_skills.read_text(build_skills.SRC_DESLOP)))
        assert summary["qianbi-deslop"]["rules"] == 45   # 上游口径 28→45
        assert summary["qianbi-bridge-codes"]["codes"] == 36
        sc = build_skills.extract_state_card_schema(
            build_skills.read_text(build_skills.SRC_STATE_CARD))
        assert len(sc["titles"]) == 7
        assert sc["byte_budget"] == 12 * 1024

    def test_marketplace_lists_three_skills(self, built):
        out, _ = built
        mkt = json.loads(_read(os.path.join(out, ".claude-plugin",
                                            "marketplace.json")))
        skills = mkt["plugins"][0]["skills"]
        assert skills == ["./qianbi-deslop", "./qianbi-bridge-codes",
                          "./qianbi-state-card"]
        assert mkt["plugins"][0]["version"] == __version__


# ---------------- 单源 vendoring ----------------

class TestVendoringFidelity:
    def test_deslop_engine_verbatim(self, built):
        out, _ = built
        vendor = os.path.join(out, "qianbi-deslop", "scripts", "_vendor",
                              "qbn_exported", "qianbi_vendor")
        assert _read(os.path.join(vendor, "deslop.py")) == _read(
            build_skills.SRC_DESLOP)
        assert _read(os.path.join(vendor, "core", "deslop_metrics.py")) == \
            _read(build_skills.SRC_DESLOP_METRICS)

    def test_bridge_codes_verbatim(self, built):
        out, _ = built
        vendor = os.path.join(out, "qianbi-bridge-codes", "scripts",
                              "_vendor", "qbn_exported", "qianbi_vendor")
        assert _read(os.path.join(vendor, "bridge_codes.py")) == _read(
            build_skills.SRC_BRIDGE_CODES)


# ---------------- 金标可复现（生成的 CLI 实跑） ----------------

class TestGoldReproduction:
    def test_deslop_check_json_matches_gold(self, built):
        out, _ = built
        cli = os.path.join(out, "qianbi-deslop", "scripts", "deslop_check.py")
        gold = os.path.join(out, "qianbi-deslop", "tests", "deslop_gold.txt")
        proc = _run_cli(cli, gold, "--json")
        assert proc.returncode == 1  # 金标样章含 blocking，门禁退出码 1
        assert proc.stdout == _read(os.path.join(out, "qianbi-deslop",
                                                 "tests", "deslop_gold.json"))

    def test_deslop_check_rules_lists_all(self, built):
        out, summary = built
        cli = os.path.join(out, "qianbi-deslop", "scripts", "deslop_check.py")
        proc = _run_cli(cli, "--rules")
        assert proc.returncode == 0
        assert str(summary["qianbi-deslop"]["rules"]) in proc.stdout
        assert "not-is-comparison" in proc.stdout

    def test_deslop_clean_text_exit_zero(self, built):
        out, _ = built
        cli = os.path.join(out, "qianbi-deslop", "scripts", "deslop_check.py")
        clean = os.path.join(out, "qianbi-deslop", "tests", "_clean_tmp.txt")
        with io.open(clean, "w", encoding="utf-8", newline="\n") as f:
            f.write("# 第一章 山门\n\n他挑水、劈柴、扫地，一天过去了。\n")
        try:
            assert _run_cli(cli, clean).returncode == 0
        finally:
            os.remove(clean)

    def test_bridge_route_list_matches_gold(self, built):
        out, _ = built
        cli = os.path.join(out, "qianbi-bridge-codes", "scripts",
                           "bridge_route.py")
        proc = _run_cli(cli, "--list", "--json")
        assert proc.returncode == 0
        assert proc.stdout == _read(os.path.join(out, "qianbi-bridge-codes",
                                                 "tests", "bridge_gold.json"))

    def test_bridge_route_single_and_unknown(self, built):
        out, _ = built
        cli = os.path.join(out, "qianbi-bridge-codes", "scripts",
                           "bridge_route.py")
        ok = _run_cli(cli, "--code", "DL")
        assert ok.returncode == 0 and "打脸" in ok.stdout
        assert _run_cli(cli, "--code", "XX").returncode == 2
        route = _run_cli(cli, "--route", "当众", "--json")
        assert route.returncode == 0
        assert any(c["code"] == "DL"
                   for c in json.loads(route.stdout)["codes"])

    def test_state_card_validator_gold_and_bad(self, built):
        out, _ = built
        cli = os.path.join(out, "qianbi-state-card", "scripts",
                           "state_card_validate.py")
        gold = _run_cli(cli, os.path.join(out, "qianbi-state-card", "tests",
                                          "state_card_gold.md"), "--json")
        assert gold.returncode == 0
        assert json.loads(gold.stdout)["ok"] is True
        bad = _run_cli(cli, os.path.join(out, "qianbi-state-card", "tests",
                                         "state_card_bad.md"), "--json")
        assert bad.returncode == 1
        report = json.loads(bad.stdout)
        checks = {p["check"] for p in report["problems"]}
        assert {"column", "budget"} <= checks


# ---------------- 确定性与 --check ----------------

class TestDeterminismAndCheck:
    def test_two_builds_byte_identical(self, tmp_path):
        out_a = str(tmp_path / "a")
        out_b = str(tmp_path / "b")
        build_skills.build(out_a, build_skills.read_version())
        build_skills.build(out_b, build_skills.read_version())
        assert build_skills._tree(out_a) == build_skills._tree(out_b)

    def test_check_mode_pass_and_drift(self, tmp_path, capsys):
        out = str(tmp_path / "repo_skills")
        build_skills.build(out, build_skills.read_version())
        assert build_skills.check(out) == []
        # 手改一个产物文件 → drift 必须报出来
        victim = os.path.join(out, "qianbi-deslop", "SKILL.md")
        with io.open(victim, "a", encoding="utf-8") as f:
            f.write("<!-- 手改漂移 -->\n")
        diffs = build_skills.check(out)
        assert len(diffs) == 1 and "SKILL.md" in diffs[0]
        # 删除一个产物 → 报缺失
        os.remove(os.path.join(out, "VERSION"))
        diffs = build_skills.check(out)
        assert any(d.startswith("缺失") for d in diffs)

    def test_main_check_exit_codes(self, tmp_path):
        out = str(tmp_path / "skills")
        assert build_skills.main(["--out", out, "--quiet"]) == 0
        assert build_skills.main(["--out", out, "--check", "--quiet"]) == 0
        victim = os.path.join(out, "README.md")
        with io.open(victim, "a", encoding="utf-8") as f:
            f.write("drift\n")
        assert build_skills.main(["--out", out, "--check", "--quiet"]) == 1

    def test_state_card_schema_extraction_rejects_mangled_source(self):
        with pytest.raises(RuntimeError):
            build_skills.extract_state_card_schema("BYTE_BUDGET = 1024\n")
