# -*- coding: utf-8 -*-
"""字数阻塞闸门：细纲目标优先（幻觉回退）+ 审校前本地预检"""
import os

from app import project
from app.core import gates


def _cfg(**gates_over):
    cfg = {"writing": {"chapter_word_target": 3000},
           "gates": {"word_tolerance": 0.1}}
    cfg["gates"].update(gates_over)
    return cfg


def _mk_proj(tmp_path, outline_text=None, num=4):
    proj = str(tmp_path)
    if outline_text is not None:
        project.write_file(project.get_outline_path(proj, num), outline_text)
    return proj


# ---- chapter_word_target ----

def test_outline_target_preferred(tmp_path):
    proj = _mk_proj(tmp_path, "# 细纲 第4章\n\n字数目标：2500\n剧情：…")
    assert gates.chapter_word_target(proj, 4, 3000) == 2500


def test_outline_hallucinated_target_falls_back(tmp_path):
    # 偏差 >50%（3000 vs 300）→ 视为模型自造，回退默认
    proj = _mk_proj(tmp_path, "字数目标：300")
    assert gates.chapter_word_target(proj, 4, 3000) == 3000


def test_no_outline_falls_back(tmp_path):
    proj = _mk_proj(tmp_path)
    assert gates.chapter_word_target(proj, 4, 3000) == 3000


# ---- word_count_precheck ----

def test_precheck_rejects_short_chapter(tmp_path):
    proj = _mk_proj(tmp_path)
    items, blocking, verdict = gates.word_count_precheck(proj, 4, "字" * 2407, _cfg())
    assert verdict == "REJECT" and len(items) == 1
    assert items[0]["dim"] == "D_PLOT" and items[0]["level"] == "fail"
    assert "[字数]" in blocking[0] and "2407" in blocking[0]


def test_precheck_boundary_pass(tmp_path):
    proj = _mk_proj(tmp_path)
    # == 目标×90% 恰好放行
    items, blocking, verdict = gates.word_count_precheck(proj, 4, "字" * 2700, _cfg())
    assert (items, blocking, verdict) == ([], [], "")
    items2, _, verdict2 = gates.word_count_precheck(proj, 4, "字" * 2699, _cfg())
    assert verdict2 == "REJECT" and len(items2) == 1


def test_precheck_uses_outline_target(tmp_path):
    proj = _mk_proj(tmp_path, "字数目标：2000")
    # 目标 2000 → 下限 1800；1900 字放行
    _, _, verdict = gates.word_count_precheck(proj, 4, "字" * 1900, _cfg())
    assert verdict == ""
    _, _, verdict2 = gates.word_count_precheck(proj, 4, "字" * 1700, _cfg())
    assert verdict2 == "REJECT"


def test_precheck_can_be_disabled(tmp_path):
    proj = _mk_proj(tmp_path)
    cfg = _cfg(word_block_on_review=False)
    assert gates.word_count_precheck(proj, 4, "字" * 10, cfg) == ([], [], "")


def test_precheck_none_cfg_safe(tmp_path):
    proj = _mk_proj(tmp_path)
    _, _, verdict = gates.word_count_precheck(proj, 4, "字" * 4000, {})
    assert verdict == ""
