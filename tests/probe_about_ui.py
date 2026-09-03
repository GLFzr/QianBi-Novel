# -*- coding: utf-8 -*-
"""「关于」页更新通道探针（#89 R3）

真 QML + 真 Bridge + 真配置文件（probe_guard 退出时还原），只把清单拉取换成假函数。
验的都是升级那天才会暴露的事：
① 开机自动检查默认关；关着时一次网络请求都不发，开着时才发并且要看得见；
② 手动检查发现新版时，SHA-256 与「前往下载」真的显示出来（清单字段别再空转）；
③ 网络失败不得被说成「已是最新版本」；
④ 写给用户看的「哪些目录不会被动」，路径要和 Bridge 给的一致，且没被挤出对话框。
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

import app.update_check as update_check            # noqa: E402
import app.ui.bridge as bridge_mod                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QML_MSG = []
results = []
toasts = []
BOGUS_URL = "http://127.0.0.1:9/latest.json"        # 端口 9 立刻拒连，失败路径可复现
FAKE_NEW = {"version": "99.0.0", "url": "https://example.invalid/release/99",
            "notes": "探针新版说明", "sha256": "a" * 64}
_orig_fetch = update_check.fetch_manifest


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
b.toast.connect(lambda lv, msg: toasts.append((lv, str(msg))))


def run_all():
    from app import config as cfg_mod

    dlg = find(win, "aboutDialog")
    check("找到 aboutDialog", dlg is not None)
    if dlg is None:
        return finish()

    orig_updates = dict(cfg_mod.load_config().get("updates") or {})
    cfg = cfg_mod.load_config()
    cfg.setdefault("updates", {})["manifest_url"] = BOGUS_URL
    cfg["updates"]["auto_check"] = False
    cfg_mod.save_config(cfg)

    dlg.open()
    pump(400)

    box = find(dlg, "autoCheckRow")
    check("「启动时检查更新」勾选框在页面上", box is not None)
    if box is not None:
        check("默认未勾选（开机不联网）", not bool(box.property("checked")))
    joined = "\n".join(texts(dlg))
    check("页面写明更新只覆盖程序目录", "更新只覆盖程序目录" in joined, joined[:120])
    check("书稿路径与 Bridge 一致", str(b.defaultBooksRoot()) in joined)
    check("配置路径与 Bridge 一致", str(b.dataDirPath()) in joined)

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

    # ③ 拉不到清单 ≠ 已是最新（不真连网：本机有代理环境变量，会走代理而非立拒）
    update_check.fetch_manifest = lambda url, timeout=10.0: None
    toasts.clear()
    b.checkForUpdates(True)
    pump(1500)
    check("清单拉不到时报「失败」而不是「已是最新」",
          any("检查更新失败" in m for _l, m in toasts)
          and not any("已是最新" in m for _l, m in toasts), str(toasts[:2]))

    # ② 有新版：版本号、SHA-256、前往下载都显示出来
    update_check.fetch_manifest = lambda url, timeout=10.0: dict(FAKE_NEW)
    toasts.clear()
    b.checkForUpdates(True)
    pump(1500)
    ts = texts(dlg)
    joined = "\n".join(ts)
    check("新版号显示出来", "99.0.0" in joined, joined[:140])
    check("清单里的 SHA-256 显示出来", FAKE_NEW["sha256"] in joined)
    check("按钮切换成前往下载", any("前往下载" in t for t in ts))

    # ① 自动检查：关着时一次请求都不发
    calls = []
    inner = update_check.fetch_manifest

    def spy(url, timeout=10.0):
        calls.append(url)
        return inner(url, timeout)

    update_check.fetch_manifest = spy
    b.checkForUpdates(False)
    pump(800)
    check("auto_check 关着时开机检查不发请求", not calls and b._update_worker is None,
          str(calls))

    b.setUpdateAutoCheck(True)
    pump(250)
    if box is not None:
        check("勾选框跟随配置回写", bool(box.property("checked")))
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        check("开关已落盘", '"auto_check": true' in f.read())
    toasts.clear()
    b.checkForUpdates(False)
    pump(1500)
    check("auto_check 开着时开机检查会拉一次清单", calls == [BOGUS_URL], str(calls))
    check("自动检查也有可见提示", any("发现新版本" in m for _l, m in toasts),
          str(toasts[:2]))

    cfg_mod.load_config()          # 触发迁移与最新值读取，再整体还原
    back = cfg_mod.load_config()
    back["updates"] = orig_updates or {"auto_check": False}
    cfg_mod.save_config(back)
    finish()


def finish(failed=False):
    update_check.fetch_manifest = _orig_fetch
    try:
        dlg = find(win, "aboutDialog")
        if dlg is not None:
            dlg.close()
    except Exception:      # noqa: BLE001
        pass
    print("=== 关于页更新通道探针 ===")
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
