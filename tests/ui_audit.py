# -*- coding: utf-8 -*-
"""全量 UI 审计截图：每个面板 / 每个弹窗 / 每个可交互状态，逐一截屏到 tests_output/ui_audit/"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests_output", "ui_audit")
os.makedirs(OUT, exist_ok=True)
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj"))

app = QGuiApplication([])
engine = QQmlApplicationEngine()
b = Bridge()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)

ACTIONS = []


def by_name(name):
    for c in win.findChildren(object):
        if c.objectName() == name:
            return c
    raise RuntimeError("not found: " + name)


def find_reader():
    for c in win.findChildren(object):
        if "ReaderView" in c.metaObject().className():
            return c
    raise RuntimeError("no reader")


def shot(name):
    def do():
        img = app.primaryScreen().grabWindow(win.winId())
        img.save(os.path.join(OUT, f"{name}.png"))
        print("shot", name, flush=True)
    win.setVisible(False)
    win.setVisible(True)
    QTimer.singleShot(160, do)


def at(name, fn=None, wait=420):
    def run():
        err = None
        if fn:
            try:
                fn()
            except Exception as e:
                err = e

        def fin():
            try:
                shot(name)
            except Exception as e:
                print("shotfail", name, e, flush=True)
            print("STEP", name, "ERR" if err else "OK", str(err or "")[:100], flush=True)
            nxt()
        QTimer.singleShot(wait, fin)
    ACTIONS.append(run)


def nxt():
    ACTIONS.pop(0)
    if ACTIONS:
        ACTIONS[0]()
    else:
        print("AUDIT_DONE", flush=True)
        QTimer.singleShot(200, app.quit)


def nav(key):
    win.setProperty("activePanel", key)


def close_all_dialogs():
    for n in ["rewriteDialog", "unsavedDialog", "versionsDialog", "recoverDialog", "statsDialog",
              "exportDialog", "regenDialog", "rewriteConfirmDialog", "chapterGuidanceDialog", "fileDialog"]:
        try:
            d = by_name(n)
            if d.property("visible"):
                d.close()
        except Exception:
            pass


# ============ 截图序列 ============
at("01_shelf", lambda: nav("shelf"))
at("02_pipeline", lambda: (close_all_dialogs(), nav("pipeline")))
at("03_notes", lambda: nav("notes"))
at("04_chapters", lambda: nav("chapters"))
at("05_settings_conn", lambda: nav("settings"))
at("06_settings_writing", lambda: by_name("settingsPanel").setProperty("settingsTab", 1))
at("07_settings_appearance", lambda: by_name("settingsPanel").setProperty("settingsTab", 2))
at("08_settings_system", lambda: by_name("settingsPanel").setProperty("settingsTab", 3))
# 弹窗族
at("09_versions_dialog", lambda: (nav("pipeline"), by_name("versionsDialog").open()))
at("10_export_dialog", lambda: (by_name("versionsDialog").close(), by_name("exportDialog").refreshPreview(), by_name("exportDialog").open()))
at("11_stats_dialog", lambda: (by_name("exportDialog").close(), by_name("statsDialog").open()))
at("12_unsaved_dialog", lambda: (by_name("statsDialog").close(), b.markEditorDirty("审计用未保存"), by_name("unsavedDialog").open()))
at("13_recover_dialog", lambda: (by_name("unsavedDialog").close(), by_name("recoverDialog").open()))
at("14_regen_dialog", lambda: (by_name("recoverDialog").close(), nav("pipeline"), by_name("regenDialog").open()))
at("15_rewrite_dialog", lambda: (by_name("regenDialog").close(), by_name("rewriteDialog").open()))
at("16_guidance_dialog", lambda: (by_name("rewriteDialog").close(), nav("chapters"), by_name("chapterGuidanceDialog").open()))
at("17_confirm_rewrite", lambda: (by_name("chapterGuidanceDialog").close(), by_name("rewriteConfirmDialog").open()))
at("18_file_dialog", lambda: (by_name("rewriteConfirmDialog").close(), by_name("fileDialog").open()))
# 阅读器全状态
at("19_reader_night", lambda: (by_name("fileDialog").close(), b.setReaderPref("theme", "night"), win.openReader()), 650)
at("20_reader_toc", lambda: (find_reader().setProperty("drawerTab", "toc"), find_reader().setProperty("drawerOpened", True)))
at("21_reader_marks", lambda: (b.addAnnotation(2, "highlight_yellow", "这是第二章的内容", "", 0.1),
                               b.addAnnotation(2, "comment", "剧情推进", "节奏太拖，定稿前压缩", 0.4),
                               b.addBookmark(2, 0.4, "审计书签"),
                               find_reader().refreshStore(),
                               find_reader().setProperty("drawerTab", "marks"),
                               find_reader().setProperty("drawerOpened", True)))
at("22_reader_prefs", lambda: (find_reader().setProperty("drawerOpened", False), _open_prefs()))
at("23_reader_parchment", lambda: (b.setReaderPref("theme", "parchment"), find_reader().setProperty("prefs", b.readerPrefs()), find_reader().setProperty("drawerOpened", False)))
at("24_reader_white_big", lambda: (b.setReaderPref("theme", "white"), b.setReaderPref("fontScale", 1.35), find_reader().setProperty("prefs", b.readerPrefs())))
at("25_back_pipeline", lambda: (b.setReaderPref("fontScale", 1.0),
                                find_reader().metaObject().invokeMethod(find_reader(), "close")))


def _open_prefs():
    r = find_reader()
    # Aa 排版面板：reader 直接子矩形，宽 300 且有 border（唯一）
    for c in r.findChildren(object):
        try:
            if c.metaObject().className() == "QQuickRectangle" and float(c.property("width") or 0) == 300:
                c.setProperty("visible", True)
                return
        except Exception:
            pass
    raise RuntimeError("prefs panel not found")


QTimer.singleShot(900, ACTIONS[0])
sys.exit(app.exec())
