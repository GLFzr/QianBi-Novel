# -*- coding: utf-8 -*-
"""「关于」页探针（#89 R3 收窄版）

真 QML + 真 Bridge + 真配置文件（probe_guard 退出时还原）。
更新链路的通道/验签/离线出路全部搬去 probe_update_ui.py，这里只验「关于」页自己
该说对的话：哪些目录不会被升级动到，路径要和 Bridge 给的一致，且没被挤出对话框。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard      # noqa: E402

arm_config_guard()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QPointF, QUrl, QTimer   # noqa: E402
from PySide6.QtGui import QGuiApplication          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine    # noqa: E402
from PySide6.QtQuick import QQuickItem             # noqa: E402

import app.ui.bridge as bridge_mod                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QML_MSG = []
results = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))


def pump(ms=250):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


def find(root, name):
    """Dialog 的根是 QQuickPopup（不是 QQuickItem），只能递归走 children()"""
    if root.objectName() == name:
        return root
    for c in root.children():
        got = find(c, name)
        if got is not None:
            return got
    return None


def visible_items(root):
    """Dialog 的根是 QQuickPopup（不是 QQuickItem），得先进 contentItem 才有视觉树"""
    start = root if isinstance(root, QQuickItem) else root.property("contentItem")
    out = []

    def rec(it):
        if not isinstance(it, QQuickItem) or not it.isVisible():
            return
        out.append(it)
        for c in it.childItems():
            rec(c)
    if start is not None:
        rec(start)
    return out


def texts(root):
    return [str(v) for v in (it.property("text") for it in visible_items(root)) if v]


def guard(fn):
    def wrapped():
        try:
            fn()
        except Exception:      # noqa: BLE001
            # 只吞 Exception：sys.exit() 抛的 SystemExit 必须穿透，
            # 否则全绿的一轮会被当成崩溃并以非零码退出
            import traceback
            traceback.print_exc()
            finish(failed=True)
    return wrapped


app = QGuiApplication(sys.argv[:1])
b = bridge_mod.Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", b)
engine.addImportPath(os.path.join(ROOT, "app", "ui", "qml"))
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
assert engine.rootObjects(), "Main.qml 加载失败"
win = engine.rootObjects()[0]


def run_all():
    dlg = find(win, "aboutDialog")
    check("找到 aboutDialog", dlg is not None)
    if dlg is None:
        return finish()

    dlg.open()
    pump(400)

    joined = "\n".join(texts(dlg))
    check("页面写明更新只覆盖程序目录", "更新只覆盖程序目录" in joined, joined[:120])
    check("书稿路径与 Bridge 一致", str(b.defaultBooksRoot()) in joined)
    check("配置路径与 Bridge 一致", str(b.dataDirPath()) in joined)
    check("关于页不再自带更新勾选框（设置只有一处真相）",
          find(dlg, "autoCheckRow") is None)

    # 「更新…」入口必须真的能把面板叫出来：断链的症状是按钮点了没反应，
    # 而 Python 侧一切正常
    panel = find(win, "updateDialog")
    check("找到 updateDialog", panel is not None)
    btn = find(dlg, "openUpdateDialog")
    check("关于页有「更新…」入口", btn is not None)
    if btn is not None and panel is not None:
        was = bool(panel.property("visible"))
        try:
            btn.clicked.emit()
        except Exception as e:  # noqa: BLE001
            check("入口按钮可触发", False, repr(e))
        pump(400)
        check("点入口后更新面板打开、关于页收起",
              bool(panel.property("visible")) and not was and not bool(dlg.property("visible")),
              "panel=%s about=%s" % (panel.property("visible"), dlg.property("visible")))

    ci = dlg.property("contentItem")
    bound = float(ci.width()) if isinstance(ci, QQuickItem) else 460.0
    over = []
    for it in visible_items(dlg):
        if it is ci:
            continue
        x = it.mapToItem(ci, QPointF(0, 0)).x()
        if x + it.width() > bound + 1.5:
            over.append("%s %.0f+%.0f>%.0f" % (it.metaObject().className(),
                                               x, it.width(), bound))
    check("无元素溢出对话框宽度", not over, "; ".join(over[:3]))
    finish()


def finish(failed=False):
    for name in ("updateDialog", "aboutDialog"):
        obj = find(win, name)
        try:
            if obj is not None:
                obj.close()
        except Exception:      # noqa: BLE001
            pass
    print("=== 关于页探针 ===")
    if failed:
        print("ABORTED：探针中途抛异常，下面的结果不是全部检查")
    for m in [x for x in QML_MSG if "About" in x][:8]:
        print("QML-MSG:", m[:240])
    ok = not failed
    for name, passed, extra in results:
        print(("PASS" if passed else "FAIL"), name, ("| " + extra) if extra else "")
        ok = ok and passed
    print("TOTAL", f"{sum(1 for _n, p, _e in results if p)} / {len(results)}")
    sys.exit(0 if ok else 1)


QTimer.singleShot(700, guard(run_all))
app.exec()
