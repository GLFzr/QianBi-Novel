# -*- coding: utf-8 -*-
"""§7.3 仪器：审计痕可见性（WP-05 新增，台账点名此前 tests/unit 查无此件）。

四类审计痕迹必须有「写源 → bridge 读者 → 界面消费者」完整链路，缺一环即红：
  ① forced_locks（作者绕过的门）→ forcedLocksList() → 关于弹窗「强锁审计痕」区
  ② chapter_need_human（3 轮不收敛转人工）→ 队列注记「已转人工」→ 章节面板
  ③ is_review_stale（结论过期）→ 队列注记「结论已过期」+ 打开章时 toast
  ④ 门回退归档目录 → openProjDebugDir("rollback") → 关于弹窗「打开门回退归档」
静态结构断言：各环节的代码记号在位。删任一环（比如把 QML 消费者摘掉）即红。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_audit_trails_have_ui_readers():
    state_src = _read("app/core/state.py")
    bridge_src = _read("app/ui/bridge.py")
    orch_src = _read("app/core/orchestrator.py")
    qml_all = ""
    qml_root = os.path.join(ROOT, "app", "ui", "qml")
    for dp, _dn, fns in os.walk(qml_root):
        for fn in fns:
            if fn.endswith(".qml"):
                qml_all += open(os.path.join(dp, fn), encoding="utf-8").read()

    links = [
        # ① 强锁审计痕
        ("forced_locks 写源（state）", '"forced_locks"' in state_src),
        ("forced_locks 读者（bridge.forcedLocksList）", "forcedLocksList" in bridge_src),
        ("forced_locks 界面消费者（强锁审计痕区）", "强锁审计痕" in qml_all and "forcedLocksList" in qml_all),
        # ② 转人工痕
        ("chapter_need_human 写源（state）", "mark_chapter_need_human" in state_src and '"chapter_need_human"' in state_src),
        ("chapter_need_human 读者（bridge）", "is_chapter_need_human" in bridge_src),
        ("chapter_need_human 界面注记（已转人工）", "已转人工" in bridge_src and "note" in _read("app/ui/qml/ChapterPanel.qml")),
        # ③ 结论过期痕
        ("review_stale 判定（state）", "def is_review_stale" in state_src),
        ("review_stale 读者（bridge）", "is_review_stale" in bridge_src),
        ("review_stale 界面注记（结论已过期）", "结论已过期" in bridge_src),
        # ④ 门回退归档
        ("rollback 归档写源（orchestrator）", "pipeline_debug" in orch_src and 'rollback' in orch_src),
        ("归档读者（bridge.openProjDebugDir）", "openProjDebugDir" in bridge_src),
        ("归档界面入口（打开门回退归档按钮）", "打开门回退归档" in qml_all and 'openProjDebugDir("rollback")' in qml_all),
    ]
    missing = [name for name, ok in links if not ok]
    assert not missing, "审计痕链路断裂（写源→读者→界面缺一即红）：" + "；".join(missing)
