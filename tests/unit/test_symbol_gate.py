# -*- coding: utf-8 -*-
"""符号级 dual_sync 门禁自身的单测（#61）

门禁是**给同步流程用的护栏**，它自己失效同样没人看见：所以这里既测「该报的报得出」
（同名函数悄悄少注入一个字段、清单笔误、登记后 TUI 又动过），也测「不该报的不报」
（注释/空行/换行符/BOM 差异必须算同源），最后拿真仓库验一遍清单不烂、水印不假绿。
"""
import importlib.util
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "dual_sync_check", os.path.join(_ROOT, "scripts", "dual_sync_check.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

REL = "app/core/mod.py"


def _write(root, rel, src, newline="\n", bom=False):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write((("﻿" if bom else "") + src.replace("\n", newline)).encode("utf-8"))


def _gate(tmp_path, gui_src, tui_src, monkeypatch, deferred=None, syms=("fetch",),
          pick="fetch"):
    """造双端临时仓库，跑门禁，取指定符号的状态行"""
    gui, tui = os.path.join(str(tmp_path), "gui"), os.path.join(str(tmp_path), "tui")
    _write(gui, REL, gui_src)
    _write(tui, REL, tui_src)
    monkeypatch.setattr(D, "SHARED_SYMBOLS", {REL: list(syms)})
    monkeypatch.setattr(D, "DEFERRED_SYMBOLS", deferred or {})
    rows = {r["symbol"]: r for r in D.compare_symbols(gui, tui)}
    assert set(rows) == set(syms)
    return rows[pick]


SAME = "def fetch(a, b):\n    return {'x': a, 'y': b}\n"


# ---------- 该报的报得出 ----------

def test_dropped_field_in_body_is_caught(tmp_path, monkeypatch):
    """P4 那一类事故：函数还在、签名没变、只是悄悄不再注入某个字段"""
    row = _gate(tmp_path, SAME, "def fetch(a, b):\n    return {'x': a}\n", monkeypatch)
    assert row["status"] == "DIFF"
    assert row["gui"] != row["tui"] and not row["reason"]


def test_added_kwarg_is_caught_with_signature(tmp_path, monkeypatch):
    row = _gate(tmp_path, "def fetch(a, b, *, phase=''):\n    return b\n",
               "def fetch(a, b):\n    return b\n", monkeypatch)
    assert row["status"] == "DIFF"
    assert "phase" in row["gui_sig"]


def test_symbol_missing_on_tui_side_is_caught(tmp_path, monkeypatch):
    row = _gate(tmp_path, SAME + "\ndef extra(a):\n    return a\n", SAME,
                monkeypatch, syms=("fetch", "extra"), pick="extra")
    assert row["symbol"] == "extra" and row["status"] == "MISSING_TUI"


def test_typo_in_symbol_list_is_caught(tmp_path, monkeypatch):
    """清单笔误/符号被改名 → 必须失败，否则该项永不生效而全绿"""
    row = _gate(tmp_path, SAME, SAME, monkeypatch, syms=("fetcch",), pick="fetcch")
    assert row["status"] == "MISSING_GUI"


def test_watermark_ratchet_catches_tui_side_edit(tmp_path, monkeypatch):
    """登记延后之后 TUI 侧又动过这个符号＝两侧同时漂移，必须炸"""
    import ast
    tui_src = "def fetch(a, b):\n    return {'x': a}\n"
    deferred = {(REL, "fetch"): {"reason": "GUI 先行",
                                 "tui": D._symbol_hash(ast.parse(tui_src), "fetch")}}
    assert _gate(tmp_path, SAME, tui_src, monkeypatch, deferred)["status"] == "DEFERRED"
    moved = _gate(tmp_path, SAME, "def fetch(a, b):\n    return {'x': a, 'y': 1}\n",
                  monkeypatch, deferred)
    assert moved["status"] == "DEFERRED_TUI_MOVED"
    assert moved["status"] not in D.SYMBOL_PASS


def test_stale_deferral_entry_is_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "SHARED_SYMBOLS", {REL: ["fetch"]})
    monkeypatch.setattr(D, "DEFERRED_SYMBOLS",
                        {(REL, "gone"): {"reason": "x", "tui": "0" * 16},
                         ("app/other.py", "fetch"): {"reason": "y", "tui": "0" * 16}})
    assert sorted(D.stale_deferrals()) == [f"{REL}::gone", "app/other.py::fetch"]


