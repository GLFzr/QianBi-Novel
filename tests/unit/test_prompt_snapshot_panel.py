# -*- coding: utf-8 -*-
"""E1 装配预览面板（Context Viewer）单测：SnapshotPanelController 访问器
+ 真实 ctx（stages._snap_prompt 写入）链路 + 空态 fail-open + 面板 QML 钉扎。

口径（docs/落地计划附录A 卡 E1 / 0.23.0 施工批）：
- bridge.snapshotPanel 独立 controller（照 C26/C39 先例不摊主类），只读不写、
  零新增配置键；
- promptSnapshotKinds = ctx.prompt_snapshots 可用 kind（流水线装配顺序，
  未知 kind 字母序垫底）；
- promptSnapshot(kind) = 该 kind 最新装配 prompt 全文（未装配 → 空串）；
- promptSnapshotChapter = ctx.prompt_snapshot_ch（chapter_microcycle 章入口
  写入；无项目/未跑 → 0）；
- orchestrator 即 stage ctx（stages.chapter_microcycle(self, …) 把 self 传
  进去），controller 沿 bridge.orch 读——orch=None/属性缺失/坏型一律
  fail-open（空列表/0/空串），绝不抛进 UI。
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import stages  # noqa: E402


# ---------- 测试脚手架（照 test_cost_panel 先例，不起 Qt 应用） ----------

class _FakeOrch:
    """最小 ctx 形状：orchestrator 即 stage ctx（属性缺失=流水线还没跑过章）"""
    def __init__(self, snaps=None, ch=0):
        if snaps is not None:
            self.prompt_snapshots = snaps
        self.prompt_snapshot_ch = ch


class _FakeBridge:
    """controller 只吃 orch 一个属性"""
    def __init__(self, orch=None):
        self.orch = orch


def _ctl(orch=None):
    from app.ui.bridge import SnapshotPanelController
    return SnapshotPanelController(_FakeBridge(orch))


# ---------- 访问器：kind 列表 / 全文 / 章号 ----------

def test_kinds_listed_in_pipeline_order():
    """可用 kind 按流水线装配顺序排；未知 kind 字母序垫底（下拉顺序稳定可预期）"""
    orch = _FakeOrch({"chapter_summary": "C", "zz_unknown": "U",
                      "prose": "P", "deslop": "D"}, ch=3)
    ctl = _ctl(orch)
    assert ctl.promptSnapshotKinds == ["prose", "deslop", "chapter_summary",
                                       "zz_unknown"]


def test_prompt_snapshot_returns_full_text_of_latest_assembly():
    """promptSnapshot(kind) 返回该 kind 最新装配 prompt 全文；未装配 → 空串"""
    orch = _FakeOrch({"prose": "P-全文", "deslop": "D-全文"}, ch=1)
    ctl = _ctl(orch)
    assert ctl.promptSnapshot("prose") == "P-全文"
    assert ctl.promptSnapshot("deslop") == "D-全文"
    assert ctl.promptSnapshot("enrich") == "", "未触发的相位 → 空串（空态口径）"
    assert ctl.promptSnapshot("") == ""


def test_prompt_snapshot_chapter_property():
    """promptSnapshotChapter = ctx.prompt_snapshot_ch；缺失/None → 0"""
    assert _ctl(_FakeOrch({"prose": "P"}, ch=7)).promptSnapshotChapter == 7
    assert _ctl(_FakeOrch({"prose": "P"}, ch=0)).promptSnapshotChapter == 0
    assert _ctl(_FakeOrch()).promptSnapshotChapter == 0


def test_non_string_snapshot_value_is_not_leaked():
    """快照值坏型（非 str）→ 按空串处理，绝不把脏对象递给 UI"""
    orch = _FakeOrch({"prose": 123, "deslop": None}, ch=2)
    ctl = _ctl(orch)
    assert ctl.promptSnapshot("prose") == ""
    assert ctl.promptSnapshot("deslop") == ""
    assert ctl.promptSnapshotKinds == ["prose", "deslop"], "kind 在场不受值坏型影响"


# ---------- 空态：无项目 / 流水线未跑（fail-open） ----------

def test_empty_ctx_yields_empty_state():
    """orch=None（未开项目）→ 空列表 / 0 / 空串，绝不抛"""
    ctl = _ctl(None)
    assert ctl.promptSnapshotKinds == []
    assert ctl.promptSnapshotChapter == 0
    assert ctl.promptSnapshot("prose") == ""
    assert ctl.refresh() is None, "空态下刷新也必须安全"


def test_orch_without_snapshot_attrs_yields_empty_state():
    """orchestrator 在场但还没跑过章（prompt_snapshots 属性缺失）→ 同空态"""
    ctl = _ctl(_FakeOrch())
    assert ctl.promptSnapshotKinds == []
    assert ctl.promptSnapshotChapter == 0
    assert ctl.promptSnapshot("prose") == ""


def test_orch_with_corrupted_snapshot_dict_fail_open():
    """ctx.prompt_snapshots 坏型（非 dict）→ 按空处理，不抛"""
    orch = _FakeOrch(ch=5)
    orch.prompt_snapshots = ["not", "a", "dict"]
    ctl = _ctl(orch)
    assert ctl.promptSnapshotKinds == []
    assert ctl.promptSnapshot("prose") == ""


# ---------- 真实 ctx 链路：stages._snap_prompt 写入 → controller 读出 ----------

def _real_ctx():
    """最小真 ctx：stages._snap_prompt 只吃 prompt_snapshots/last_prompt/cfg"""
    return types.SimpleNamespace(last_prompt="", cfg={}, prompt_snapshot_ch=0)


def test_real_snap_prompt_flows_into_controller():
    """stages._snap_prompt(ctx, kind) 写入 → 同一 ctx 当 orch → 访问器读出；
    章号由 chapter_microcycle 章入口写 prompt_snapshot_ch（_snap_prompt 不碰）"""
    ctx = _real_ctx()
    ctx.prompt_snapshot_ch = 3          # 章入口（chapter_microcycle 开头）语义
    ctx.last_prompt = "装配后的最终 prompt 全文"
    stages._snap_prompt(ctx, "prose", 3)
    ctl = _ctl(ctx)
    assert ctl.promptSnapshotKinds == ["prose"]
    assert ctl.promptSnapshot("prose") == "装配后的最终 prompt 全文"
    assert ctl.promptSnapshotChapter == 3


def test_chapter_entry_reset_visible_after_refresh():
    """章入口清零纪律（ctx.prompt_snapshots = {}）→ 刷新后面板回到空态；
    refresh() 发 dataChanged 通知（QML 据此回读）"""
    ctx = _real_ctx()
    ctx.last_prompt = "P1"
    stages._snap_prompt(ctx, "prose", 1)
    ctl = _ctl(ctx)
    assert ctl.promptSnapshotKinds == ["prose"]

    seen = []
    ctl.dataChanged.connect(lambda: seen.append(1))
    ctl.refresh()
    assert seen, "refresh() 必须发 dataChanged（QML 回读触发）"

    # 章入口清零（chapter_microcycle 开头两行的模拟）
    ctx.prompt_snapshots = {}
    ctx.prompt_snapshot_ch = 2
    ctl.refresh()
    assert ctl.promptSnapshotKinds == [], "清零后不许残留上一章 kind（陈旧键纪律）"
    assert ctl.promptSnapshot("prose") == ""
    assert ctl.promptSnapshotChapter == 2


def test_multi_kind_accumulation_within_chapter():
    """同章多挂点累积：prose/deslop/chapter_summary 依次入座，互不覆盖"""
    ctx = _real_ctx()
    for kind, text in (("prose", "PP"), ("deslop", "DD"),
                       ("chapter_summary", "CS")):
        ctx.last_prompt = text
        stages._snap_prompt(ctx, kind, 4)
    ctl = _ctl(ctx)
    assert ctl.promptSnapshotKinds == ["prose", "deslop", "chapter_summary"]
    assert ctl.promptSnapshot("chapter_summary") == "CS"


# ---------- 面板 QML 钉扎（真编译走 tests/probe_qml_compile.py） ----------

def _read_settings_panel() -> str:
    src = os.path.join(ROOT, "app", "ui", "qml", "SettingsPanel.qml")
    with open(src, encoding="utf-8") as f:
        return f.read()


def test_qml_panel_section_wiring():
    """设置面板「装配预览」节：controller 出口 / kind 下拉 / 只读等宽大文本框 /
    刷新 / 复制全文 / 空态说明，一样不许缺"""
    src = _read_settings_panel()
    assert "装配预览（Context Viewer）" in src
    assert "bridge.snapshotPanel.refresh()" in src
    assert "bridge.snapshotPanel.promptSnapshotKinds" in src
    assert "bridge.snapshotPanel.promptSnapshot(" in src
    assert "bridge.snapshotPanel.promptSnapshotChapter" in src
    assert 'id: snapKind' in src, "kind 下拉在场"
    assert 'id: snapView' in src and "readOnly: true" in src, "只读大文本框在场"
    assert "Theme.monoFont" in src, "等宽字体（Theme.monoFont）"
    assert "复制全文" in src and "bridge.copyText(" in src
    assert "生成一章后可查看" in src, "空态说明"


def test_bridge_exposes_snapshot_panel_property():
    """bridge.snapshotPanel 常量 Property 出口在场（照 modelPolicy/costPanel 先例）"""
    import inspect
    from app.ui import bridge as bridge_mod
    src = inspect.getsource(bridge_mod)
    assert "snapshotPanel = Property(QObject" in src
    assert "SnapshotPanelController" in src
    # 访问器三件套同名在场（任务合同）
    ctl_src = inspect.getsource(bridge_mod.SnapshotPanelController)
    assert "def promptSnapshotKinds" in ctl_src
    assert "def promptSnapshot(" in ctl_src
    assert "def promptSnapshotChapter" in ctl_src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
