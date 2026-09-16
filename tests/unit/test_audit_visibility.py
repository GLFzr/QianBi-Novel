# -*- coding: utf-8 -*-
"""§7.3 仪器：审计痕可见性（WP-05 新增；WP-14 按验收口径返工为结构断言）。

四类审计痕迹必须有「写源 → bridge 读者 → 界面消费者」完整链路，缺一环即红。

WP-14 返工点（旧实现全是源码子串匹配，抓不住三种逃逸）：
- 「bridge.forcedLocks」子串在 ⇒ 绿——把 AboutDialog 改回
  `text: { bridge.forcedLocksList() }` 方法调用式（永不重算，正是 L2-13 原病）
  依旧绿 ⇒ 现改为：QML 侧禁 `forcedLocksList()` 调用式，必须消费
  `bridge.forcedLocks` Property，且 bridge 侧必须有 @Property(notify=…) 定义；
- 「"note" in ChapterPanel.qml」近乎恒真 ⇒ 现改为：delegate 必须真实绑定
  `note: model.note`，且 QueueRow 必须把 row.note 渲染进 Text 绑定；
- 「结论已过期」只验 bridge 侧字符串、不要求 QML 消费者 ⇒ 现要求两条队列注记
  （已转人工 / 结论已过期）都经由同一条 model.note → QueueRow 渲染链上屏。
删任一环（比如把 QML 消费者摘掉）即红。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_forced_locks_reader_is_property_binding_not_method_call():
    """① 强锁审计痕：读者必须是绑定到 NOTIFY Property 的表达式，禁方法调用式。"""
    state_src = _read("app/core/state.py")
    bridge_src = _read("app/ui/bridge.py")
    about_src = _read("app/ui/qml/components/AboutDialog.qml")

    # 写源
    assert '"forced_locks"' in state_src, "state.py 无 forced_locks 写源"
    # bridge 读者：必须是带 NOTIFY 的 Property（L2-13 形态），不是裸方法
    assert re.search(r"forcedLocksChanged\s*=\s*Signal\(\)", bridge_src), (
        "bridge 无 forcedLocksChanged 信号——Property 永不重算（L2-13 原病）")
    assert re.search(r"@Property\([^)]*notify\s*=\s*forcedLocksChanged", bridge_src, re.S), (
        "bridge 的 forcedLocks 必须是 @Property(notify=forcedLocksChanged) 定义")
    # QML 消费者：必须消费 Property；方法调用式绑定禁绝
    assert re.search(r"bridge\.forcedLocksList\s*\(", about_src) is None, (
        "AboutDialog 又改回 bridge.forcedLocksList() 方法调用式绑定——永不重算，"
        "弹窗只显首帧值（L2-13 原病复演，WP-14 结构断言）")
    assert re.search(r"bridge\.forcedLocks\b", about_src), (
        "AboutDialog 不再消费 bridge.forcedLocks Property——强锁审计痕失去界面读者")
    assert "强锁审计痕" in about_src, "AboutDialog 缺「强锁审计痕」区块标题"


def test_queue_notes_render_chain_intact():
    """②③ 转人工痕 / 结论过期痕：注记文案必须经由 model.note 绑定 → QueueRow
    渲染链上屏（旧实现只查 '"note" in ChapterPanel.qml'——任何含 note 字样的
    文件都恒绿，链路断了也测不出来）。"""
    state_src = _read("app/core/state.py")
    bridge_src = _read("app/ui/bridge.py")
    chap_src = _read("app/ui/qml/ChapterPanel.qml")
    qrow_src = _read("app/ui/qml/components/QueueRow.qml")

    assert "mark_chapter_need_human" in state_src and '"chapter_need_human"' in state_src, (
        "state.py 无 chapter_need_human 写源")
    assert "def is_review_stale" in state_src, "state.py 无 is_review_stale 判定"
    assert "is_chapter_need_human" in bridge_src, "bridge 无转人工读者"
    # 两条注记文案的源头都在 bridge 队列构建器里
    assert "已转人工" in bridge_src, "bridge 队列注记缺「已转人工」"
    assert "结论已过期" in bridge_src, "bridge 队列注记缺「结论已过期」"
    # 渲染链：delegate 绑定 model.note → QueueRow 把 row.note 渲染进 Text
    assert re.search(r"\bnote\s*:\s*model\.note\b", chap_src), (
        "ChapterPanel delegate 不再绑定 note: model.note——队列注记（已转人工/结论已过期）失去界面读者")
    assert re.search(r"text\s*:[^\n]*row\.note\b", qrow_src), (
        "QueueRow 不再把 row.note 渲染进 Text——绑定接进来也不上屏")


def test_rollback_archive_entry_wired():
    """④ 门回退归档：写源 → openProjDebugDir 读者 → 界面按钮真调 openProjDebugDir("rollback")。"""
    orch_src = _read("app/core/orchestrator.py")
    bridge_src = _read("app/ui/bridge.py")
    about_src = _read("app/ui/qml/components/AboutDialog.qml")
    assert "pipeline_debug" in orch_src and "rollback" in orch_src, "orchestrator 无归档写源"
    assert "def openProjDebugDir" in bridge_src, "bridge 无 openProjDebugDir 读者"
    assert "打开门回退归档" in about_src, "AboutDialog 缺「打开门回退归档」入口"
    assert 'openProjDebugDir("rollback")' in about_src, (
        "归档按钮没有真实调用 openProjDebugDir(\"rollback\")——按钮是死的")
