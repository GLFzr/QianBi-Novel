# -*- coding: utf-8 -*-
"""状态机：阶段常量、共写转移表、持久化与想法/指导生命周期"""
import pytest

from app.core import state as st


# ---- 常量与转移表的一致性 ----

def test_stage_order_unique_and_labeled():
    assert len(st.STAGE_ORDER) == len(set(st.STAGE_ORDER))
    for key in st.STAGE_ORDER:
        assert key in st.STAGE_LABELS


def test_cw_stage_chain_complete():
    # 沿 CW_NEXT 从立项走到正文终态，必须覆盖全部共写阶段且无环
    # （cw_prose → cw_prose 自环表示终态不再前进）
    seen, cur = [], st.STAGE_CW_PROJECT
    while st.CW_NEXT[cur] != cur:
        assert cur not in seen, f"CW_NEXT 有环：{cur}"
        seen.append(cur)
        cur = st.CW_NEXT[cur]
    seen.append(cur)  # 终态 cw_prose
    assert seen == st.CW_STAGE_ORDER
    assert cur == st.STAGE_CW_PROSE


def test_cw_prev_is_inverse_of_next():
    for k, v in st.CW_NEXT.items():
        if k == st.STAGE_CW_PROSE:
            continue  # 正文为终态，无前驱
        assert st.CW_PREV.get(v) == k


def test_rollback_cascade_keys_are_valid_stages():
    # 级联值是「需失效的产物路径模式」（精确相对路径或 .md 前缀），非阶段键
    valid = set(st.CW_STAGE_ORDER)
    assert st.CW_ROLLBACK_CASCADE.keys() <= valid
    for k, patterns in st.CW_ROLLBACK_CASCADE.items():
        for pat in patterns:
            assert isinstance(pat, str) and pat
            assert "/" in pat or pat.endswith("_"), f"非产物路径模式：{pat}"


def test_step_order_subset_of_defined_steps():
    defined = {st.STEP_ASSEMBLE, st.STEP_DRAFT, st.STEP_ENRICH, st.STEP_SCAN,
               st.STEP_DESLOP, st.STEP_REVIEW, st.STEP_FINALIZE}
    assert set(st.STEP_ORDER) <= defined
    assert len(st.STEP_ORDER) == len(set(st.STEP_ORDER))


# ---- 持久化 ----

def test_load_state_defaults_and_cw(tmp_path):
    proj = tmp_path / "book"
    proj.mkdir()
    s = st.load_state(str(proj))
    for k, v in st.DEFAULT_STATE.items():
        assert s[k] == v, f"缺省字段 {k} 被覆盖"
    assert isinstance(s["cw"], dict) and s["cw"]
    assert s["cw"] == st.cw_defaults()


def test_save_load_roundtrip(tmp_path):
    proj = tmp_path / "book"
    proj.mkdir()
    s = st.load_state(str(proj))
    s["stage"] = st.STAGE_PROSE
    s["current_chapter"] = 7
    st.save_state(str(proj), s)
    s2 = st.load_state(str(proj))
    assert s2["stage"] == st.STAGE_PROSE
    assert s2["current_chapter"] == 7


# ---- 指导与想法 ----

def test_guidance_roundtrip_consumed_once(tmp_path):
    proj = tmp_path / "book"
    proj.mkdir()
    s = st.load_state(str(proj))
    st.set_guidance(str(proj), s, 3, "本章多用对话")
    s2 = st.load_state(str(proj))  # 落盘后读回（JSON 键转字符串）
    assert st.take_guidance(s2, 3) == "本章多用对话"
    assert st.take_guidance(s2, 3) == ""  # 消费即删除


def test_idea_lifecycle_and_scope(tmp_path):
    proj = tmp_path / "book"
    proj.mkdir()
    s = st.load_state(str(proj))
    assert st.add_idea(str(proj), s, "加一只猫") is True
    assert st.add_idea(str(proj), s, "  ") is False  # 空想法拒绝
    assert st.add_idea(str(proj), s, "第5章伏笔", scope="5") is True

    taken = st.take_ideas(s, num=3)
    assert taken == ["加一只猫"]  # scope=5 的想法第 3 章不消费
    assert st.pending_idea_texts(s) == ["第5章伏笔"]
    taken5 = st.take_ideas(s, num=5)
    assert taken5 == ["第5章伏笔"]
    assert st.take_ideas(s, num=5) == []  # applied 后不重复消费


def test_norm_ideas_legacy_string_format():
    s = {"pending_ideas": ["老格式纯字符串"]}
    items = st.norm_ideas(s)
    assert len(items) == 1
    assert items[0]["text"] == "老格式纯字符串"
    assert items[0]["scope"] == "next"
    assert items[0]["status"] == "pending"


def test_review_findings_save_load(tmp_path):
    proj = tmp_path / "book"
    proj.mkdir()
    s = st.load_state(str(proj))
    st.save_review_findings(str(proj), s, 2, "REJECT",
                            [{"dim": "D_PLOT", "level": "fail"}])
    data = st.load_review_findings(s, 2)
    assert data.get("verdict") == "REJECT"
    assert data.get("items")[0]["dim"] == "D_PLOT"
    assert st.load_review_findings(s, 99) == {}  # 缺省返回空
