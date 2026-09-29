# -*- coding: utf-8 -*-
"""C26 阶段级模型路由单测：ModelPolicyController 四阶段组读写 + 两张阶段级策略卡

口径（落地计划附录A 卡 C26 / w4_model_orch §3 方案 A）：
- 预设 JSON {prose:{slot:"x"}} 经 controller 写出与手写等价，stage_slot() 解析一致；
- 两张策略卡（quality_mix / budget_run）切换后 stage_params 变化；
- A14 回归（零静默换型，对照 tests/unit/test_v18c_slot_pro_lock.py 的槽位层语义）：
  阶段层只写显式覆盖、绝不改三槽绑定；「跟随默认」= 摘除覆盖、槽位层原样生效；
  悬空连接 id 会被 slot_connection 兜底链静默换到第一条——controller 拒绝落盘。
"""
import json
import os

import pytest

from app import model_strategy as ms
from app import presets as P
from app import project
from app.core import state as st
from app.slots import slot_connection
from app.ui import bridge as bmod
from app.ui.bridge import ModelPolicyController

FLASH, PRO = "ds-official-flash", "ds-official-pro"
DRAFT_PHASES = ("prose", "enrich", "trim", "deslop")


# ---------- 夹具 ----------

def _write_preset(stage_params=None):
    """沙箱用户仓写一张 v2 预设（不碰内置 JSON 与真实 ~/.qianbi_novel）"""
    d = P.user_dir()
    data = {"id": "wired", "name": "路由预设", "version": 2}
    if stage_params is not None:
        data["stage_params"] = stage_params
    with open(os.path.join(d, "wired.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def _preset_file():
    return os.path.join(P.user_dir(), "wired.json")


def _read_preset():
    with open(_preset_file(), encoding="utf-8") as f:
        return json.load(f)


def _cfg():
    return {"connections": [
        {"id": FLASH, "name": "Flash 行", "provider": "deepseek",
         "base_url": "https://api.deepseek.com", "api_key": "sk",
         "model": "deepseek-v4-flash"},
        {"id": PRO, "name": "Pro 行", "provider": "deepseek",
         "base_url": "https://api.deepseek.com", "api_key": "sk",
         "model": "deepseek-v4-pro"},
    ], "slots": {"writing": FLASH, "helper": FLASH, "review": FLASH}}


class _FakeBridge:
    """controller 只吃这几个属性——不起 Qt 应用、不建真 Bridge"""

    def __init__(self, cfg, proj=None):
        self.cfg = cfg
        self.proj = proj
        self._running = False
        self.toasts = []
        self.refreshed = 0
        self.slot_signals = 0

        class _Sig:
            def __init__(self, fn):
                self._fn = fn

            def emit(self, *a):
                self._fn(*a)

        self.toast = _Sig(lambda kind, msg: self.toasts.append((kind, msg)))
        self.slotsTextChanged = _Sig(
            lambda: setattr(self, "slot_signals", self.slot_signals + 1))

        class _Conn:
            def __init__(self, fn):
                self._fn = fn

            def refresh(self):
                self._fn()

        self.connectionModel = _Conn(
            lambda: setattr(self, "refreshed", self.refreshed + 1))

    def applyModelPreset(self, card_id):
        """applyStrategy 的三槽层走 Bridge 既有入口（§11.1 认可范式）——
        桩不是 Bridge 子类，显式未绑定直调走真实逻辑（test_auto_backup 同款）。"""
        bmod.Bridge.applyModelPreset(self, card_id)


def _make(tmp_path, monkeypatch, stage_params=None, preset_id="wired", cfg=None):
    """沙箱：预设用户仓 + 最小项目挂上它 → (controller, FakeBridge)"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_preset(stage_params)
    proj = project.create_project(os.path.join(str(tmp_path), "books"), "路由书")
    st.save_state(proj, {"genre_preset": preset_id})
    fb = _FakeBridge(cfg or _cfg(), proj)
    return ModelPolicyController(fb), fb


# ---------- 组划分合法性 ----------

def test_groups_partition_is_legal():
    """四组相位必须全部合法且不重不漏——未知相位会被读层「脏值即丢」静默吞掉，
    进下拉就是写了不生效的假旋钮。"""
    phases = [ph for g in ModelPolicyController.GROUPS for ph in g["phases"]]
    legal = {k for k, _lab in P.STAGE_PARAM_PHASES}
    assert len(phases) == len(set(phases)), "组间相位重复"
    assert set(phases) <= legal, "GROUPS 里混进非法相位 %s" % (set(phases) - legal)


# ---------- 验收①：controller 写出与手写等价 + stage_slot 解析一致 ----------

def test_group_write_equivalent_to_handwritten(tmp_path, monkeypatch):
    ctl, _fb = _make(tmp_path, monkeypatch)
    ctl.setGroupSlot("draft", PRO)
    assert _read_preset()["stage_params"] == {ph: {"slot": PRO} for ph in DRAFT_PHASES}, \
        "controller 写出的 JSON 应与手写逐键等价（只有 slot 键、无多余包装）"
    assert P.stage_params("wired") == {ph: {"slot": PRO} for ph in DRAFT_PHASES}
    assert P.stage_slot("wired", "prose") == PRO, "stages._stream 消费的解析口径必须一致"
    assert P.stage_slot("wired", "outline") == "", "组外相位不许被波及"


def test_group_write_preserves_other_params(tmp_path, monkeypatch):
    """只动 slot 键：手写的 temperature/top_p 原样保留；组外相位零波及。"""
    ctl, _fb = _make(tmp_path, monkeypatch,
                     stage_params={"prose": {"temperature": 0.9, "top_p": 0.95}})
    ctl.setGroupSlot("draft", PRO)
    sp = P.stage_params("wired")
    assert sp["prose"] == {"temperature": 0.9, "top_p": 0.95, "slot": PRO}
    assert sp["enrich"] == {"slot": PRO}, "组语义=整组指向：其余组内相位只补 slot 键"
    assert "outline" not in sp and "core_setting" not in sp, "组外相位不许被波及"


def test_group_clear_restores_follow(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.setGroupSlot("draft", PRO)
    assert P.stage_slot("wired", "prose") == PRO
    ctl.setGroupSlot("draft", "")
    assert P.stage_slot("wired", "prose") == "", "摘除覆盖后回落槽位层（stage_slot 恒空串）"
    assert P.stage_params("wired") == {}, "清空后的空档位键不落盘"
    opts = {g["id"]: g for g in ctl.groupOptions}
    assert opts["draft"]["current"] == "", "组下拉视图应回到「跟随默认」"


def test_group_read_mixed_overrides_shows_follow(tmp_path, monkeypatch):
    """手写只配了组内单个相位：读数不一致 → 展示跟随默认，不替用户合并。"""
    ctl, _fb = _make(tmp_path, monkeypatch,
                     stage_params={"prose": {"slot": "x"}})
    opts = {g["id"]: g for g in ctl.groupOptions}
    assert P.stage_slot("wired", "prose") == "x"   # 单相位解析照常
    assert opts["draft"]["current"] == "", "组内不一致时不该假装组级覆盖存在"
    assert opts["planning"]["current"] == ""


def test_group_write_unknown_connection_rejected(tmp_path, monkeypatch):
    """A14：悬空连接 id 会在 slot_connection 兜底链里静默换到第一条——拒绝落盘。"""
    ctl, fb = _make(tmp_path, monkeypatch)
    before = _read_preset()
    ctl.setGroupSlot("review", "no-such-conn")
    assert _read_preset() == before, "文件不许有任何变化"
    assert any(k == "warn" for k, _m in fb.toasts)


def test_group_write_unknown_group_rejected(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.setGroupSlot("不存在组", PRO)
    assert not os.path.exists(os.path.join(P.user_dir(), "nonexistent"))  # no-op 不炸
    assert any(k == "warn" for k, _m in fb.toasts)


def test_group_write_without_preset_refused(tmp_path, monkeypatch):
    """未启用题材预设：阶段路由无处落，明说而不是写进不存在的文件。"""
    ctl, fb = _make(tmp_path, monkeypatch, preset_id="")
    before_toasts = len(fb.toasts)
    ctl.setGroupSlot("draft", PRO)
    assert len(fb.toasts) == before_toasts + 1
    kind, msg = fb.toasts[-1]
    assert kind == "warn" and "题材预设" in msg


# ---------- 验收②：两策略卡切换后 stage_params 变化 ----------

def test_strategy_card_quality_mix(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.applyStrategy("quality_mix")
    sp = P.stage_params("wired")
    for ph in DRAFT_PHASES:
        assert sp[ph]["slot"] == FLASH, "草稿组四相位应钉 Flash"
    for ph in ("core_setting", "volume_outline", "worldbook", "outline"):
        assert sp[ph]["slot"] == FLASH, "大纲组四相位应钉 Flash"
    assert P.stage_slot("wired", "prose") == FLASH
    assert fb.cfg["slots"]["review"] == PRO, "槽位层：审校槽升 Pro（显式卡动作，非静默）"
    assert slot_connection(fb.cfg, "review")["id"] == PRO
    ids = {c["id"] for c in fb.cfg["connections"]}
    assert {FLASH, PRO} <= ids, "卡里钉的连接行必须真实存在（apply_preset 确保）"
    assert any("阶段档已存进预设" in m for _k, m in fb.toasts)


def test_strategy_card_budget_run(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.applyStrategy("budget_run")
    sp = P.stage_params("wired")
    assert sp["prose"] == {"thinking": "disabled"}, "创作相位关思考（机械相位内置表本就关）"
    assert sp["core_setting"] == {"thinking": "disabled"}
    assert all(v == FLASH for v in fb.cfg["slots"].values()), "全快档 = 三槽全 Flash"
    # 再切 quality_mix：stage_params 被改写（卡间切换语义）
    ctl.applyStrategy("quality_mix")
    assert P.stage_params("wired")["prose"]["slot"] == FLASH
    assert P.stage_params("wired")["prose"]["thinking"] == "disabled", \
        "既有参数键保留，slot 键并入"


def test_strategy_card_slot_options_untouched_by_preset_options(tmp_path, monkeypatch):
    """槽位层两卡（official_all/strict_review）不混进阶段卡列表，反之亦然——
    两套 UI 出口各说各话，不出现「点了没全生效」的半套语义。"""
    slot_ids = {o["id"] for o in ms.preset_options()}
    stage_ids = {o["id"] for o in ms.strategy_card_options()}
    assert slot_ids == {"official_all", "strict_review"}
    assert stage_ids == {"quality_mix", "budget_run"}
    assert not slot_ids & stage_ids


def test_strategy_card_without_preset_slots_only(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch, preset_id="")
    before = _read_preset()
    ctl.applyStrategy("quality_mix")
    assert fb.cfg["slots"]["review"] == PRO, "三槽层照常生效（不依赖题材预设）"
    assert _read_preset() == before, "阶段档无处落，预设文件零触碰"
    assert any("题材预设" in m and "未落" in m for _k, m in fb.toasts)


def test_strategy_card_running_refused(tmp_path, monkeypatch):
    """与 applyModelPreset 同款守卫：运行中换 self.cfg 会把 orchestrator 劈成两半。"""
    ctl, fb = _make(tmp_path, monkeypatch)
    fb._running = True
    before_slots = dict(fb.cfg["slots"])
    ctl.applyStrategy("quality_mix")
    assert fb.cfg["slots"] == before_slots
    assert any(k == "warn" for k, _m in fb.toasts)
    assert P.stage_params("wired") == {}


def test_strategy_card_unknown_id(tmp_path, monkeypatch):
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.applyStrategy("不存在")
    assert any(k == "warn" for k, _m in fb.toasts)


# ---------- A14 回归：零静默换型（对照 test_v18c_slot_pro_lock）----------

def test_a14_stage_layer_never_touches_slot_bindings(tmp_path, monkeypatch):
    """阶段层写满预设后：三槽绑定 cfg.slots 逐键不变；显式覆盖原样生效；
    未指定组回落槽位层——选了 Flash 就是 Flash，没有任何模型过滤/替换。"""
    ctl, fb = _make(tmp_path, monkeypatch)
    slots_before = dict(fb.cfg["slots"])
    ctl.setGroupSlot("draft", PRO)
    ctl.setGroupSlot("review", PRO)
    assert fb.cfg["slots"] == slots_before, "阶段层写入不许碰三槽绑定"
    assert slot_connection(fb.cfg, "writing")["id"] == FLASH, "槽位层原样生效（无静默升级）"
    assert slot_connection(fb.cfg, "review")["id"] == FLASH
    assert P.stage_slot("wired", "prose") == PRO, "显式阶段覆盖原样生效（选了 Pro 就是 Pro）"
    assert P.stage_slot("wired", "tracking") == "", "未指定的辅助组仍跟随槽位层"


def test_a14_strategy_card_pro_only_via_explicit_rows(tmp_path, monkeypatch):
    """quality_mix 的 Pro 全部走显式连接行绑定/钉选，不出厂夹带 Pro：
    落盘的 stage_params 里没有第四种连接 id。"""
    ctl, fb = _make(tmp_path, monkeypatch)
    ctl.applyStrategy("quality_mix")
    written_slots = {v.get("slot") for v in P.stage_params("wired").values() if v.get("slot")}
    assert written_slots == {FLASH}
