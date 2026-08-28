# -*- coding: utf-8 -*-
"""T3.2 state 类型加固：validate_state / load_state / save_state 键校验与旧存档回归"""
import copy
import json
import os

import pytest

from app.core import state as st

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE = os.path.dirname(REPO)

# 工作区内真实存档（GUI 写 / TUI 写 / 异形格式各覆盖；缺失则跳过）
REAL_ARCHIVES = [
    os.path.join(WORKSPACE, "qianbi-novel_real_run", "demo_book", "pipeline_state.json"),
    os.path.join(WORKSPACE, "cw_e2e", "proj", "青冥问道", "pipeline_state.json"),
    os.path.join(WORKSPACE, "e2e_10ch_proj", "时间铺子", "pipeline_state.json"),
    os.path.join(WORKSPACE, "qianbi_test_review_cfg_proj", "pipeline_state.json"),
]


# ---- validate_state 基础行为 ----

def test_default_state_passes_unchanged():
    s = copy.deepcopy(dict(st.DEFAULT_STATE))
    out = st.validate_state(s)
    assert out["stage"] == st.STAGE_INIT
    assert out["history"] == []


def test_none_values_repaired_to_defaults():
    s = {"stage": None, "history": None, "pending_guidance": None, "cw": None}
    out = st.validate_state(s)
    assert out["stage"] == st.STAGE_INIT
    assert out["history"] == []
    assert out["pending_guidance"] == {}
    assert out["cw"] == {}


def test_wrong_type_raises():
    s = {"history": "not-a-list"}
    with pytest.raises(st.StateValidationError, match="history"):
        st.validate_state(s)


def test_bool_is_not_int_for_chapter_counter():
    s = {"current_chapter": True}
    with pytest.raises(st.StateValidationError, match="current_chapter"):
        st.validate_state(s)


def test_unknown_keys_preserved():
    # 真实存档含 genre_preset / writing 等扩展键，校验不得拒绝或丢弃
    s = {"genre_preset": "xiuxian", "writing": {"a": 1}, "history": []}
    out = st.validate_state(s)
    assert out["genre_preset"] == "xiuxian"
    assert out["writing"] == {"a": 1}


def test_cw_bad_key_raises_with_path():
    s = {"cw": {"mode": 123}}
    with pytest.raises(st.StateValidationError, match=r"cw\['mode'\]"):
        st.validate_state(s)


def test_cw_unknown_keys_preserved():
    # 真实存档 cw 含 seq_v2 / worldbook_generated 等扩展键
    s = {"cw": {"mode": "cw", "seq_v2": 7, "worldbook_generated": True}}
    out = st.validate_state(s)
    assert out["cw"]["seq_v2"] == 7


# ---- save/load 集成 ----

def _proj(tmp_path):
    p = str(tmp_path / "proj")
    os.makedirs(p, exist_ok=True)
    return p


def test_save_rejects_invalid_state_without_touching_file(tmp_path):
    proj = _proj(tmp_path)
    st.save_state(proj, {"stage": "prose", "history": []})   # 先写一份合法状态
    path = st.state_path(proj)
    before = open(path, encoding="utf-8").read()
    bad = {"history": "corrupt"}
    with pytest.raises(st.StateValidationError):
        st.save_state(proj, bad)
    assert open(path, encoding="utf-8").read() == before     # 坏状态未落盘


def test_save_load_roundtrip_with_cw(tmp_path):
    proj = _proj(tmp_path)
    s = dict(st.DEFAULT_STATE)
    s["stage"] = st.STAGE_PROSE
    s["current_chapter"] = 3
    s["cw"] = st.cw_defaults()
    s["cw"]["mode"] = "cw"
    s["cw"]["stage"] = st.STAGE_CW_PROSE
    st.save_state(proj, s)
    loaded = st.load_state(proj)
    assert loaded["stage"] == st.STAGE_PROSE
    assert loaded["cw"]["mode"] == "cw"


# ---- 真实存档回归（T3.2 验收：旧存档全部可读）----

@pytest.mark.parametrize("path", REAL_ARCHIVES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_real_archives_load_and_validate(path):
    if not os.path.exists(path):
        pytest.skip(f"存档不存在：{path}")
    s = st.load_state(os.path.dirname(path))     # 损坏会抛 StateValidationError
    assert isinstance(s, dict)
    # 异形档（e2e 驱动写的 project_root 格式）无已知键也应原样通过
    if "stage" in s:
        assert s["stage"] in (st.STAGE_INIT, st.STAGE_SETTING, st.STAGE_OUTLINE,
                              st.STAGE_CH_OUTLINE, st.STAGE_PROSE, st.STAGE_DONE)


def test_deformed_archive_format_passes(tmp_path):
    # e2e_10ch_proj 实测格式：顶层无任何已知键，不得报错
    proj = _proj(tmp_path)
    raw = {"project_root": "x", "genre_preset": "urban", "writing": {}, "co_writing": {}}
    with open(st.state_path(proj), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    s = st.load_state(proj)
    assert s["project_root"] == "x"
    assert s["stage"] == st.STAGE_INIT           # 已知键缺失 → 默认值补齐
