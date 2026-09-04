# -*- coding: utf-8 -*-
"""连接卡片的删除与退役清理（v0.18.1）

真 Bridge + 真 QML 设置页；凭据被 `probe_guard` 换成进程内字典——这个探针既要证明
「Key 跟着连接一起没了」，又要保证没碰到用户真凭据，不隔离就根本没法测。

盯的四件都会伤到人：
① `secrets.delete_secret` 原先定义了却零调用 → 每删一张卡就在凭据管理器里留一个孤儿 Key；
② 那是不可恢复的操作 → 按钮必须两步确认，且换一张卡时确认要自动解除；
③ 只剩一条连接不许删；
④ 自动清退役出厂行时，**填过 Key 的、被槽位用着的、被用户改过的**一律不许动。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard      # noqa: E402

arm_config_guard()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl               # noqa: E402
from PySide6.QtGui import QGuiApplication     # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from app import config as cfg_mod             # noqa: E402
from app import secrets                       # noqa: E402
from app.ui.bridge import Bridge              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "sk-probe-secret-0123456789"
results = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))


def pump(ms=250):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


def find(root, name):
    if root.objectName() == name:
        return root
    for c in root.children():
        got = find(c, name)
        if got is not None:
            return got
    return None


def disk():
    with open(cfg_mod.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


app = QGuiApplication.instance() or QGuiApplication([])
b = Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", b)
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
win = engine.rootObjects()[0]
win.setProperty("activePanel", "settings")
pump(600)

panel = find(win, "settingsPanel")
btn = find(win, "deleteConnButton")
check("设置面板与删除按钮都在位", panel is not None and btn is not None)
if panel is None or btn is None:
    print("FAIL 找不到控件，后面全部跳过")
    print("TOTAL 0 / 1")
    sys.exit(1)

# ---------- ① 存一条带 Key 的连接 ----------
b.saveConnection({"id": "", "name": "探针连接", "provider": "custom",
                  "base_url": "https://probe.invalid/v1", "api_key": KEY,
                  "model": "probe-model", "temperature": 0.7,
                  "max_tokens": 4096, "timeout": 60})
pump(300)
row = next((c for c in disk()["connections"] if c.get("name") == "探针连接"), None)
check("新连接已落盘", row is not None)
pid = (row or {}).get("id") or ""
check("明文 Key 不留在 config.json 里",
      (row or {}).get("api_key", "") == "" and (row or {}).get("key_ref") == "keyring",
      str(row)[:110])
check("Key 进了凭据存储（沙箱）", secrets.get_secret(pid) == KEY, pid)

# ---------- ② 两步确认 ----------
panel.setProperty("isNew", False)
panel.setProperty("editingId", pid)
pump(200)
check("选中一条连接后删除按钮可用", bool(btn.property("enabled")) is True)
check("默认文案只是「删除」", str(btn.property("text")) == "删除", str(btn.property("text")))

btn.clicked.emit()          # 第一次：只问确认
pump(200)
check("第一次点击不删连接",
      any(c.get("id") == pid for c in disk()["connections"]))
check("第一次点击不碰 Key", secrets.get_secret(pid) == KEY)
check("按钮改口要第二次确认", "确认删除" in str(btn.property("text")), str(btn.property("text")))

panel.setProperty("editingId", "ds-v4-pro")   # 换一张卡
pump(150)
check("换连接会把确认状态解除", bool(panel.property("armedDelete")) is False)
check("解除后文案回到「删除」", str(btn.property("text")) == "删除", str(btn.property("text")))

panel.setProperty("editingId", pid)
pump(150)
btn.clicked.emit()
btn.clicked.emit()          # 第二次：真删
pump(300)
after = disk()
check("第二次点击后连接消失", all(c.get("id") != pid for c in after["connections"]))
check("它的 Key 一起消失（不留孤儿凭据）", secrets.get_secret(pid) == "",
      str(sorted(secrets._VAULT))[:110])
check("槽位没有指向被删的连接",
      all(v != pid for v in (after.get("slots") or {}).values()), str(after.get("slots")))

# ---------- ③ 只剩一条不许删 ----------
only = {"connections": [json.loads(json.dumps(cfg_mod.DEFAULT_CONNECTIONS[0]))],
        "slots": {s: cfg_mod.DEFAULT_CONNECTIONS[0]["id"] for s in cfg_mod.SLOT_ORDER}}
b.cfg.clear()
b.cfg.update(only)
b.deleteConnection(cfg_mod.DEFAULT_CONNECTIONS[0]["id"])
check("只剩一条时拒绝删除", len(b.cfg.get("connections") or []) == 1)

# ---------- ④ 退役出厂行的三条护栏（走真 save/load）----------
FACTORY = {"id": "ds-v4-flash", "name": "DeepSeek V4 Flash", "provider": "deepseek",
           "base_url": "https://api.deepseek.com", "api_key": "", "model": "deepseek-v4-flash",
           "temperature": 0.7, "max_tokens": 16384, "timeout": 300}
PRO = json.loads(json.dumps(cfg_mod.DEFAULT_CONNECTIONS[0]))


def seed(rows, slots=None):
    cfg_mod._RETIRED_WITH_KEY.clear()       # 否则上一条结论会串到这一条
    cfg = {"connections": json.loads(json.dumps(rows)),
           "slots": slots or {s: PRO["id"] for s in cfg_mod.SLOT_ORDER},
           "updates": {"auto_check": False}}
    cfg_mod.save_config(cfg)
    return cfg_mod.load_config()


def has(out, cid):
    return any(c["id"] == cid for c in out["connections"])


base_rows = [dict(PRO), dict(FACTORY)]
check("没 Key、没被引用的出厂遗留行会被清掉", not has(seed(base_rows), "ds-v4-flash"))

seed(base_rows)
secrets.store_secret("ds-v4-flash", KEY)
check("填过 Key 的出厂行不许删（删了 Key 就成孤儿）",
      has(seed(base_rows), "ds-v4-flash"))
secrets.delete_secret("ds-v4-flash")

used = {"writing": "ds-v4-flash", "helper": PRO["id"], "review": PRO["id"]}
check("被槽位用着的出厂行不许删", has(seed(base_rows, used), "ds-v4-flash"))

check("用户改过模型名的行不算出厂遗留",
      has(seed([dict(PRO), dict(FACTORY, model="deepseek-v4-flash-0731")]), "ds-v4-flash"))

check("删干净后出厂 12 家照样补齐回来",
      len({c["id"] for c in seed([dict(PRO)])["connections"]}
          & {c["id"] for c in cfg_mod.DEFAULT_CONNECTIONS}) == len(cfg_mod.DEFAULT_CONNECTIONS))

fails = [r for r in results if not r[1]]
for name, ok, extra in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" | " + extra) if extra else ""))
print("TOTAL %d / %d" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
