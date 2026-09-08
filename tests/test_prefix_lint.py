# -*- coding: utf-8 -*-
"""prefix_lint（W0.1 前缀卫生 lint）单测：对当前仓库全绿 + 各层可独立注入验证

运行：
    python -m pytest tests/test_prefix_lint.py -q
"""
import ast
import os
import sys
import types

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

import prefix_lint as pl


# ---------- A 层：AST 模板占位符断言 ----------

def _fake_prompts(**tmpl):
    m = types.SimpleNamespace(**tmpl)
    return m


def test_ast_layer_detects_missing_placeholder(tmp_path):
    """0.18.4 七处静默丢参 bug 的回放：keywords 传了 chapter_header=，模板却没有占位符"""
    src = (
        "from .. import prompts\n"
        "def f(hdr, proj):\n"
        "    return prompts.BAD_TMPL.format(chapter_header=hdr, x=1)\n"
        "    return prompts.GOOD_TMPL.format(chapter_header=hdr, project_header=proj)\n"
    )
    p = tmp_path / "stage_bad.py"
    p.write_text(src, encoding="utf-8")
    prompts_mod = _fake_prompts(BAD_TMPL="阶段体 {x}（没有头部占位符）",
                                GOOD_TMPL="{project_header}\n\n{chapter_header}\n\n阶段体")
    violations = pl.check_file(str(p), prompts_mod)
    assert len(violations) == 1
    _path, lineno, name, kw, why = violations[0]
    assert lineno == 3 and name == "BAD_TMPL" and kw == "chapter_header"
    assert "静默丢弃" in why


def test_ast_layer_passes_correct_templates(tmp_path):
    src = (
        "from .. import prompts\n"
        "def f(hdr, proj):\n"
        "    return prompts.GOOD_TMPL.format(chapter_header=hdr, project_header=proj)\n"
    )
    p = tmp_path / "stage_good.py"
    p.write_text(src, encoding="utf-8")
    prompts_mod = _fake_prompts(GOOD_TMPL="{project_header}\n\n{chapter_header}\n\n阶段体")
    assert pl.check_file(str(p), prompts_mod) == []


def test_ast_layer_flags_unexported_template(tmp_path):
    """模板没从 app.prompts 导出（getattr 落空）→ 报违规让人工确认"""
    src = (
        "from .. import prompts\n"
        "def f(hdr):\n"
        "    return prompts.MISSING.format(chapter_header=hdr)\n"
    )
    p = tmp_path / "stage_missing.py"
    p.write_text(src, encoding="utf-8")
    violations = pl.check_file(str(p), _fake_prompts())
    assert len(violations) == 1 and "取不到" in violations[0][4]


def test_prompts_alias_detection_variants(tmp_path):
    """from .. import prompts / from ..prompts import x / from app import prompts 都算 prompts 别名"""
    cases = [
        "from .. import prompts\n",
        "from ..prompts import scene_cards\n",
        "from app import prompts\n",
        "def _x():\n    from .. import prompts\n    return prompts\n",
    ]
    for i, head in enumerate(cases):
        tree = ast.parse(head)
        assert pl._prompts_aliases(tree), "case %d 未识别到 prompts 别名" % i


def test_find_format_calls_ignores_non_prompts(tmp_path):
    src = (
        "class cfg:\n    T = '{a}'\n"
        "cfg.T.format(a=1)\n"          # 非 prompts 模块 → 不在检查范围
        "vars({'a': 1})\n"
    )
    tree = ast.parse(src)
    assert pl.find_format_calls(tree, {"prompts"}) == []


# ---------- B 层：动态确定性 ----------

def test_determinism_layer_green_on_current_repo():
    """最小项目上 project_header / chapter_header 两次生成逐字节一致"""
    assert pl.check_determinism() == []


# ---------- C 层：动态值扫描 ----------

def test_scan_layer_detects_forbidden_tokens(tmp_path):
    p = tmp_path / "shared_prefix.py"
    p.write_text(
        "import datetime\n"
        "import uuid\n"
        "ts = time.time()\n"
        "rid = uuid.uuid4()\n"
        "roll = random.randint(0, 1)\n"
        "x = t.now()\n",
        encoding="utf-8")
    violations = pl.scan_dynamic_values(str(p))
    hits = [v[2] for v in violations]
    assert "datetime" in hits and "uuid" in hits
    assert "time.time" in hits and "random" in hits and "now(" in hits
    assert len(violations) == 6


def test_scan_layer_skips_pure_comments(tmp_path):
    p = tmp_path / "shared_prefix.py"
    p.write_text("# 注释里提到 datetime / uuid / random 不算违规\n"
                 "ok = 1\n", encoding="utf-8")
    assert pl.scan_dynamic_values(str(p)) == []


def test_scan_layer_clean_on_current_repo():
    assert pl.scan_dynamic_values(os.path.join(os.getcwd(), "app", "core", "shared_prefix.py")) == []


# ---------- 全仓库（当前真实代码必须全绿） ----------

def test_full_lint_green_on_current_repo():
    """三层全跑：当前仓库若有真实违规这里会红——那是审计发现，不是测试写错"""
    violations = pl.run_lint(os.getcwd(), dynamic=True)
    assert violations == []


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(pl, "run_lint", lambda *a, **k: [
        ("app/core/stages.py", 100, "X_PROMPT", "chapter_header", "模板缺占位符")])
    assert pl.main([]) == 1
    out = capsys.readouterr().out
    assert "1 处违规" in out and "chapter_header" in out
    monkeypatch.setattr(pl, "run_lint", lambda *a, **k: [])
    assert pl.main([]) == 0
    assert "全绿" in capsys.readouterr().out
