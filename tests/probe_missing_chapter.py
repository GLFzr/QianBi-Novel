# -*- coding: utf-8 -*-
"""缺失章节可打开探针（不发任何 LLM 请求）

验证：① 仅有细纲、无正文的章节出现在列表（outline_ready）；
② openChapter 对缺失章合成空打开（currentChapterNum/空内容/预期路径）；
③ 保存后落盘无标题文件、刷新列表转 untracked；④ 无 ReferenceError/TypeError。
"""
import os
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
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "miss_ch_probe_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)


def build_fixture():
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    with open(os.path.join(PROJ, "正文", "第001章_甲.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 甲\n内容。")
    with open(os.path.join(PROJ, "大纲", "细纲_第002章.md"), "w", encoding="utf-8") as f:
        f.write("核心事件：乙事件\n故事内容：略。")
    old = os.path.join(PROJ, "正文", "第002章.md")
    if os.path.exists(old):
        os.remove(old)
    st.save_state(PROJ, {"stage": "writing", "current_chapter": 1,
                         "total_chapters": 5, "history": [
                             {"num": 1, "title": "甲", "words": 3, "status": "pass",
                              "deslop_blocking": 0, "deslop_advisory": 0, "ts": "T"}]})


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


def model_items():
    m = b.property("chapterModelProp")
    return list(m._items)


def step1_list():
    items = {it["num"]: it for it in model_items()}
    check("列表含缺失的第2章（细纲就绪）",
          2 in items and items[2]["state"] == "outline_ready")
    check("第1章仍为通过", items.get(1, {}).get("state") == "pass")
    QTimer.singleShot(200, step2_open_missing)


def step2_open_missing():
    b.openChapter(2)
    check("currentChapterNum==2", int(b.property("currentChapterNum")) == 2)
    check("编辑器内容为空", b.property("chapterText") == "")
    path = b.property("chapterPath")
    check("路径指向无标题预期文件", str(path).endswith(os.path.join("正文", "第002章.md")))
    QTimer.singleShot(200, step3_save)


def step3_save():
    b.saveChapterText("# 第2章 乙\n补写出来的正文。")
    p = os.path.join(PROJ, "正文", "第002章.md")
    check("保存落盘 第002章.md", os.path.isfile(p))
    items = {it["num"]: it for it in model_items()}
    check("保存后第2章转 untracked", items.get(2, {}).get("state") == "untracked")
    QTimer.singleShot(100, step4_warnings)


def step4_warnings():
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_list)
sys.exit(app.exec())
