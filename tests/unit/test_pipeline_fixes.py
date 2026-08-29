# -*- coding: utf-8 -*-
"""真机全量测试暴露缺陷的回归守卫：
① first_missing_chapter 中间章重写续跑  ③ 审校 verdict/blocking 解析一致性兜底"""
import os

from app import project
from app.core.stages import parse_final_review_v2


# ---- 问题①：续跑起点 ----

def test_first_missing_no_gap(tmp_path):
    proj = str(tmp_path / "a")
    os.makedirs(proj)
    for n in (1, 2, 3):
        project.write_file(project.get_chapter_path(proj, n, f"t{n}"), "# t")
    assert project.first_missing_chapter(proj) == 4   # 无缺口 = max+1（追加语义不变）


def test_first_missing_with_gap(tmp_path):
    proj = str(tmp_path / "b")
    os.makedirs(proj)
    for n in (1, 2, 4, 5):
        project.write_file(project.get_chapter_path(proj, n, f"t{n}"), "# t")
    assert project.first_missing_chapter(proj) == 3   # 缺口优先（重写本章后续跑语义）


def test_first_missing_empty(tmp_path):
    proj = str(tmp_path / "c")
    os.makedirs(proj)
    assert project.first_missing_chapter(proj) == 1


def test_chapter_nums(tmp_path):
    proj = str(tmp_path / "d")
    os.makedirs(proj)
    for n in (1, 5):
        project.write_file(project.get_chapter_path(proj, n, f"t{n}"), "# t")
    assert project.chapter_nums(proj) == {1, 5}


# ---- 问题③：审校解析一致性兜底 ----

def test_parse_markdown_dims_with_verdict_reject():
    # 真机 ch1 实况形态：markdown 维度 + ===VERDICT=== REJECT → 旧解析 blocking=0
    t = ("## 整体判定\n**REJECT-HARD**（设定硬伤）\n## 六维评审\n"
         "### A_GOLDEN_OPEN：fail 开篇说明化\n### B_PAYOFF：marginal 铺垫不足\n"
         "===VERDICT===\nREJECT-HARD\n")
    r = parse_final_review_v2(t)
    assert r["verdict"] in ("REJECT", "REJECT-HARD")
    assert len(r["blocking"]) == 1 and len(r["advisory"]) == 1
    assert r["blocking"][0].startswith("开篇说明化") or "A_GOLDEN_OPEN" in str(r["items"])


def test_parse_verdict_keyword_fallback_synthesizes_blocking():
    t = "## 总评\n整体判定 REJECT：本章因果链断裂，需重写。\n"
    r = parse_final_review_v2(t)
    assert r["verdict"] == "REJECT"
    assert len(r["blocking"]) == 1 and "[未结构化评审]" in r["blocking"][0]


def test_parse_bracket_grades_protocol_output():
    # 括号式判级（prompt 规定格式，旧实现只认裸词导致漏判）
    t = ('===A_GOLDEN_OPEN=== [fail] 开篇拖沓 【原文引证："x"】\n'
         "===B_PAYOFF=== [pass] 达标\n===VERDICT===\nREJECT\n===END===\n")
    r = parse_final_review_v2(t)
    assert r["verdict"] == "REJECT"
    assert len(r["blocking"]) == 1 and len(r["items"]) == 2
    assert r["items"][0]["level"] == "fail" and r["items"][1]["level"] == "pass"


def test_parse_pass_untouched():
    t = "===A_GOLDEN_OPEN=== [pass] ok\n===VERDICT===\nPASS\n===END===\n"
    r = parse_final_review_v2(t)
    assert r["verdict"] == "PASS" and not r["blocking"]
