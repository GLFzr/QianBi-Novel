# -*- coding: utf-8 -*-
"""B6 review2 语义复核第二 pass——prompt 契约 + 三态解析钉测

覆盖：
1. prompt 契约：REVIEW2_PROMPT 独立于主审校六维（不评文笔/商业质量）、只回答
   事实/因果/时间线硬伤、三态裁决、只上报不写库、输入含 fact_ledger/状态卡摘要
   占位、零 ASCII 花括号外的裸花括号（模板走 .format()）。
2. parse_review2 三态解析：CLEAN/HARD_BUGS/UNDECIDABLE + 中文别名容错 +
   状态词换行容错 + items 提取（（无）行剔除）。
3. 边界：空输入/纯空白/畸形输出（无标记/乱标记）→ verdict=""，不抛异常。
stages 接线（_mc_review 主审校通过后追加第二 pass 调用）为 TODO，本文件钉接线方
必须遵守的形状（verdict 三态 + items 清单 + 无效票 verdict=""）。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.prompts.review import REVIEW2_PROMPT, parse_review2  # noqa: E402


# ---------------- 1. prompt 契约 ----------------

def test_review2_prompt_format_placeholders():
    """占位符齐备且整体可 .format（花括号逃逸纪律）"""
    out = REVIEW2_PROMPT.format(
        chapter_num=21, prose="正文样例",
        fact_ledger_summary="（无已入账事实）", state_card_summary="（无状态卡）")
    assert "正文样例" in out and "21" in out


def test_review2_prompt_scope_contract():
    """独立于六维：不评文笔/商业质量；只答事实/因果/时间线；三态；只上报不写库"""
    assert "不评文笔" in REVIEW2_PROMPT and "不评商业质量" in REVIEW2_PROMPT
    for kw in ("事实", "因果", "时间线"):
        assert kw in REVIEW2_PROMPT
    for state in ("CLEAN", "HARD_BUGS", "UNDECIDABLE"):
        assert state in REVIEW2_PROMPT
    assert "只上报、不写库" in REVIEW2_PROMPT
    assert "UNDECIDABLE" in REVIEW2_PROMPT and "拿不准就选这档" in REVIEW2_PROMPT
    # 输入含两份复核基准占位符
    assert "{fact_ledger_summary}" in REVIEW2_PROMPT
    assert "{state_card_summary}" in REVIEW2_PROMPT


# ---------------- 2. 三态解析 ----------------

def test_parse_review2_clean():
    raw = "===REVIEW2=== CLEAN\n===REVIEW2_ITEMS===\n（无）\n===END==="
    r = parse_review2(raw)
    assert r == {"verdict": "clean", "items": []}


def test_parse_review2_hard_bugs_with_items():
    raw = ("===REVIEW2=== HARD_BUGS\n===REVIEW2_ITEMS===\n"
           "- 硬伤：账本记「灵石余额 3 块」vs 本章「他掏出十块灵石」\n"
           "- 硬伤：记录第12章「柳三更已离铺」vs 本章她在柜台\n"
           "===END===")
    r = parse_review2(raw)
    assert r["verdict"] == "hard_bugs"
    assert len(r["items"]) == 2
    assert "十块灵石" in r["items"][0] and "柳三更" in r["items"][1]
    assert not any(i.startswith("-") for i in r["items"])   # 列表符号已剥


def test_parse_review2_undecidable_with_reason():
    raw = "===REVIEW2=== UNDECIDABLE\n===REVIEW2_ITEMS===\n- 两份复核基准均为空，无从对照\n===END==="
    r = parse_review2(raw)
    assert r["verdict"] == "undecidable"
    assert r["items"] == ["两份复核基准均为空，无从对照"]


def test_parse_review2_chinese_alias_and_linebreak_tolerance():
    """中文别名 + 状态词被换到标记下一行的容错"""
    assert parse_review2("===REVIEW2===\n无硬伤\n===REVIEW2_ITEMS===\n（无）\n===END===")["verdict"] == "clean"
    assert parse_review2("===REVIEW2===\n硬伤清单\n===END===")["verdict"] == "hard_bugs"
    assert parse_review2("===REVIEW2=== 无法判定\n===END===")["verdict"] == "undecidable"


def test_parse_review2_tolerates_missing_end_and_items():
    """缺 ===END=== 或缺 ITEMS 段不炸：verdict 照取，items 为空"""
    r = parse_review2("===REVIEW2=== CLEAN")
    assert r["verdict"] == "clean" and r["items"] == []


# ---------------- 3. 空输入 / 畸形输出 ----------------

def test_parse_review2_empty_and_blank():
    assert parse_review2("") == {"verdict": "", "items": []}
    assert parse_review2("   \n  ") == {"verdict": "", "items": []}
    assert parse_review2(None) == {"verdict": "", "items": []}


def test_parse_review2_malformed_outputs():
    """无标记/乱标记/主审校六维票误投 → verdict=""（无效票），不抛异常"""
    for bad in ("模型拒绝输出", "===REVIEW2=== 瞎写一档",
                "===A_GOLDEN_OPEN=== pass\n===VERDICT===\nPASS\n===END===",
                "===REVIEW2=== clean 后面跟一段没完没了的解释，但状态词仍是合法的"):
        r = parse_review2(bad)
        assert isinstance(r, dict) and set(r) == {"verdict", "items"}


def test_parse_review2_items_capped_at_20():
    raw = "===REVIEW2=== HARD_BUGS\n===REVIEW2_ITEMS===\n" + \
        "".join(f"- 硬伤{i}\n" for i in range(50))
    r = parse_review2(raw)
    assert len(r["items"]) == 20
