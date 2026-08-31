# -*- coding: utf-8 -*-
"""待修汇总 + 一键修复入口探针（不发任何 LLM 请求）

验证：① 注入 needs_fix 状态后 needsFixCount/needsFixChapters 聚合正确；
② NeedsFixDialog 可 refresh/open；③ QueueRow「查看问题」同路径
（showReviewIssues → onReviewIssuesChanged → ReviewIssueDialog 打开）；
④ 全程无 ReferenceError/TypeError 类 QML 警告。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import state as st
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "nfx_probe_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)


def build_fixture():
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    with open(os.path.join(PROJ, "正文", "第002章_乙.md"), "w", encoding="utf-8") as f:
        f.write("# 第2章 乙\n正文内容。\n")
    state = dict(st.DEFAULT_STATE)
    state = {
        "stage": "writing", "current_chapter": 2, "chapter_step": "",
        "total_chapters": 10, "paused": False,
        "history": [{"num": 2, "title": "乙", "words": 6,
                     "deslop_blocking": 0, "deslop_advisory": 0,
                     "status": "needs_fix", "ts": "2026-08-31 12:00:00"}],
        "pending_guidance": {}, "pending_ideas": [],
        "review_findings": {"2": {
            "verdict": "REJECT",
            "items": [{"dim": "C_FINGER", "level": "fail", "text": "金手指越界",
                       "quote": "x", "root_layer": "ROOT_PROSE", "line": ""}],
            "blocking": ["金手指越界"], "advisory": [],
            "ts": "2026-08-31 12:00:00"}},
        "review_chain": {}, "chapter_need_human": {}, "cw": {},
    }
    st.save_state(PROJ, state)


build_fixture()

app = QGuiApplication([])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
if not engine.rootObjects():
    print("FAIL: Main.qml 加载失败")
    for w in WARNINGS:
        print("  QML>", w)
    sys.exit(1)
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)


def check(name, ok):
    print(("[OK ] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        check.failed = True


check.failed = False


def find_by_object_name(name):
    for c in win.findChildren(object):
        try:
            if c.objectName() == name:
                return c
        except Exception:
            pass
    return None


def step1_backend():
    check("needsFixCount==1", int(b.property("needsFixCount")) == 1)
    entries = b.needsFixChapters()
    check("聚合含第2章·阻塞1·REJECT",
          len(entries) == 1 and entries[0]["num"] == 2
          and entries[0]["blocking"] == 1 and entries[0]["verdict"] == "REJECT")
    QTimer.singleShot(200, step2_dialog)


def _call(obj, method):
    return obj.metaObject().invokeMethod(obj, method)


def step2_dialog():
    dlg = find_by_object_name("needsFixDialog")
    check("NeedsFixDialog 存在", dlg is not None)
    if dlg:
        _call(dlg, "refresh")
        check("对话框 chapters 长度==1", len(dlg.property("chapters") or []) == 1)
        _call(dlg, "open")
    QTimer.singleShot(300, step3_opened)


def step3_opened():
    dlg = find_by_object_name("needsFixDialog")
    check("NeedsFixDialog 已打开", dlg is not None and bool(dlg.property("opened")))
    if dlg:
        _call(dlg, "close")
    QTimer.singleShot(200, step4_issue_dialog)


def step4_issue_dialog():
    # QueueRow「查看问题」同路径：showReviewIssues → reviewIssuesChanged → 主窗打开对话框
    b.showReviewIssues(2)
    QTimer.singleShot(400, step5_issue_opened)


def step5_issue_opened():
    dlg = find_by_object_name("reviewIssueDialog")
    opened = dlg is not None and bool(dlg.property("opened"))
    check("ReviewIssueDialog 已由查看问题打开", opened)
    check("对话框显示 1 项 issue",
          dlg is not None and len(dlg.property("issues") or []) == 1)
    check("verdict 已同步为该章登记判定",
          dlg is not None and dlg.property("verdict") == "REJECT")
    if dlg:
        _call(dlg, "close")
    QTimer.singleShot(100, step6_warnings)


def step6_warnings():
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_backend)
sys.exit(app.exec())
