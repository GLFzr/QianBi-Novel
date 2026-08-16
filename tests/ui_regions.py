# -*- coding: utf-8 -*-
"""部位级 UI 审计：关键状态分步截图 → 按部位命名裁剪 → 供逐部位评审

输出：tests_output/ui_regions/<屏>--<部位>.png（部位名编入文件名，评审时告知模型看的是哪）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests_output", "ui_regions")
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
RAW = os.path.join(OUT, "_raw")
os.makedirs(RAW, exist_ok=True)


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


def grab_to(path):
    def do():
        img = app.primaryScreen().grabWindow(win.winId())
        img.save(path)
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
                grab_to(os.path.join(RAW, name + ".png"))
            except Exception as e:
                print("grabfail", name, e, flush=True)
            print("CAP", name, "ERR" if err else "OK", str(err or "")[:80], flush=True)
            nxt()
        QTimer.singleShot(wait, fin)
    ACTIONS.append(run)


def nxt():
    ACTIONS.pop(0)
    if ACTIONS:
        ACTIONS[0]()
    else:
        crop_all()
        print("REGIONS_DONE", flush=True)
        QTimer.singleShot(200, app.quit)


def nav(key):
    win.setProperty("activePanel", key)


def close_dialogs():
    for n in ["rewriteDialog", "unsavedDialog", "versionsDialog", "recoverDialog", "statsDialog",
              "exportDialog", "regenDialog", "rewriteConfirmDialog", "chapterGuidanceDialog", "fileDialog"]:
        try:
            d = by_name(n)
            if d.property("visible"):
                d.close()
        except Exception:
            pass


# ============ 分步截图序列（每个可触发状态一步）============
at("pipeline_default", lambda: (close_dialogs(), nav("pipeline")))
at("pipeline_hover_start", lambda: None)          # 同屏（hover 无法程序触发，跳过）
at("notes", lambda: nav("notes"))
at("chapters", lambda: nav("chapters"))
at("shelf", lambda: nav("shelf"))
at("settings_conn", lambda: nav("settings"))
at("settings_writing", lambda: by_name("settingsPanel").setProperty("settingsTab", 1))
at("settings_appearance", lambda: by_name("settingsPanel").setProperty("settingsTab", 2))
at("settings_system", lambda: (close_dialogs(), by_name("settingsPanel").setProperty("settingsTab", 3)))
at("dlg_versions", lambda: (nav("pipeline"), by_name("versionsDialog").open()))
at("dlg_export", lambda: (by_name("versionsDialog").close(), by_name("exportDialog").refreshPreview(), by_name("exportDialog").open()))
at("dlg_stats", lambda: (by_name("exportDialog").close(), by_name("statsDialog").open()))
at("dlg_unsaved", lambda: (by_name("statsDialog").close(), b.markEditorDirty("部位审计"), by_name("unsavedDialog").open()))
at("dlg_rewrite", lambda: (by_name("unsavedDialog").close(), by_name("rewriteDialog").open()))
at("reader_night", lambda: (by_name("rewriteDialog").close(), b.setReaderPref("theme", "night"), win.openReader()), 650)
at("reader_toc", lambda: (find_reader().setProperty("drawerTab", "toc"), find_reader().setProperty("drawerOpened", True)))
at("reader_marks", lambda: (b.addAnnotation(2, "highlight_yellow", "这是第二章的内容", "", 0.1),
                            b.addBookmark(2, 0.4, "部位书签"), find_reader().refreshStore(),
                            find_reader().setProperty("drawerTab", "marks")))
at("reader_prefs", lambda: _open_prefs())
at("reader_close", lambda: find_reader().setProperty("opacity", 0))


def _open_prefs():
    r = find_reader()
    for c in r.findChildren(object):
        try:
            if c.metaObject().className() == "QQuickRectangle" and float(c.property("width") or 0) == 300:
                c.setProperty("visible", True)
                return
        except Exception:
            pass
    raise RuntimeError("prefs panel not found")


# ============ 部位裁剪表（屏名 → [(部位名, x, y, w, h)]，1400x900 窗口）============
W, H = 1400, 900
REGIONS = {
    'pipeline_default': [
        ('navrail', 0, 0, 48, 856),
        ('pipe-header', 48, 0, 300, 50),
        ('stage-cards', 50, 52, 296, 206),
        ('pipe-stepper-progress', 50, 260, 296, 106),
        ('pipe-controls', 50, 368, 296, 106),
        ('pipe-steppills-quality', 50, 476, 296, 156),
        ('pipe-idea-trend', 50, 634, 296, 240),
        ('topbar', 350, 2, 1046, 40),
        ('editor-body', 352, 48, 1044, 824),
        ('statusbar', 4, 878, 1392, 18),
    ],
    'notes': [
        ('notes-header', 48, 0, 300, 50),
        ('notes-newidea', 50, 52, 296, 170),
        ('notes-list', 50, 224, 296, 300),
        ('notes-globalprefs', 50, 560, 296, 314),
    ],
    'chapters': [
        ('chapters-header', 48, 0, 300, 50),
        ('chapters-list', 50, 52, 296, 820),
    ],
    'shelf': [
        ('shelf-header', 48, 0, 296, 50),
        ('shelf-cards', 50, 52, 296, 820),
    ],
    'settings_conn': [
        ('settings-note', 50, 12, 296, 92),
        ('settings-connlist', 50, 108, 296, 56),
        ('settings-tabs', 48, 20, 296, 26),
        ('settings-form-a', 50, 168, 296, 330),
        ('settings-form-b', 50, 500, 296, 374),
    ],
    'settings_writing': [('writing-page', 50, 52, 296, 820)],
    'settings_appearance': [('appearance-page', 50, 52, 296, 820)],
    'settings_system': [('system-page', 50, 52, 296, 820)],
    'dlg_versions': [
        ('dlg-title', 292, 182, 816, 76),
        ('dlg-versions-list', 292, 258, 262, 404),
        ('dlg-versions-diff', 554, 258, 552, 404),
        ('dlg-footer', 554, 662, 552, 52),
    ],
    'dlg_export': [
        ('dlg-export-opts', 362, 240, 676, 116),
        ('dlg-export-preview', 362, 358, 676, 296),
        ('dlg-export-footer', 362, 656, 676, 48),
    ],
    'dlg_stats': [('dlg-stats-grid', 482, 200, 436, 340), ('dlg-stats-footer', 482, 544, 436, 60)],
    'dlg_unsaved': [('dlg-unsaved-body', 458, 208, 484, 210), ('dlg-unsaved-footer', 458, 420, 484, 100)],
    'dlg_rewrite': [('dlg-rewrite-body', 388, 108, 624, 430), ('dlg-rewrite-footer', 388, 538, 624, 72)],
    'reader_night': [
        ('reader-topbar', 2, 2, 1396, 50),
        ('reader-chip', 2, 58, 260, 38),
        ('reader-bottom', 2, 852, 1396, 44),
    ],
    'reader_toc': [('reader-drawer', 1102, 56, 294, 788)],
    'reader_marks': [('reader-marks', 1102, 56, 294, 788)],
    'reader_prefs': [('reader-prefspanel', 1072, 56, 326, 396)],
}


def crop_all():
    from PIL import Image
    for screen, regs in REGIONS.items():
        p = os.path.join(RAW, screen + ".png")
        if not os.path.isfile(p):
            continue
        im = Image.open(p)
        for name, x, y, w, h in regs:
            box = (max(0, x), max(0, y), min(W, x + w), min(H, y + h))
            im.crop(box).save(os.path.join(OUT, f"{screen}--{name}.png"))
    print("cropped:", len(os.listdir(OUT)), "files", flush=True)


QTimer.singleShot(900, ACTIONS[0])
sys.exit(app.exec())
