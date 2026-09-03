# -*- coding: utf-8 -*-
"""发布物料（简介与标签）对话框探针（不发任何 LLM 请求）

验证：① blurbDialog 存在/可打开；② 打开即载入已保存物料（blurbText）；
③ blurbGenerated 信号联动刷新内容 + 清 busy；④ copyText 进剪贴板；
⑤ 生成按钮文案随内容切换（生成/重新生成）；⑥ 无 ReferenceError/TypeError。
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import state as st
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "blurb_probe_proj"))
SAVED_BLURB = "## 发布标签\n- 测试标签甲\n- 测试标签乙\n\n## 一句话简介\n探针用简介。"

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)


def build_fixture():
    if os.path.isdir(PROJ):
        shutil.rmtree(PROJ)
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    with open(os.path.join(PROJ, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("## 题材定位\n测试题材。\n")
    with open(os.path.join(PROJ, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("# 全书大纲\n测试大纲。\n")
    with open(os.path.join(PROJ, "设定", "简介与标签.md"), "w", encoding="utf-8") as f:
        f.write(SAVED_BLURB)
    state = dict(st.DEFAULT_STATE)
    state.update({"stage": "writing", "current_chapter": 1, "total_chapters": 5})
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


def step1_open():
    dlg = find_by_object_name("blurbDialog")
    check("blurbDialog 存在", dlg is not None)
    if dlg:
        dlg.metaObject().invokeMethod(dlg, "open")
    QTimer.singleShot(300, step2_loaded)


def step2_loaded():
    dlg = find_by_object_name("blurbDialog")
    check("对话框已打开", dlg is not None and bool(dlg.property("opened")))
    content = dlg.property("content") if dlg else ""
    check("打开即载入已保存物料", content == SAVED_BLURB)
    check("busy 初始为 false", dlg is not None and not dlg.property("busy"))
    # 按钮文案：已有内容 → 「重新生成」
    texts = []
    for c in dlg.findChildren(object) if dlg else []:
        try:
            t = c.property("text")
            if isinstance(t, str) and t:
                texts.append(t)
        except Exception:
            pass
    check("按钮显示「重新生成」", "重新生成" in texts)
    check("复制全文按钮存在", "复制全文" in texts)
    QTimer.singleShot(100, step3_signal)


def step3_signal():
    dlg = find_by_object_name("blurbDialog")
    dlg.setProperty("busy", True)
    b.blurbGenerated.emit(True, "## 新生成的简介内容")
    QTimer.singleShot(200, step4_after_signal)


def step4_after_signal():
    dlg = find_by_object_name("blurbDialog")
    check("信号联动：内容已刷新", dlg.property("content") == "## 新生成的简介内容")
    check("信号联动：busy 已清零", not dlg.property("busy"))
    QTimer.singleShot(100, step5_clipboard)


def step5_clipboard():
    b.copyText("探针剪贴板内容")
    cb = QGuiApplication.clipboard()
    check("copyText 已写入剪贴板", cb is not None and cb.text() == "探针剪贴板内容")
    dlg = find_by_object_name("blurbDialog")
    if dlg:
        dlg.metaObject().invokeMethod(dlg, "close")
    QTimer.singleShot(200, step6_warnings)


def step6_warnings():
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_open)
rc = app.exec()
shutil.rmtree(PROJ, ignore_errors=True)
sys.exit(0 if not check.failed and rc == 0 else 1)
