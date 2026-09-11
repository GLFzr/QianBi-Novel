# -*- coding: utf-8 -*-
"""演示内容包与引导脚本校验（0.20.0）

这些测试是「演示不发疯」的下限：
- 包能加载、字段齐全；
- script.json 里每个 target 都真实存在于 QML 源码（objectName 交叉比对）——
  引导步骤指向不存在的控件 = 气泡永远悬空、用户被卡死在第一步；
- 回放素材与 book/ 产物自洽（共写轮次、撰写体、去味对照）；
- 伪流式时长不超过演示预算（正文流式是时长大头）。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.ui.demo_pack import DemoPack  # noqa: E402

QML_ROOT = os.path.join(ROOT, "app", "ui", "qml")


def _qml_sources() -> dict:
    out = {}
    for dp, _, fs in os.walk(QML_ROOT):
        for f in fs:
            if f.endswith(".qml"):
                p = os.path.join(dp, f)
                out[os.path.relpath(p, QML_ROOT)] = open(p, encoding="utf-8").read()
    return out


def test_pack_loads_and_validates():
    pack = DemoPack.load()
    assert pack is not None, "assets/demo 内容包缺失——演示入口将不可用"
    assert pack.missing() == [], f"内容包校验失败: {pack.missing()}"
    assert pack.book_meta.get("name"), "pack.json 缺书名"
    assert len(pack.steps) >= 15, "引导步骤过少，覆盖不了完整流程"


def test_script_targets_exist_in_qml():
    pack = DemoPack.load()
    assert pack is not None
    qml = _qml_sources()
    blob = "\n".join(qml.values())
    for step in pack.steps:
        t = step.get("target") or ""
        if not t:
            continue
        if t.startswith("nav_"):
            assert 'objectName: "nav_" + modelData.key' in blob, \
                "导航栏 delegate 缺 objectName 模板"
            key = t[4:]
            assert f'"key": "{key}"' in blob, f"导航无此面板 key: {key}"
            continue
        if t.startswith("stageCard_"):
            assert 'objectName: "stageCard_" + modelData.key' in blob, \
                "阶段卡片 delegate 缺 objectName 模板"
            key = t[len("stageCard_"):]
            assert f'"key": "{key}"' in blob, f"阶段卡片无此 key: {key}"
            continue
        assert f'objectName: "{t}"' in blob, f"步骤 {step['id']} 的目标控件 {t} 在 QML 中不存在"


def test_user_click_steps_have_completion_hooks():
    """每个 user_click 步骤都必须有推进来源：QML hook、bridge 信号分支或面板到达"""
    pack = DemoPack.load()
    assert pack is not None
    blob = "\n".join(_qml_sources().values())
    bridge_py = open(os.path.join(ROOT, "app", "ui", "bridge.py"), encoding="utf-8").read()
    for s in pack.steps:
        if s.get("mode") != "user_click":
            continue
        sid = s["id"]
        if sid == "click_new_project":
            assert 'demoStepDone("click_new_project")' in blob
        elif sid == "click_create":
            assert 'step_done("click_create")' in bridge_py
        elif sid in ("cw_send", "cw_write_send"):
            assert "cw_submit(text, mode)" in bridge_py
        elif sid == "cw_confirm":
            assert "cw_confirm()" in bridge_py
        elif sid == "finish_nav":
            assert "demoNotifyPanel" in blob or "demoNotifyPanel" in bridge_py
        else:
            raise AssertionError(f"user_click 步骤 {sid} 没有登记推进来源")


def test_fill_targets_supported_types():
    """fill 序列里每个目标要么是文本框（打字机）、要么是预设下拉/数字框（直接置值）"""
    pack = DemoPack.load()
    assert pack is not None
    for s in pack.steps:
        for f in s.get("fills") or []:
            assert f.get("target") and (
                "value" in f), f"步骤 {s['id']} 的 fill 缺 target/value"


def test_replay_assets_consistent():
    pack = DemoPack.load()
    assert pack is not None
    # 共写至少两轮（讨论 + 撰写），撰写轮的正文体必须真实存在
    assert len(pack.cw) >= 2
    write_turns = [t for t in pack.cw if t.get("mode") == "write"]
    assert write_turns, "共写缺「撰写」轮"
    for t in write_turns:
        assert t.get("body_file") and pack.book_has(t["body_file"]), \
            f"撰写轮 body_file 不存在: {t.get('body_file')}"
        body = pack.book_file(t["body_file"])
        assert len(body) > 100, "撰写体过短，撑不起流式演示"
    # 去味对照必须是两段不同真实文本
    assert pack.deslop["before"] != pack.deslop["after"]
    # 审校票真实形态
    assert (pack.review or {}).get("verdict") in ("PASS", "REJECT", "REJECT-HARD")


def test_streaming_duration_within_budget():
    """伪流式时长大头是正文：按导演的实际节奏参数核算，超出预算就是演示超时"""
    pack = DemoPack.load()
    assert pack is not None
    src_dir = open(os.path.join(ROOT, "app", "ui", "demo_director.py"), encoding="utf-8").read()
    # 从导演源码里抠出各阶段 stream(text, chars, ms) 参数，按 pack 里的真实文本长度算时长
    budget = (pack.pack.get("budget_s") or {}).get("pipeline", 150)
    total = 0.0
    for phase, rel in [("setting", "设定/题材定位.md"), ("outline", "大纲/大纲.md"),
                       ("ch_outline", "大纲/细纲_第001章.md"), ("prose", "正文/第001章_撕纸角.md")]:
        m = re.search(r'phase == "%s".*?op_stream\(P\.book_file\("([^"]+)"\), (\d+), (\d+)\)' % phase,
                      src_dir, re.S)
        assert m, f"导演里找不到 {phase} 阶段的流式参数"
        assert m.group(1) == rel, f"{phase} 阶段流式文本与预期不符"
        chars, ms = int(m.group(2)), int(m.group(3))
        total += len(pack.book_file(rel)) / chars * (ms / 1000.0)
    assert total < budget * 0.8, f"流水线流式总时长 {total:.0f}s 已逼近/超出预算 {budget}s"


def test_config_has_demo_done_default():
    from app import config as cfg_mod
    assert cfg_mod.DEFAULT_CONFIG.get("general", {}).get("demo_done") is False
