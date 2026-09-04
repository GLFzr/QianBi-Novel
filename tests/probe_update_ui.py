# -*- coding: utf-8 -*-
"""更新面板探针（v0.18 更新链路）

真 QML + 真 Bridge（probe_guard 退出时还原配置并把 updates/ 缓存隔离到临时目录），
只把 `update_check.fetch_text` 换成假的取字节函数——那是整条链上唯一的网络咽喉。

盯的都是「升级那天才会暴露」的事：
① 连不上 ≠ 已最新，且每条通道的死法要列给用户看（否则他不知道该配代理还是走离线）；
② **未验签的清单不许产生任何可执行按钮**——Python 层已有门，这里在 UI 层再钉一次；
③ 一键安装要同时满足「验签通过 + 安装版」，源码态跑探针时那个按钮就不该出现；
④ 自动检查的开关、限流与落盘；
⑤ 离线导入清单 + 本机安装包对账（连不上 GitHub 的那条活路）。
"""
import base64
import hashlib
import json
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

import app.update_check as uc                      # noqa: E402
import app.ui.bridge as bridge_mod                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []
toasts = []
requests = []            # 假 fetch_text 记的 (url, 是否带代理)
NEW_VERSION = "99.0.0"
PKG_SHA = hashlib.sha256(b"probe-installer-bytes").hexdigest()
BASE = {"version": NEW_VERSION, "url": "https://example.invalid/release/99",
        "notes": "探针新版说明", "sha256": PKG_SHA,
        "assets": {"setup": {"name": "QianBi-Novel-v99-setup.exe",
                             "url": "https://example.invalid/dl/setup.exe",
                             "sha256": PKG_SHA, "size": 4096}}}
_ORIG_FETCH = uc.fetch_text
_ORIG_UPDATES = {}
PRIV = None
PUBKEYS = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))


def pump(ms=250):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


def find(root, name):
    """Dialog 的根是 QQuickPopup，不是 QQuickItem：只能递归走 children()"""
    if root.objectName() == name:
        return root
    for c in root.children():
        got = find(c, name)
        if got is not None:
            return got
    return None


def visible_items(root):
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


def overflow(root):
    ci = root.property("contentItem")
    if not isinstance(ci, QQuickItem):
        return []
    bound = ci.width()
    over = []
    for it in visible_items(root):
        if it is ci:
            continue
        x = it.mapToItem(ci, QPointF(0, 0)).x()
        if x + it.width() > bound + 1.5:
            over.append("%s %.0f+%.0f>%.0f" % (it.metaObject().className(), x, it.width(), bound))
    return over


def signed_manifest(**over):
    body = dict(BASE)
    body.update(over)
    body["sig"] = base64.b64encode(PRIV.sign(uc.canonical_bytes(body))).decode()
    return body


def stub(**by_channel):
    """按 URL 里的特征字决定回什么；没列出的通道一律「连接失败」"""
    def fake(url, plan, timeout=uc.TIMEOUT):
        requests.append((url, bool(plan.proxy)))
        for key, payload in by_channel.items():
            if key in url:
                text = payload if isinstance(payload, str) else json.dumps(payload)
                return (text, "")
        return ("", "连接失败（探针设定）")
    uc.fetch_text = fake


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


