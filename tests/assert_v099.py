# -*- coding: utf-8 -*-
"""V0.9.9 结构化断言：全部新功能后端行为 + QML 加载"""
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge
from app.core import state as st, stages

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(OUT, "tests_output", "m1_proj"))

app = QGuiApplication([])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(OUT, "app", "ui", "qml", "Main.qml")))
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)

results = []


def check(name, cond):
    results.append((name, bool(cond)))


def run():
    try:
        cards = b.stageCards()
        check("阶段卡片=4", len(cards) == 4)
        check("卡片状态合法", all(c["status"] in ("done", "active", "pending") for c in cards))
        ideas = b.ideasList()
        check("想法列表>=3", len(ideas) >= 3)
        check("想法结构化字段", all(k in ideas[0] for k in ("id", "text", "status", "scope", "ts")))
        b.saveGlobalPrefs("冷峻克制", "不写品牌", "三章一小高潮")
        wp = b.writingPrefs()
        check("全局偏好持久化", wp["stylePref"] == "冷峻克制" and wp["taboos"] == "不写品牌")
        b.saveGlobalPrefs("", "", "")
        g = stages._compose_guidance("本章要打脸", {"writing": {"style_pref": "短句", "taboos": "品牌", "pace_pref": ""}})
        check("指导+偏好合成", "本章要打脸" in g and "短句" in g and "品牌" in g)
        g2 = stages._compose_guidance("", {"writing": {}})
        check("空指导回退", g2 == "无特殊指导")
        rl = b.readerChapterList()
        check("阅读目录=2章含字数", len(rl) == 2 and rl[0]["words"] > 0)
        rc = b.readerChapter(2)
        check("阅读章节加载", rc["num"] == 2 and len(rc["text"]) > 0)
        b.setEditorPref("fontScale", 1.12)
        check("编辑器偏好持久化", b.editorPrefs()["fontScale"] == 1.12)
        b.setEditorPref("fontScale", 1.0)
        check("质量趋势", isinstance(b.qualityTrend(), list))
        pv = b.exportPreviewText("line", 1)
        check("导出预览非空", len(pv) > 10 and "———" in pv)
        b.setAutoBackup(True)
        check("自动备份开关", b.autoBackupEnabled() is True)
        b.setAutoBackup(False)
        b.setChapterWordTarget(2500)
        check("字数目标持久化", b.chapterWordTarget() == 2500)
        b.setChapterWordTarget(3000)
        # 想法消费：scope 匹配（先补一条指定章想法，避免历史消费影响）
        s = st.load_state(PROJ)
        st.add_idea(PROJ, s, "断言专用：第7章想法XQ77", "7")
        st.save_state(PROJ, s)
        s = st.load_state(PROJ)
        taken = st.take_ideas(s, 7)
        st.save_state(PROJ, s)
        check("指定章想法被取走", any("XQ77" in t for t in taken))
        # 重写前快照安全网（隔离副本）：重写后旧内容必须可从版本历史恢复
        t2 = os.path.join(OUT, "smoke_tmp", "t2")
        shutil.rmtree(t2, ignore_errors=True)
        shutil.copytree(PROJ, t2)
        b.proj = os.path.abspath(t2)
        from app import project as proj_mod
        from app.core import versions as ver_mod
        old_text = proj_mod.read_file([c for c in proj_mod.list_chapters(t2) if c[0] == 1][0][2])
        b.rewriteChapterWithGuidance(1, "更黑暗一点")
        vs = ver_mod.list_versions(t2, 1)
        latest = ver_mod.read_version(t2, 1, vs[-1]["v"]) if vs else ""
        check("重写前旧内容可恢复", latest == old_text and old_text != "")
        check("正文已移除待重写", b.diskTextOf(1) == "")
        # 导航含笔记（QJSValue → toVariant）
        nav = win.property("navItems")
        try:
            nav = nav.toVariant()
        except Exception:
            pass
        check("导航五项", len(nav or []) == 5)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("无异常", False)
    for n, ok in results:
        print(("PASS" if ok else "FAIL"), n, flush=True)
    print("TOTAL", sum(1 for _, ok in results if ok), "/", len(results), flush=True)
    app.quit()


QTimer.singleShot(1500, run)
sys.exit(app.exec())