# ---------- 不该报的不报 ----------

def test_comments_and_blank_lines_are_not_drift(tmp_path, monkeypatch):
    """AST 摘要只计代码结构：注释/空行/排版自由，不会变成假漂移"""
    doced = 'def fetch(a, b):\n    """取数"""\n    return {\'x\': a, \'y\': b}\n'
    # docstring 计入结构：有无文档串是真差异（会改变模型读到的语义）
    assert _gate(tmp_path, SAME, doced, monkeypatch)["status"] == "DIFF"
    pretty = "# 顶部说明\n\n\n" + doced.replace(
        "    return", "    # 双端各自补的注释\n\n    return")
    assert _gate(tmp_path, doced, pretty, monkeypatch)["status"] == "OK"


def test_eol_and_bom_only_diff_is_identical_for_modules(tmp_path, monkeypatch):
    gui, tui = os.path.join(str(tmp_path), "gui"), os.path.join(str(tmp_path), "tui")
    _write(gui, REL, SAME)
    _write(tui, REL, SAME, newline="\r\n", bom=True)
    monkeypatch.setattr(D, "SHARED_SYMBOLS", {REL: ["*"]})
    monkeypatch.setattr(D, "DEFERRED_SYMBOLS", {})
    assert D.compare_symbols(gui, tui)[0]["status"] == "OK"


def test_class_method_lookup_uses_same_symbol(tmp_path, monkeypatch):
    src = "class C:\n    def m(self, a):\n        return a\n"
    row = _gate(tmp_path, src, src.replace("return a", "return a  # 注释"),
                monkeypatch, syms=("C.m",), pick="C.m")
    assert row["status"] == "OK"


def test_deferred_states_all_pass(tmp_path, monkeypatch):
    """GUI 独有（TUI 尚无此符号）与「其实已同源」都判过，但后者提示撤销登记"""
    deferred = {(REL, "extra"): {"reason": "GUI 独有特性待移植", "tui": ""}}
    row = _gate(tmp_path, SAME + "\ndef extra(a):\n    return a\n", SAME,
                monkeypatch, deferred, syms=("fetch", "extra"), pick="extra")
    assert row["status"] == "DEFERRED_GUI_ONLY" and row["status"] in D.SYMBOL_PASS
    resynced = _gate(tmp_path, SAME, SAME, monkeypatch,
                     {(REL, "fetch"): {"reason": "已同步却忘了删登记", "tui": "0" * 16}})
    assert resynced["status"] == "DEFERRED_RESYNCED" and resynced["status"] in D.SYMBOL_PASS


# ---------- 真仓库：清单不烂、水印不假绿 ----------

def test_real_repo_symbol_gate_is_green():
    gui, tui = D._default_roots()
    if not os.path.isdir(os.path.join(tui, "app")):
        pytest.skip("TUI 仓库不在同级目录，符号门禁无法比对")
    rows = D.compare_symbols(gui, tui)
    assert rows, "SHARED_SYMBOLS 清单为空"
    bad = [f"{r['file']}::{r['symbol']}={r['status']}" for r in rows
           if r["status"] not in D.SYMBOL_PASS]
    assert not bad, f"符号级漂移未登记：{bad}"
    assert D.stale_deferrals() == []
    # 清单里每个 GUI 符号都必须真的解析得到（防改名后静默恒过）
    assert all(r["gui"] for r in rows), [r["symbol"] for r in rows if not r["gui"]]
