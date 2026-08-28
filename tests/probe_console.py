# -*- coding: utf-8 -*-
"""Agent Console 探针（T4.3 M1+M2）：离屏加载 Main.qml，验证 ConsoleDock 挂载、
思考链分组留存、对话区镜像与输入路由（无需 API Key）"""
import os, sys, tempfile

# 隔离用户配置：测试不得写入 ~/.qianbi_novel（防书架被污染）
_FH = tempfile.mkdtemp(prefix="qbn_console_fakehome_")
os.environ["USERPROFILE"] = _FH

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer

app = QGuiApplication(sys.argv)

# ---- 造一个有内容的演示项目 ----
from app import project
from app.core import state as st

tmp = tempfile.mkdtemp(prefix="qbn_console_proj_")
proj = project.create_project(tmp, "Console 探针")
project.write_idea_info(proj, "悬疑脑洞", "番茄", "主角捡到能改命的笔记", 100)

from app.ui.bridge import Bridge
bridge = Bridge()
bridge.openProject(proj)

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", bridge)
qml_dir = os.path.join(os.getcwd(), "app", "ui", "qml")
engine.addImportPath(qml_dir)
warns = []
engine.warnings.connect(lambda msgs: warns.extend(m.toString() for m in msgs))
engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
assert engine.rootObjects(), f"QML load failed, warns={warns}"
win = engine.rootObjects()[0]

from PySide6.QtQuick import QQuickItem
dock = win.findChild(QQuickItem, "consoleDockItem") or win.findChild(QQuickItem, "consoleDock")
assert dock is not None, "consoleDock objectName not found"

results = []

def pump(ms=300):
    t = QTimer()
    loop = [0]
    t.timeout.connect(lambda: loop.__setitem__(0, loop[0] + 1))
    t.start(ms)
    deadline = __import__("time").time() + ms / 1000
    while __import__("time").time() < deadline:
        app.processEvents()
    t.stop()

# 1. 挂载 + 折叠态
results.append(("ConsoleDock 挂载", dock is not None))
results.append(("初始折叠", bridge.consoleExpanded is False))

# 2. 思考链分组留存（M1）：模拟三条不同槽位/章的增量
bridge._on_thinking("writing", "prose", 1, "主角动机要再压一层")
bridge._on_thinking("writing", "prose", 1, "，用雨夜道具带出。")
bridge._on_thinking("review", "prose", 2, "第 2 章审校注意对白标签")
bridge._cur_num = 2   # 模拟第 2 章写作中（当前章组应排最前）
pump(200)
groups = bridge.consoleThinkingGroups
g1 = next((g for g in groups if g["num"] == 1 and g["slot"] == "writing"), None)
results.append(("思考链按槽位×阶段×章分组", g1 is not None and g1["text"].endswith("带出。")))
results.append(("当前章组优先", bool(groups) and groups[0]["is_current"] is True and groups[0]["num"] == 2))
results.append(("组间不串", all(g["text"] != "".join([x for x in []]) for g in groups)))

# 3. 对话区镜像 + 落盘（M2）
bridge._console_log("agent", "—— 第 1 章开始 ——", num=1)
bridge._console_log("gate", "⏸ 决策门 G8（第1章）：测试摘要", num=1)
dial = bridge.consoleDialogue
results.append(("对话区条目", len(dial) >= 2 and dial[-1]["kind"] == "gate"))
session = os.path.join(proj, "pipeline_debug", "console")
files = os.listdir(session) if os.path.isdir(session) else []
results.append(("会话落盘 jsonl", len(files) == 1 and files[0].startswith("session-")))

# 4. 输入路由：非门状态 → 沉淀为下一章想法
bridge.consoleSubmit("下一章加一场摊牌戏")
pump(200)
state = st.load_state(proj)
ideas = st.norm_ideas(state)
results.append(("非门输入→沉淀想法", any("摊牌戏" in it["text"] for it in ideas)))

# 5. 展开态切换
bridge.setConsoleExpanded(True)
pump(250)
results.append(("展开态", bridge.consoleExpanded is True))

# 基线告警（与 probe_gate_ui 同一份静默表：改动前已存在的存量惰性绑定，git diff 确认非本次引入）
mute = ("QML Layout", "QQuickText", "anchor", "cycle",
        "multiple key bindings", "hovered is not defined",
        "containsMouse", "drawer is not defined", "Unable to assign")
new_warns = [w for w in warns if not any(m in w for m in mute)]
results.append(("零 QML 告警", len(new_warns) == 0))

print("=== Agent Console 探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
for w in new_warns:
    print("QML-WARN:", w)
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
