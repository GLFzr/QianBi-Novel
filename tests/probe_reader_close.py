# -*- coding: utf-8 -*-
"""阅读器开/关与抽屉探针（修复 drawer id 回归用）

验证：① openReader 后 opacity=1；② close()（退出按钮同路径）后淡出到 0 且 visible=False；
③ drawerOpened=True 时抽屉真实可见；④ 全程无 ReferenceError 类 QML 警告。
不发任何 LLM 请求。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 独占项目路径：m1_proj 被 panel_fit/settings_tabs/ui_gallery 多支探针共用，舰队字母序
# panel_fit 先跑会留下无章节布局，本探针 isdir 跳夹具 ⇒ 章表恒空（solo 必过/舰队必挂）
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "m1_proj_reader_close"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)

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

# 自备一次性项目：过去靠「本机恰好有 tests_output/m1_proj」才能过——干净 runner 上
# _open_project 静默失败 ⇒ openReader 走「请先打开项目」早退，opacity 永远 0（CI 三轮红的根因）
from app import project as _proj
if not _proj.is_project(PROJ):
    # create_project(root, name) 会在 root/name 下建四目录——想在 PROJ 处得到项目根，
    # 必须以 PROJ 的父目录为 root（传错一层会让项目结构半残、章表恒空）
    _proj.create_project(os.path.dirname(PROJ), os.path.basename(PROJ))
    _proj.write_idea_info(PROJ, "悬疑脑洞", "番茄", "探针夹具", 10)
if not _proj.list_chapters(PROJ):
    _ch = _proj.get_chapter_path(PROJ, 1, "第一章")
    _proj.write_file(_ch, "# 第一章\n\n阅读器探针夹具正文，与被断言的开关行为无关。")
b._open_project(PROJ, silent=True)


def find_reader():
    for c in win.findChildren(object):
        if "ReaderView" in c.metaObject().className():
            return c
    raise RuntimeError("no reader")


def check(name, ok):
    print(("[OK ] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        check.failed = True


check.failed = False


def wait_until(fn, timeout_ms, then):
    """轮询到条件成立再走下一步（慢 runner 上淡入/淡出动画未必在固定 sleep 内播完）。"""
    state = {"left": timeout_ms}

    def tick():
        if fn() or state["left"] <= 0:
            then()
        else:
            state["left"] -= 50
            QTimer.singleShot(50, tick)
    tick()


def step0_wait_project():
    # _open_project 是异步加载：慢 runner 上事件未回来时 hasProject 仍 False，
    # openReader 会走「请先打开项目」早退——先等加载完成再进场（本地快所以从未暴露）
    def tick(left):
        if b.hasProject or left <= 0:
            print(f"DIAG hasProject={b.hasProject} chapters={len(b.readerChapterList)}", flush=True)
            step1_open()
        else:
            QTimer.singleShot(100, lambda: tick(left - 100))
    tick(10000)


def step1_open():
    win.setProperty("activePanel", "chapters")
    win.openReader()
    QTimer.singleShot(100, lambda: wait_until(
        lambda: find_reader() is not None and abs(float(find_reader().property("opacity")) - 1.0) < 0.01,
        5000, step2_check_open))


def step2_check_open():
    r = find_reader()
    val = float(r.property("opacity"))
    check("打开后 opacity==1", abs(val - 1.0) < 0.01)
    if abs(val - 1.0) >= 0.01:
        for _w in WARNINGS[-15:]:
            print("DIAG qml>", _w, flush=True)
        # 现场诊断：runner 上若动画未驱动，这里能看到真实卡值与可见性
        print(f"DIAG opacity={val} visible={r.property('visible')} "
              f"readers={len([c for c in r.findChildren(object) if True])} "
              f"motion={bool(r.property('visible'))}", flush=True)
        print(f"DIAG windowVisible={win.property('visibility') is not None} "
              f"winExpose={win.isExposed() if hasattr(win, 'isExposed') else 'n/a'}", flush=True)
    r.setProperty("drawerOpened", True)
    QTimer.singleShot(100, lambda: wait_until(
        lambda: any(getattr(c, "objectName", lambda: "")() == "" and "QQuickRectangle" in c.metaObject().className()
                    and float(c.property("width") or 0) == 300 and bool(c.property("visible"))
                    for c in r.findChildren(object)),
        5000, step3_drawer))


def step3_drawer():
    r = find_reader()
    drawer = None
    for c in r.findChildren(object):
        try:
            if c.objectName() == "" and "QQuickRectangle" in c.metaObject().className() \
               and float(c.property("width") or 0) == 300:
                drawer = c
                break
        except Exception:
            pass
    check("抽屉可见", drawer is not None and bool(drawer.property("visible")))
    r.setProperty("drawerOpened", False)
    r.close()          # 与「退出」按钮同路径
    QTimer.singleShot(100, lambda: wait_until(
        lambda: float(find_reader().property("opacity")) < 0.01,
        5000, step4_closed))


def step4_closed():
    r = find_reader()
    check("退出后 opacity==0", abs(float(r.property("opacity"))) < 0.01)
    check("退出后 visible==False", not bool(r.property("visible")))
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step0_wait_project)
_rc = app.exec()
_rc0 = (1 if getattr(check, 'failed', False) else 0)  # N-31：失败非零退码
# A-10 延伸（v4 复验）：结论已打印；先跑完 atexit（probe_guard 真 config 还原），再躲 Qt 静态析构 fastfail
import atexit as _ax
sys.stdout.flush(); sys.stderr.flush()  # os._exit 不冲缓冲：不 flush 结论行会被吃掉
_ax._run_exitfuncs()
os._exit(_rc0)
