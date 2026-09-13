# -*- coding: utf-8 -*-
"""v1.2 两档制改造单测：run_mode 收缩为 auto|cw、门预置 gate_preset/gate_list、
旧四档配置迁移矩阵、G1/G3 接线、bridge 门槽位语义（无需 API Key）"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from app import config as cfg_mod
from app.core.orchestrator import Orchestrator
from app.core import state as st


# ---------------------------------------------------------------- 迁移矩阵

def _migrate(writing: dict) -> dict:
    cfg = {"writing": writing}
    return cfg_mod._migrate_run_mode(cfg)["writing"]


def test_migrate_step_mode():
    w = _migrate({"run_mode": "step", "gate_hard": ["G2", "G9"], "gate_soft": ["G6"]})
    assert w["run_mode"] == "auto"
    assert w["gate_preset"] == "step"
    assert set(w["gate_list"]) == {"G2", "G9", "G6"}
    assert "gate_hard" not in w and "gate_soft" not in w and "step_confirm" not in w


def test_migrate_border_mode_keeps_list():
    w = _migrate({"run_mode": "border", "gate_hard": ["G2", "G5L"], "gate_soft": ["G6"]})
    assert w["run_mode"] == "auto"
    assert w["gate_preset"] == "border"
    assert set(w["gate_list"]) == {"G2", "G5L", "G6"}


def test_migrate_auto_mode_gates_off_but_remembered():
    w = _migrate({"run_mode": "auto", "gate_hard": ["G2"], "gate_soft": []})
    assert w["run_mode"] == "auto"
    assert w["gate_preset"] == "off"
    assert w["gate_list"] == ["G2"]          # 勾选记忆保留，但关闭


def test_migrate_cw_mode_becomes_auto():
    w = _migrate({"run_mode": "cw"})
    assert w["run_mode"] == "auto"           # config 永不再存 'cw'（#16 根治）
    assert w["gate_preset"] == "off"


def test_migrate_step_confirm_to_g9_border():
    w = _migrate({"run_mode": "auto", "step_confirm": True})
    assert w["gate_preset"] == "border"
    assert w["gate_list"] == ["G9"]          # 每章定稿停，语义原样


def test_migrate_idempotent_and_skips_new_format():
    w = _migrate({"run_mode": "auto", "gate_preset": "border", "gate_list": ["G4"]})
    assert w["gate_list"] == ["G4"]          # 已是新格式：原样不动
    assert "gate_hard" not in w


# ---------------------------------------------------------------- 门预置语义

def _orch(tmp_path, writing: dict, name="两档制"):
    from app import project
    proj = project.create_project(str(tmp_path), name)
    return Orchestrator(proj, {"writing": writing})


def test_preset_off_all_gates_pass(tmp_path):
    o = _orch(tmp_path, {"gate_preset": "off"})
    for k in ("G1", "G2", "G3", "G4", "G5L", "G6", "G7", "G8", "G9"):
        assert o.gate_enabled(k) is False, k


def test_preset_step_all_wired_gates_stop(tmp_path):
    o = _orch(tmp_path, {"gate_preset": "step"})
    for k in cfg_mod.WIRED_GATES:
        assert o.gate_enabled(k) is True, k


def test_preset_border_list_driven(tmp_path):
    o = _orch(tmp_path, {"gate_preset": "border", "gate_list": ["G2", "G9"]})
    assert o.gate_enabled("G2") is True
    assert o.gate_enabled("G9") is True
    assert o.gate_enabled("G6") is False
    assert o.gate_enabled("G5L") is False


def test_run_mode_no_longer_affects_gates(tmp_path):
    """v1.2 核心：run_mode 不再参与门判定（删除档位维度零损失的前提）"""
    o = _orch(tmp_path, {"run_mode": "auto", "gate_preset": "border", "gate_list": ["G2"]}, "两档A")
    assert o.gate_enabled("G2") is True
    o2 = _orch(tmp_path, {"run_mode": "cw", "gate_preset": "border", "gate_list": []}, "两档B")
    assert o2.gate_enabled("G2") is False


# ---------------------------------------------------------------- G1/G3 接线

def test_wired_gates_complete():
    assert set(cfg_mod.WIRED_GATES) == {"G1", "G2", "G3", "G4", "G5L", "G6", "G7", "G8", "G9"}


def test_g1_gate_blocks_and_rolls_back_setting(tmp_path):
    from app import project
    proj = project.create_project(str(tmp_path), "G1门")
    setting = os.path.join(proj, "设定", "题材定位.md")
    project.write_file(setting, "# 题材定位\n\n旧设定")
    o = Orchestrator(proj, {"writing": {"gate_preset": "border", "gate_list": ["G1"]}})
    import threading
    threading.Timer(0.3, lambda: o.resolve_gate("return", "设定太平淡")).start()
    r = o.gate("G1", "核心设定已生成", 0)
    assert r is None                                  # 回退信号
    assert not os.path.exists(setting)                # 设定已归档清除
    assert o.consume_gate_idea() == "设定太平淡"       # 想法携带
    roll = os.path.join(proj, "pipeline_debug", "rollback")
    assert os.path.isdir(roll) and any(os.listdir(roll))


def test_g3_gate_rolls_back_batch_outlines(tmp_path):
    from app import project
    proj = project.create_project(str(tmp_path), "G3门")
    project.write_file(project.get_outline_path(proj, 3), "### 第 3 章")
    project.write_file(project.get_outline_path(proj, 4), "### 第 4 章")
    o = Orchestrator(proj, {"writing": {"gate_preset": "border", "gate_list": ["G3"]}})
    import threading
    threading.Timer(0.3, lambda: o.resolve_gate("return", "这两章节奏太快")).start()
    r = o.gate("G3", "第 3~4 章细纲已生成", 3)
    assert r is None
    assert not os.path.exists(project.get_outline_path(proj, 3))
    assert not os.path.exists(project.get_outline_path(proj, 4))


# ---------------------------------------------------------------- bridge 门槽位

def test_bridge_gate_slots_semantics(tmp_path):
    """bridge 门槽位与 orchestrator 同语义：写 self.cfg 即时生效（#15 同源修复口径）"""
    from app.ui import bridge as bridge_mod
    b = bridge_mod.Bridge.__new__(bridge_mod.Bridge)
    b.cfg = cfg_mod.load_config()
    b._running = False
    b.proj = ""
    # 绕过 Qt 依赖：仅测纯逻辑槽
    w = b.cfg.setdefault("writing", {})
    w["gate_preset"] = "step"
    assert b.gateEnabled("G6") is True
    w["gate_preset"] = "border"
    w["gate_list"] = ["G2"]
    assert b.gateEnabled("G2") is True and b.gateEnabled("G6") is False
    w["gate_preset"] = "off"
    assert b.gateEnabled("G2") is False
