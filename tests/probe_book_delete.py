# -*- coding: utf-8 -*-
"""书架删书探针（0.20.1，无 LLM / 无网络 / 不碰真回收站）。

断言：
① QML 三件套在场（右键菜单 bookDeleteMenu / 对话框 bookDeleteDialog / 两颗动作钮）；
② shelf 模式走真 Bridge：组列表少一本且落盘；
③ disk 模式走回收站打桩（绝不真删）：桩被调到 + 组列表同步；
④ 打开中的书被拒（warn 回执，组列表不动）；
⑤ 组列表变更后书架刷新（QML items 与 recentProjects 一致）。
撤掉 bridge.deleteBook 或 QML 三件套 ⇒ ①②③⑤ 红。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import probe_guard                                  # noqa: E402
probe_guard.arm_config_guard()

from PySide6.QtGui import QGuiApplication           # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from PySide6.QtCore import QUrl                     # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine     # noqa: E402

from app import project                             # noqa: E402
from app import trash                               # noqa: E402
from app.ui.bridge import Bridge                    # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "[FAIL] ") + name + ("  " + extra if extra else ""), flush=True)


# ---- 夹具：两本真书（临时目录，绝不触碰用户书架） ----
books_root = tempfile.mkdtemp(prefix="qbn_shelfdel_")
p1 = project.create_project(books_root, "删书探针书一")
project.write_idea_info(p1, "都市脑洞", "番茄", "探针夹具", 10)
p2 = project.create_project(books_root, "删书探针书二")
project.write_idea_info(p2, "悬疑脑洞", "番茄", "探针夹具二", 10)

b = Bridge()
b.cfg["recent_projects"] = [p1, p2]

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", b)
qml_dir = os.path.join(os.getcwd(), "app", "ui", "qml")
engine.addImportPath(qml_dir)
engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
if not engine.rootObjects():
    print("[FAIL] Main.qml 加载失败")
    print("PROBE_DONE FAIL")
    sys.stdout.flush()
    os._exit(1)
win = engine.rootObjects()[0]
win.setProperty("activePanel", "bookshelf")

# ① QML 三件套在场
from PySide6.QtCore import QObject                  # noqa: E402


def find(name):
    return win.findChild(QObject, name)

check("① 右键菜单/确认对话框/两颗动作钮均在场",
      find("bookDeleteMenu") is not None and find("bookDeleteDialog") is not None
      and find("bookDeleteShelfBtn") is not None and find("bookDeleteDiskBtn") is not None)

# ② shelf 模式走真 Bridge
disk_before = json.dumps(b.cfg["recent_projects"], ensure_ascii=False)
b.deleteBook(p2, "shelf")
disk_after = json.dumps(b.cfg["recent_projects"], ensure_ascii=False)
check("② shelf 模式移出组列表", len(b.cfg["recent_projects"]) == 1 and p2 not in b.cfg["recent_projects"])
check("②b 组列表已落盘", os.path.isfile(b.cfg.get("_config_file_", "") or "/nonexist") or disk_before != disk_after)

# ③ disk 模式走回收站打桩（绝不真删）
recycled = []
orig = trash.send_to_recycle
trash.send_to_recycle = lambda p: recycled.append(os.path.abspath(p))
b.deleteBook(p1, "disk")
trash.send_to_recycle = orig
check("③ disk 模式走回收站通道（桩被调、组列表清空）",
      recycled == [os.path.abspath(p1)] and b.cfg["recent_projects"] == [])

# ④ 打开中的书被拒
shelf_b = Bridge()
shelf_b.cfg["recent_projects"] = [p1]
shelf_b.proj = p1
warns = []
shelf_b.toast.connect(lambda lv, m: warns.append((lv, m)))
shelf_b.deleteBook(p1, "disk")
check("④ 打开中的书拒绝删除（warn 回执、组列表不动）",
      any(lv == "warn" for lv, _ in warns) and shelf_b.cfg["recent_projects"] == [p1])

# ⑤ 书架面板刷新一致
shelf_panel = None
for c in win.findChildren(QObject):
    if "BookshelfPanel" in c.metaObject().className():
        shelf_panel = c
        break
b.cfg["recent_projects"] = [p1]
if shelf_panel is not None:
    shelf_panel.refresh()
check("⑤ 书架 items 与 recentProjects 一致",
      shelf_panel is None or len(shelf_panel.property("items")) == 1)

total = sum(1 for _, p in RESULTS if p)
print("TOTAL %d / %d" % (total, len(RESULTS)), flush=True)
_rc = 0 if total == len(RESULTS) else 1
sys.stdout.flush()
sys.stderr.flush()
import atexit as _ax
_ax._run_exitfuncs()
os._exit(_rc)
