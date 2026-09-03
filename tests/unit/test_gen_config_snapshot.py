# -*- coding: utf-8 -*-
"""P2 章级配置快照：世界书激活清单 + 参数档 + 调用指纹落 正文/.annotations/第N.json"""
import hashlib
import json
import os

from app import presets as genre_presets
from app import project, wb
from app.core import stages
from app.core import state as st


class _Ctx:
    """最小流水线上下文替身（只带快照需要的 proj/log）"""

    def __init__(self, proj=""):
        self.proj = proj
        self.logs = []

    def log(self, level, msg):
        self.logs.append((level, msg))


class _Client:
    model = "test-model"
    last_sampling = {"temperature": 0.7, "max_tokens": 4096}
    last_degraded = False


def _seed_preset(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    d = os.path.join(str(tmp_path), ".qianbi_novel", "presets")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "snap.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "snap", "name": "快照测试", "version": 2,
                   "sampling": {"temperature": 0.8, "thinking": "disabled"},
                   "stage_params": {"prose": {"temperature": 0.95, "slot": "写作"},
                                    "ghost_phase": {"temperature": 1.5}}}, f,
                  ensure_ascii=False)


# ---------- project 侧读写口 ----------

def test_snapshot_round_trip_keeps_lock_and_annotations(tmp_path):
    proj = project.create_project(str(tmp_path), "快照书")
    project.set_chapter_locked(proj, 3, True)
    project._write_annotation(proj, 3, dict(project._read_annotation(proj, 3),
                                            annotations=[{"kind": "comment", "quote": "甲"}]))
    project.set_chapter_gen_config(proj, 3, {"num": 3, "calls": [{"phase": "prose"}]})

    snap = project.get_chapter_gen_config(proj, 3)
    assert snap["calls"][0]["phase"] == "prose"
    data = project._read_annotation(proj, 3)
    assert data["locked"] is True and len(data["annotations"]) == 1   # 快照不踩同仓其他字段


def test_snapshot_is_replaced_not_merged(tmp_path):
    proj = project.create_project(str(tmp_path), "快照书")
    project.set_chapter_gen_config(proj, 1, {"preset": "a", "calls": [{"phase": "prose"}]})
    project.set_chapter_gen_config(proj, 1, {"preset": "b"})
    assert project.get_chapter_gen_config(proj, 1) == {"preset": "b"}


def test_missing_snapshot_and_zero_num_are_harmless(tmp_path):
    proj = project.create_project(str(tmp_path), "老书")
    assert project.get_chapter_gen_config(proj, 9) == {}
    project.set_chapter_gen_config(proj, 0, {"preset": "a"})   # 无章号：不写不炸
    assert not os.path.exists(project._annotation_path(proj, 0))


# ---------- stages 侧轨迹记录 ----------

def test_record_call_stores_real_sampling_and_prompt_hash():
    ctx = _Ctx()
    stages.begin_gen_trace(ctx)
    stages._record_call(ctx, "prose", "写作", _Client(), "提示词")
    (rec,) = ctx.gen_trace
    assert rec["phase"] == "prose" and rec["slot"] == "写作" and rec["model"] == "test-model"
    assert rec["sampling"] == {"temperature": 0.7, "max_tokens": 4096}
    assert rec["prompt_hash"] == hashlib.sha256("提示词".encode("utf-8")).hexdigest()[:16]
    assert rec["degraded"] is False


def test_recorders_skip_uncooperative_ctx():
    """共写/探针替身没配轨迹容器：静默跳过，绝不把正文流程带崩"""
    ctx = _Ctx()
    stages._record_call(ctx, "prose", "写作", _Client(), "提示词")
    stages._record_worldbook(ctx, "prose", {"budget": 1, "activated": [], "dropped": []})
    assert not hasattr(ctx, "gen_trace")


def test_record_worldbook_keeps_trigger_reason_and_drops_skeleton():
    ctx = _Ctx()
    stages.begin_gen_trace(ctx)
    meta = {"budget": 2000, "dropped": [{"name": "拍卖行"}],
            "activated": [{"id": "a", "name": "陈更", "kind": "entity", "why": "本章命中·陈更", "hash": "h1"},
                          {"id": "s", "name": "正文骨架", "kind": "prose", "why": wb.WHY_SKELETON, "hash": "h2"}]}
    stages._record_worldbook(ctx, "prose", meta)
    got = ctx.gen_worldbooks["prose"]
    assert got["budget"] == 2000 and got["dropped"] == ["拍卖行"]
    assert [a["name"] for a in got["activated"]] == ["陈更"]        # 骨架不是设定，不进快照
    assert got["activated"][0]["why"] == "本章命中·陈更" and got["activated"][0]["hash"] == "h1"


def test_write_gen_config_freezes_layers_and_preset(tmp_path, monkeypatch):
    _seed_preset(tmp_path, monkeypatch)
    proj = project.create_project(str(tmp_path), "快照书")
    st.save_state(proj, {"genre_preset": "snap"})
    ctx = _Ctx(proj)
    stages.begin_gen_trace(ctx)
    stages._record_call(ctx, "prose", "写作", _Client(), "提示词")
    snap = stages.write_gen_config(ctx, 7)

    assert snap["preset"] == "snap" and snap["num"] == 7
    assert snap["sampling"] == {"temperature": 0.8, "thinking": "disabled"}
    assert snap["stage_params"] == {"prose": {"temperature": 0.95, "slot": "写作"}}   # 脏相位已被丢
    assert len(snap["calls"]) == 1
    assert project.get_chapter_gen_config(proj, 7) == snap        # 落盘即读回


def test_write_gen_config_with_corrupt_preset_still_records(tmp_path, monkeypatch):
    """预设文件坏了 → 参数档退空，但调用轨迹照记：快照是可追溯性，不是流水线依赖"""
    _seed_preset(tmp_path, monkeypatch)
    d = os.path.join(str(tmp_path), ".qianbi_novel", "presets", "broken.json")
    with open(d, "w", encoding="utf-8") as f:
        f.write("{不是 json")
    proj = project.create_project(str(tmp_path), "快照书")
    st.save_state(proj, {"genre_preset": "broken"})
    ctx = _Ctx(proj)
    stages.begin_gen_trace(ctx)
    stages._record_call(ctx, "prose", "写作", _Client(), "提示词")
    snap = stages.write_gen_config(ctx, 2)
    assert snap["sampling"] == {} and snap["stage_params"] == {}
    assert snap["calls"][0]["phase"] == "prose"
    assert project.get_chapter_gen_config(proj, 2)["calls"] == snap["calls"]


def test_snapshot_write_failure_only_logs(tmp_path, monkeypatch):
    proj = project.create_project(str(tmp_path), "快照书")
    ctx = _Ctx(proj)
    stages.begin_gen_trace(ctx)

    def boom(*_a, **_kw):
        raise OSError("磁盘只读")

    monkeypatch.setattr(project, "set_chapter_gen_config", boom)
    snap = stages.write_gen_config(ctx, 1)
    assert snap["num"] == 1
    assert ctx.logs and ctx.logs[0][0] == "warn" and "第 1 章" in ctx.logs[0][1]


def test_gen_presets_helper_labels_exist():
    """快照排版依赖的标签表：键缺一个，UI 就会显示英文原始参数名"""
    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty",
                "max_tokens", "thinking", "reasoning_effort"):
        assert key in genre_presets.SAMPLING_LABELS, key