def make_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    global PRIV, PUBKEYS
    PRIV = Ed25519PrivateKey.generate()
    PUBKEYS = [{"kid": "probe", "pub": base64.b64encode(
        PRIV.public_key().public_bytes_raw()).decode()}]


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
    global _ORIG_UPDATES
    _ORIG_UPDATES = dict(cfg_mod.load_config().get("updates") or {})
    make_key()
    uc.PUBKEYS = PUBKEYS
    uc.offline = lambda: False          # 本探针要测「该发请求时确实发了」
    b._update_result = None

    def reset(**kv):
        cfg = cfg_mod.load_config()
        base = dict(_ORIG_UPDATES, auto_check=False, last_channel="",
                    last_check_ts=0.0, dismissed_version="",
                    proxy_mode="none", proxy_url="", custom_url="")
        base.update(kv)
        cfg["updates"] = base
        cfg_mod.save_config(cfg)
        b.updateStateChanged.emit()     # 直接写盘的改动不会自己广播，QML 得重算

    dlg = find(win, "updateDialog")
    check("找到 updateDialog", dlg is not None)
    if dlg is None:
        return finish()
    main_qml = open(os.path.join(ROOT, "app", "ui", "qml", "Main.qml"), encoding="utf-8").read()
    check("左栏常驻更新图标已接线", 'name: "update"' in main_qml
          and "bridge.updateAvailable" in main_qml)
    reset()
    dlg.open()
    pump(400)

    # ---- ① 三条通道全失败 ----
    requests.clear()
    stub()
    toasts.clear()
    b.checkForUpdates(True)
    pump(1500)
    joined = "\n".join(texts(dlg))
    check("三条 GitHub 通道都试过", len(requests) >= 3, str([u for u, _ in requests]))
    check("状态徽标是「没查到」", "没查到" in joined, joined[:200])
    check("逐条通道列出死法", all(k in joined for k in ("GitHub raw", "GitHub Pages", "jsDelivr")),
          joined[:260])
    check("失败不说成已最新",
          any("检查更新失败" in m for _l, m in toasts) and not any("已是最新" in m for _l, m in toasts),
          str(toasts[:2]))
    check("没查到东西时不给任何安装按钮",
          not any("下载并校验" in t or "立即安装" in t for t in texts(dlg)))

    # ---- ② 有新版但未验签 ----
    requests.clear()
    stub(jsdelivr=json.dumps(BASE))
    toasts.clear()
    b.checkForUpdates(True)
    pump(1500)
    st = b.updateState
    ts = texts(dlg)
    check("回退到第三条通道并认出来", st.get("channel") == "jsdelivr", str(st.get("channel")))
    check("新版号显示出来", any(NEW_VERSION in t for t in ts))
    check("清单里的 SHA-256 显示出来", any(PKG_SHA in t for t in ts))
    check("标了未验签", any("未验签" in t or "未签名" in t for t in ts), "\n".join(ts)[:220])
    check("未验签时没有下载按钮", not any("下载并校验" in t for t in ts))
    check("未验签时 canInstall 为假", st.get("canInstall") is False, str(st.get("whyNotInstall")))
    check("自动检查也有可见提示", any("发现新版本" in m for _l, m in toasts), str(toasts[:2]))

    # ---- ③ 验签通过，但跑的是源码态 ----
    reset()
    stub(raw=signed_manifest())
    b.checkForUpdates(True)
    pump(1500)
    st = b.updateState
    check("验签通过", st.get("verified") is True, str(st.get("verifyReason")))
    check("源码态下安装门是关的", st.get("canInstall") is False
          and st.get("installMode") == "dev", str(st.get("installMode")))
    check("说清了为什么不能一键", "便携版" in str(st.get("whyNotInstall")),
          str(st.get("whyNotInstall")))
    check("不能一键时也没有下载按钮", not any("下载并校验" in t for t in texts(dlg)))

    # ---- ④ 假装是安装版：门开了按钮才出现 ----
    uc.install_mode = lambda: "installed"
    reset()
    stub(raw=signed_manifest())
    b.checkForUpdates(True)
    pump(1500)
    st = b.updateState
    check("安装版 + 验签 → 允许一键", st.get("canInstall") is True, str(st.get("whyNotInstall")))
    check("出现下载并校验按钮", any("下载并校验" in t for t in texts(dlg)))

    # ---- ⑤ 本机安装包对账 ----
    exe = os.path.join(b.updateDownloadPath(), "QianBi-Novel-v99-setup.exe")
    with open(exe, "wb") as f:
        f.write(b"probe-installer-bytes")
    out = b.checkLocalPackage(QUrl.fromLocalFile(exe).toString())
    check("本机包 SHA-256 命中", out.get("ok") is True, str(out.get("reason")))
    check("命中后给出立即安装按钮", any("立即安装" in t for t in texts(dlg)))
    bad = os.path.join(b.updateDownloadPath(), "tampered.exe")
    with open(bad, "wb") as f:
        f.write(b"tampered")
    out2 = b.checkLocalPackage(QUrl.fromLocalFile(bad).toString())
    check("改动过的包被拒", out2.get("ok") is False and "不一致" in str(out2.get("reason")),
          str(out2.get("reason")))
    # 哈希对上了但清单没验签 → 依然不许装（把门拆一半，看另一半年不拦）
    flag = b._update_result.verified
    b._update_result.verified = False
    out3 = b.checkLocalPackage(QUrl.fromLocalFile(exe).toString())
    check("未验签清单不许为本地包背书",
          out3.get("ok") is False and "验签" in str(out3.get("reason")), str(out3.get("reason")))
    b._update_result.verified = flag
    out4 = b.checkLocalPackage(QUrl.fromLocalFile(exe).toString())
    check("恢复验签后同一文件重新被接受", out4.get("ok") is True, str(out4.get("reason")))

    # 两步确认：第一次点只把「确认」问出来，绝不直接退出
    armed_texts = [t for t in texts(dlg) if "立即安装" in t or "确认退出并安装" in t]
    check("安装是两步确认", any("立即安装" in t for t in armed_texts)
          and not any("确认退出并安装" in t for t in armed_texts), str(armed_texts[:2]))

    # ---- ⑥ 限流、开关与白名单 ----
    reset(auto_check=True)
    requests.clear()
    b.checkForUpdates(False)
    pump(1200)
    first = len(requests)
    b.checkForUpdates(False)
    pump(600)
    check("24h 限流让第二次开机检查闭嘴", first >= 1 and len(requests) == first,
          "%d → %d" % (first, len(requests)))
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        disk = json.load(f).get("updates") or {}
    check("检查时间戳已落盘", float(disk.get("last_check_ts") or 0) > 0, str(disk)[:120])
    check("成功通道已记住", disk.get("last_channel") == "raw", str(disk.get("last_channel")))

    b.setUpdateSettings(json.dumps({"auto_check": False}))
    pump(300)
    b.checkForUpdates(False)
    pump(600)
    check("关掉开关后开机检查不再发请求", len(requests) == first, "%d" % len(requests))
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        disk = json.load(f).get("updates") or {}
    check("显式表过态，迁移不许再翻它", disk.get("auto_check_chosen") is True, str(disk)[:160])

    # 「这一版起默认开着」的告知：只在「开着、但不是用户自己开的」时出现
    reset(auto_check=True, auto_check_chosen=False)
    pump(300)
    check("默认翻开的自动检查会主动说明", "默认是开的" in "\n".join(texts(dlg)))
    reset(auto_check=True, auto_check_chosen=True)
    pump(300)
    check("用户自己开的就不再教育一遍", "默认是开的" not in "\n".join(texts(dlg)))
    reset(auto_check=False, auto_check_chosen=True)
    pump(300)
    check("关掉之后也不再提", "默认是开的" not in "\n".join(texts(dlg)))

    # 检查间隔：面板里有控件，且边界由 Python 侧兜（QML 传什么是外部输入）
    check("面板里有「检查间隔」可选", find(dlg, "intervalSelect") is not None)
    check("关掉自动检查时不再问间隔",
          "检查间隔" not in "\n".join(texts(dlg)))
    reset(auto_check=True, auto_check_chosen=True)
    pump(300)
    check("开着自动检查时间隔就在面板上", "检查间隔" in "\n".join(texts(dlg)))
    b.setUpdateSettings(json.dumps({"interval_hours": 0}))
    pump(300)
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        disk = json.load(f).get("updates") or {}
    check("间隔写 0 会被抬到下限而不是绕开限流",
          float(disk.get("interval_hours") or 0) >= 0.5, str(disk.get("interval_hours")))
    b.setUpdateSettings(json.dumps({"interval_hours": 999999}))
    pump(300)
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        disk = json.load(f).get("updates") or {}
    check("间隔有上限（不许设成事实上永不检查）",
          float(disk.get("interval_hours") or 0) <= 720, str(disk.get("interval_hours")))
    b.setUpdateSettings(json.dumps({"interval_hours": "乱七八糟"}))
    pump(300)
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        disk = json.load(f).get("updates") or {}
    check("读不懂的间隔退回 24 小时",
          float(disk.get("interval_hours") or 0) == 24.0, str(disk.get("interval_hours")))

    b.setUpdateSettings(json.dumps({"connections": [{"id": "evil"}],
                                    "custom_url": "https://m.example/x.json"}))
    pump(300)
    with open(os.path.join(b.dataDirPath(), "config.json"), encoding="utf-8") as f:
        whole = json.load(f)
    check("白名单挡住越界键", all(c.get("id") != "evil" for c in whole.get("connections") or []))
    check("白名单内的键照常写",
          b.updateState["settings"]["customUrl"] == "https://m.example/x.json")

    # ---- ⑦ 离线导入 ----
    reset()
    offline_file = os.path.join(b.updateDownloadPath(), "latest.json")
    with open(offline_file, "w", encoding="utf-8") as f:
        json.dump(signed_manifest(notes="离线导入的清单"), f, ensure_ascii=False)
    imp = b.importManifestFile(QUrl.fromLocalFile(offline_file).toString())
    check("离线清单导入成功且验签通过",
          imp.get("ok") is True and imp.get("verified") is True, str(imp.get("reason")))
    check("导入的清单标成 file 通道", b.updateState["channel"] == "file")
    with open(offline_file, "w", encoding="utf-8") as f:
        f.write("{ not json")
    imp2 = b.importManifestFile(QUrl.fromLocalFile(offline_file).toString())
    check("读不懂的清单报原因而不是崩",
          imp2.get("ok") is False and "JSON" in str(imp2.get("reason")), str(imp2.get("reason")))

    # ---- ⑧ 布局 ----
    pump(300)
    over = overflow(dlg)
    check("无元素溢出面板宽度", not over, "; ".join(over[:3]))

    reset()
    finish()


def finish(failed=False):
    uc.fetch_text = _ORIG_FETCH
    try:
        from app import config as cfg_mod
        cfg = cfg_mod.load_config()
        cfg["updates"] = _ORIG_UPDATES or {"auto_check": False}
        cfg_mod.save_config(cfg)
    except Exception:      # noqa: BLE001
        pass
    print("=== 更新面板探针 ===")
    if failed:
        print("ABORTED：探针中途抛异常，下面的结果不是全部检查")
    ok = not failed
    for name, passed, extra in results:
        print(("PASS" if passed else "FAIL"), name, ("| " + extra) if extra else "")
        ok = ok and passed
    print("TOTAL", f"{sum(1 for _n, p, _e in results if p)} / {len(results)}")
    sys.exit(0 if ok else 1)


QTimer.singleShot(700, guard(run_all))
app.exec()
