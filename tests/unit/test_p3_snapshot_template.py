# -*- coding: utf-8 -*-
"""P3：章级快照（P2）→ 固化为可复用预设模板"""
import json
import os

import pytest

from app import presets as P


def _sandbox_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


SNAP = {
    "ts": "2026-09-02 10:00:00", "num": 39, "preset": "xianxia",
    "sampling": {"temperature": 0.8, "thinking": "enabled", "reasoning_effort": "max"},
    "stage_params": {"prose": {"temperature": 0.95, "slot": "写作"}},
    "calls": [
        {"phase": "outline", "slot": "默认", "model": "m", "prompt_hash": "a" * 16,
         "sampling": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096,
                      "thinking": "enabled"}, "degraded": False},
        {"phase": "prose", "slot": "写作", "model": "m", "prompt_hash": "b" * 16,
         # 网关拒收过 frequency_penalty 后 last_sampling 里就没有它了
         "sampling": {"temperature": 0.95, "top_p": 0.88, "max_tokens": 8192},
         "degraded": True},
        {"phase": "prose", "slot": "写作", "model": "m", "prompt_hash": "c" * 16,
         "sampling": {"temperature": 0.5}, "degraded": False},
        {"phase": "", "slot": "", "model": "m", "prompt_hash": "d" * 16,
         "sampling": {"temperature": 0.1}, "degraded": False},
    ],
    "worldbook": {},
}


def test_template_carries_real_sampling_not_declared():
    """相位档取真实下发的采样：首次调用为准，被网关拒收的参数不会写回来"""
    t = P.preset_from_snapshot(SNAP, "执灯人")
    assert t["stage_params"]["prose"] == {"temperature": 0.95, "top_p": 0.88,
                                          "max_tokens": 8192, "slot": "写作"}
    assert "frequency_penalty" not in t["stage_params"]["prose"]
    assert t["stage_params"]["outline"]["max_tokens"] == 4096


def test_slot_goes_to_phase_layer_and_thinking_stays_in_baseline():
    t = P.preset_from_snapshot(SNAP, "执灯人")
    assert t["sampling"] == SNAP["sampling"]                 # 基线原样带走（含 thinking/effort）
    assert all("thinking" not in v for v in t["stage_params"].values())
    assert t["stage_params"]["prose"]["slot"] == "写作"       # 槽只有分相位才有意义


def test_blank_phase_and_empty_snapshot_are_harmless():
    t = P.preset_from_snapshot(SNAP, "执灯人")
    assert "" not in t["stage_params"]
    empty = P.preset_from_snapshot({}, "无名书")
    assert empty["stage_params"] == {} and empty["sampling"] == {}
    assert empty["name"] and empty["id"].startswith("snap_")


def test_template_id_is_stable_per_book_and_chapter():
    a = P.snapshot_template_id("执灯人", 39)
    assert a == P.snapshot_template_id("执灯人", 39) != P.snapshot_template_id("执灯人", 40)
    assert a.startswith("snap_") and a == P.preset_from_snapshot(SNAP, "执灯人")["id"]
    # id 只含 ASCII：中文书名走哈希，用户目录里的文件名保持可移植
    assert all(c.isascii() for c in a)


def test_saved_template_reapplies_the_same_layers(tmp_path, monkeypatch):
    """固化 → 落盘 → 加载链读回来必须等于当时生效的两层参数（飞轮回路的硬验收）"""
    _sandbox_home(monkeypatch, tmp_path)
    t = P.preset_from_snapshot(SNAP, "执灯人")
    path = P.save_preset(t)
    assert os.path.isfile(path) and os.path.dirname(path) == P.user_dir()
    assert P.sampling(t["id"]) == {"temperature": 0.8, "thinking": "enabled",
                                   "reasoning_effort": "max"}
    back = P.stage_params(t["id"])
    assert back["prose"]["temperature"] == 0.95 and back["prose"]["slot"] == "写作"
    assert back["outline"]["top_p"] == 0.9
    assert t["id"] in [i["id"] for i in P.list_presets()]     # 预设库/新建下拉都看得见
    # 重新固化只覆盖同一个文件
    P.save_preset(P.preset_from_snapshot(SNAP, "执灯人"))
    assert len([f for f in os.listdir(P.user_dir()) if f.startswith("snap_")]) == 1


def test_template_freezes_source_preset_text_too():
    """一项目一预设：模板不带走题材文本块，用户一选它就把文风丢了"""
    src = {"id": "xianxia", "name": "修仙", "version": 2,
           "style_hint": "冷硬短句", "stage_hints": {"prose": "多写动作"},
           "author_note": "别让主角一个人想太多",
           "sampling": {"temperature": 0.3},
           "stage_params": {"prose": {"temperature": 0.99}},
           "_src": "/abs/path/xianxia.json", "_builtin": True}
    t = P.preset_from_snapshot(SNAP, "执灯人", src)
    assert t["style_hint"] == "冷硬短句" and t["stage_hints"] == {"prose": "多写动作"}
    assert t["author_note"] == "别让主角一个人想太多"
    assert t["sampling"] == SNAP["sampling"]                    # 参数以本章实际下发为准
    assert t["stage_params"]["prose"]["temperature"] == 0.95
    assert not any(k.startswith("_") for k in t)                 # 来源路径/内置标记不外泄
    assert t["id"] != "xianxia" and t["name"].startswith("《执灯人》")
    assert "修仙" in t["description"]


def test_save_preset_refuses_idless_payload(tmp_path, monkeypatch):
    _sandbox_home(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        P.save_preset({"name": "没有 id"})


def test_dirty_template_values_are_dropped_by_loader(tmp_path, monkeypatch):
    """构造端不做第二套钳位：脏值由既有校验剥掉（丢而非钳）"""
    _sandbox_home(monkeypatch, tmp_path)
    snap = json.loads(json.dumps(SNAP))
    snap["calls"][1]["sampling"]["temperature"] = 9.9          # 越界
    pid = P.save_preset(P.preset_from_snapshot(snap, "脏书")).split(os.sep)[-1][:-5]
    assert "temperature" not in P.stage_params(pid)["prose"]
    assert P.stage_params(pid)["prose"]["top_p"] == 0.88
