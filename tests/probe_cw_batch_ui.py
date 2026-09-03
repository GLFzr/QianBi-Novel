# -*- coding: utf-8 -*-
"""共写档界面探针（#1 输入框折行长高 / #5 细纲批次定位 / #6 滚动跟随）

不发任何 LLM 请求：全部走真 Bridge + 真 QML 对象树，验证界面在数据到位后
确实渲染成用户要的样子。重点是三条容易悄悄退回来的行为：
① 编辑器跟随最新一批细纲，点旧批次回执能切回旧批次；
② 批量视图下保存必须拆回各章文件，不能把整批写进一个文件；
③ 输入框超过一行会折行并长高；列表只在用户主动回底后才跟随新内容。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem

from app import project
from app.core import co_dialogue, state as st
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)

app = QGuiApplication(sys.argv)

TMP = tempfile.mkdtemp(prefix="qbn_cw_batch_")
PROJ = project.create_project(TMP, "批次探针书")
for n in range(1, 11):
    project.write_file(project.get_outline_path(PROJ, n),
                       "核心事件：事件%02d\n故事内容：内容%02d" % (n, n))
state = st.load_state(PROJ)
cw = st.ensure_cw(state)
cw["mode"] = "cw"
cw["stage"] = st.STAGE_CW_UNIT
cw["unit"] = {"start": 1, "target_end": 20, "topic": "开篇单元"}
cw["last_outline_batch"] = [6, 7, 8]
co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "user", "先把前三章写细一点")
co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "agent",
                              "✅ 本批细纲已生成：第 1-3 章", nums=[1, 2, 3])
st.save_state(PROJ, state)

b = Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", b)
engine.addImportPath(os.path.join(ROOT, "app", "ui", "qml"))
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
assert engine.rootObjects(), "Main.qml 加载失败"
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)

results = []


def check(name, ok):
    results.append((name, bool(ok)))


def item(object_name):
    it = win.findChild(QQuickItem, object_name)
    assert it is not None, f"找不到 {object_name}"
    return it


def pump(ms=250):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


def add_messages(k):
    """往转写里追加 k 条长消息（模拟 AI 连续回复把列表撑高）"""
    s = st.load_state(PROJ)
    for i in range(k):
        co_dialogue.transcript_append(
            s, st.STAGE_CW_UNIT, "agent",
            "第 %d 段：雨落了整夜，陈更把账重算了三遍，天亮前又去看了眼仓库。" % i)
    st.save_state(PROJ, s)
    b._cw_sync_messages()
    pump()


def step1_product_follows_latest_batch():
    # ① 进细纲阶段：编辑器应显示最新一批（6-8），不是历史第一批
    b._cw_open_product(st.STAGE_CW_UNIT)
    pump()
    txt = b.chapterText
    check("编辑器跟随最新一批（含事件06-08）",
          all(("事件%02d" % n) in txt for n in (6, 7, 8)))
    check("不再停在历史第一批", "事件01" not in txt)
    check("标题写明批次范围", b._cw_get_chapter_title() == "细纲 第6-8章（3 章一批）")
    check("批量态没有单一文件路径（防串写）", b._chapter_path == "")
    check("canSaveEditor 在批量态仍为真", b.canSaveEditor is True)
    QTimer.singleShot(60, step2_batch_link_visible)


def step2_batch_link_visible():
    # ② 对话流用增量模型渲染，批次回执带「点我看这批细纲」
    lst = item("cwMsgList")
    dock = item("cwDialogueDock")
    def g(it, name):
        return float(it.property(name) or 0)
    check("对话流走增量模型", lst is not None and int(g(lst, "count")) == 2)
    add_messages(14)
    check("追加后行数同步增长", int(g(lst, "count")) == 16)
    check("内容已超出视口（可测滚动）", g(lst, "contentHeight") > g(lst, "height") + 40)
    dock.setProperty("follow", False)
    lst.setProperty("contentY", 0)
    pump()
    y0 = g(lst, "contentY")
    add_messages(4)
    check("未开跟随：新消息不拽动视图", abs(g(lst, "contentY") - y0) < 2)
    dock.setProperty("follow", True)
    add_messages(2)
    pump()
    check("开跟随后贴住底部",
          g(lst, "contentY") + g(lst, "height") >= g(lst, "contentHeight") - 6)
    QTimer.singleShot(60, step3_click_receipt_opens_that_batch)


def step3_click_receipt_opens_that_batch():
    # ③ 点第 1-3 章那条回执 → 切回 1-3（即使最新一批是 6-8）
    b.showCwOutlineBatch([1, 2, 3])
    pump()
    txt = b.chapterText
    check("点旧批次回看该批", all(("事件%02d" % n) in txt for n in (1, 2, 3))
          and "事件06" not in txt)
    check("回看不改状态机的最新批次记录",
          st.ensure_cw(st.load_state(PROJ)).get("last_outline_batch") == [6, 7, 8])
    # 保存：改第 2 章必须只落进第 2 章文件
    b.saveCwProduct(txt.replace("事件02", "改过的乙事件"))
    pump()
    one = project.read_file(project.get_outline_path(PROJ, 1))
    two = project.read_file(project.get_outline_path(PROJ, 2))
    eight = project.read_file(project.get_outline_path(PROJ, 8))
    check("批量保存只改动对应章", "改过的乙事件" in two and "改过的乙事件" not in one)
    check("批量保存不误伤别的批次文件", "改过的乙事件" not in eight)
    check("第1章内容未被整批覆盖", "事件02" not in one and "事件03" not in one)
    QTimer.singleShot(60, step4_input_grows)


def step4_input_grows():
    scr = item("cwInputScroll")
    ta = item("cwInput")
    h0 = float(scr.property("height") or 0)
    long_text = "\n".join(["第 %d 行：这是一段会比较长的想法，用来验证输入框会不会折行。" % i
                           for i in range(6)])
    ta.setProperty("text", long_text)
    pump(400)
    h1 = float(scr.property("height") or 0)
    check("输入框随行数长高", h1 > h0 + 40)
    check("输入框折行（多行内容按行排）", int(ta.property("lineCount") or 1) >= 6)
    check("长高有上限（不挤掉对话区）", h1 <= 141)
    QTimer.singleShot(60, step5_reader_toggle)


def step5_reader_toggle():
    project.write_file(os.path.join(PROJ, "正文", "第001章_雨夜.md"),
                       "正文第一句。" * 30)
    project.write_file(project.get_chapter_path(PROJ, 2), "第二章正文。" * 30)
    b._cur_num = 1
    chs = b.readerChapterList()
    check("阅读器有可读章节", len(chs) >= 1)
    win.openReader()
    pump(500)
    r = None
    for c in win.findChildren(object):
        if "ReaderView" in c.metaObject().className():
            r = c
            break
    assert r is not None, "找不到 ReaderView"
    check("默认看正文", "正文第一句" in r.property("bodyText")
          and r.property("showOutline") is False)
    r.setProperty("outlineText", b.readerChapterOutline(1))
    r.setView(True)
    pump(300)
    check("切到细纲后显示细纲", "事件01" in r.property("bodyText")
          and r.property("showOutline") is True)
    r.setView(False)
    pump(300)
    check("切回正文", "正文第一句" in r.property("bodyText"))
    r.close()
    QTimer.singleShot(200, finish)


def finish():
    errs = [w for w in WARNINGS
            if any(k in w for k in ("ReferenceError", "TypeError", "Cannot assign",
                                    "is not defined", "undefined behavior"))]
    check("无 QML 运行时错误", not errs)
    print("=== 共写批次界面探针 ===")
    ok = True
    for name, passed in results:
        print(("PASS" if passed else "FAIL"), name)
        ok = ok and passed
    for w in errs:
        print("QML-ERR:", w)
    print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
    shutil.rmtree(TMP, ignore_errors=True)
    QTimer.singleShot(50, app.quit)
    sys.exit(0 if ok else 1)


QTimer.singleShot(700, step1_product_follows_latest_batch)
app.exec()
