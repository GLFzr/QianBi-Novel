# -*- coding: utf-8 -*-
"""撞墙修复组（QW-A1/A2/A3/A5）回归：指路与档位一致 + 配置错误零成本前置

覆盖：
- A1：新建书 toast 按档位指路——共写档不再说「点开始」（那是必被拦的门）；
- A2：共写档「开始」按钮位置换「去共写 · {阶段}」CTA（自动档空串维持原样）；
- A3：startPipeline missing[] 同时报「未填 Key」与「未选模型」；
- A5：_slot_readiness() 起跑前拦截——构造 worker/客户端之前就拦下（零网络请求）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import state as st  # noqa: E402
from app.ui import bridge as bmod  # noqa: E402


def _capture_toast(b):
    calls = []
    b.toast.connect(lambda kind, text: calls.append((kind, text)))
    return calls


def _ready_conn(cid, name, key="sk-test", model="test-model"):
    return {"id": cid, "name": name, "base_url": "https://api.example.com/v1",
            "api_key": key, "model": model}


class _Recorder:
    """构造即记名——被拦路径上出现任何实例化即失败（零网络/零客户端证据）"""

    def __init__(self, *a, **kw):
        self.init_args = (a, kw)
        self.started = False
        raise AssertionError("被拦路径不应构造 LLM worker/客户端（零网络请求）")


def _mk_auto_proj(tmp_path):
    proj = str(tmp_path / "auto_book")
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    st.save_state(proj, {"current_chapter": 0, "total_chapters": 5,
                         "cw": {"mode": "auto", "stage": "cw_project"}})
    return proj


# ---------- A1：新建书 toast 按档位指路 ----------

def test_new_project_toast_cw_mode_points_to_topic(tmp_path):
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"writing": {"run_mode": "cw"}, "connections": [], "slots": {}}
    calls = _capture_toast(b)
    ok = b.newProject(str(tmp_path / "shelf"), "共写档新书", "都市", "番茄", 1, "灵感", "")
    assert ok
    created = [t for k, t in calls if k == "ok" and "已创建" in t]
    assert len(created) == 1
    text = created[0]
    assert "开始" not in text, f"共写档新书 toast 仍指「开始」（必被拦的门）：{text}"
    assert "选题" in text and "共写" in text


def test_new_project_toast_auto_mode_keeps_start(tmp_path):
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"writing": {"run_mode": "auto"}, "connections": [], "slots": {}}
    calls = _capture_toast(b)
    ok = b.newProject(str(tmp_path / "shelf2"), "自动档新书", "都市", "番茄", 1, "灵感", "")
    assert ok
    created = [t for k, t in calls if k == "ok" and "已创建" in t]
    assert len(created) == 1
    assert "点击「开始」启动流水线" in created[0], "自动档指路文案不得变化（老用户回归面=0）"


# ---------- A2：共写档 CTA ----------

def test_start_cta_label_by_mode(tmp_path):
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"writing": {"run_mode": "cw"}, "connections": [], "slots": {}}
    b.newProject(str(tmp_path / "shelf3"), "CTA书", "都市", "番茄", 1, "灵感", "")
    assert b.startCtaLabel.startswith("去共写 · "), f"共写档应给 CTA：{b.startCtaLabel}"
    # 阶段推进后 CTA 跟随阶段名
    state = st.load_state(b.proj)
    st.ensure_cw(state)["stage"] = st.STAGE_CW_UNIT
    st.save_state(b.proj, state)
    assert "单元细纲" in b.startCtaLabel
    # 自动档：空串（按钮维持「开始」）
    b2 = Bridge()
    b2.proj = _mk_auto_proj(tmp_path / "auto_cta")
    b2.cfg = {"writing": {"run_mode": "cw"}, "connections": [], "slots": {}}
    assert b2.startCtaLabel == "", "自动档不得改按钮文案"


def test_goto_cta_selects_stage_and_hints_once(tmp_path):
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"writing": {"run_mode": "cw"}, "connections": [], "slots": {}}
    b.newProject(str(tmp_path / "shelf4"), "定位书", "都市", "番茄", 1, "灵感", "")
    calls = _capture_toast(b)
    b.gotoCwStage()
    b.gotoCwStage()
    hints = [t for k, t in calls if "六步" in t]
    assert len(hints) == 1, "六步总览只在首次点按给一次"
    assert b._cw_view == b._get_cw_stage_key()


# ---------- A3：startPipeline missing[] 同时报 Key 与模型 ----------

def test_start_pipeline_missing_reports_key_and_model(tmp_path, monkeypatch):
    from app.ui.bridge import Bridge
    b = Bridge()
    b.proj = _mk_auto_proj(tmp_path / "auto_book2")
    b.cfg = {"writing": {"run_mode": "auto"},
             "connections": [_ready_conn("a", "无Key连接", key="", model="m1"),
                             _ready_conn("b", "无模型连接", key="sk-x", model="")],
             "slots": {"writing": "a", "helper": "b", "review": "b"}}
    calls = _capture_toast(b)
    monkeypatch.setattr(bmod, "Orchestrator",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("缺配置时不得创建 Orchestrator")))
    b.startPipeline()
    assert len(calls) == 1 and calls[0][0] == "warn"
    text = calls[0][1]
    assert "未填 API Key" in text and "无Key连接" in text
    assert "未选模型" in text and "无模型连接" in text


# ---------- A5：_slot_readiness + 共写起跑前拦截（零网络） ----------

def test_slot_readiness_copy_by_case():
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"connections": [], "slots": {}}
    assert "还没配置连接" in b._slot_readiness("writing")
    b.cfg = {"connections": [_ready_conn("a", "无Key连接", key="", model="m")], "slots": {}}
    assert "还没填 API Key" in b._slot_readiness("writing")
    b.cfg = {"connections": [_ready_conn("a", "无模型连接", model="")], "slots": {}}
    reason = b._slot_readiness("helper")
    assert "还没选模型" in reason and "设置 · 连接与模型" in reason
    b.cfg = {"connections": [_ready_conn("a", "就绪连接")], "slots": {}}
    assert b._slot_readiness("review") == ""


def test_spawn_cw_dialogue_blocked_before_client(tmp_path, monkeypatch):
    """未选模型：拦在构造 worker/客户端之前——零网络请求（构造即失败的记录器作证）"""
    from app.ui.bridge import Bridge
    b = Bridge()
    b.proj = _mk_auto_proj(tmp_path / "cw_book")
    b.cfg = {"writing": {"run_mode": "cw"},
             "connections": [_ready_conn("a", "无模型连接", model="")], "slots": {}}
    calls = _capture_toast(b)
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "ModelRouter", _Recorder)
    b._spawn_cw_dialogue("开头写什么？", st.STAGE_CW_PROJECT, mode="discuss")
    assert any("还没选模型" in t for _, t in calls), "起跑前拦截必须给深链文案"
    assert b._cw_busy is False, "被拦路径不得进入 busy 态"


def test_dialogue_slot_single_source():
    """dialogue_slot：讨论（除世界书）走辅助槽；撰写/世界书走职责槽——与 worker 实际消费同源"""
    from app import config as cfg_mod
    from app.core import co_dialogue
    from app.prompts import co_writing as cp
    assert co_dialogue.dialogue_slot(st.STAGE_CW_CORE, "discuss") == cfg_mod.SLOT_HELPER
    assert co_dialogue.dialogue_slot(st.STAGE_CW_CORE, "compose") == \
        cp.CO_ROLES[st.STAGE_CW_CORE]["slot"]
    assert co_dialogue.dialogue_slot(st.STAGE_CW_WORLDBOOK, "discuss") == \
        cp.CO_ROLES[st.STAGE_CW_WORLDBOOK]["slot"]
    assert co_dialogue.dialogue_slot(st.STAGE_CW_PROSE, "compose") == cfg_mod.SLOT_WRITING


# ---------- 演示流同步（A2 联动） ----------

def test_demo_script_pipeline_intro_matches_cta():
    """演示 pipeline_intro 仍钉 startButton（objectName 未变），文案不再教人点「开始」真跑"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "assets", "demo", "script.json"), encoding="utf-8") as f:
        steps = json.load(f)["steps"]
    step = next(s for s in steps if s.get("id") == "pipeline_intro")
    assert step["target"] == "startButton"
    qml = open(os.path.join(root, "app", "ui", "qml", "PipelinePanel.qml"),
               encoding="utf-8").read()
    assert 'objectName: "startButton"' in qml, "演示 target 悬空：QML 里已无 startButton"
    assert "去共写" in step["text"], "演示文案未同步 CTA 新形态"
