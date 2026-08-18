# -*- coding: utf-8 -*-
"""StepGateBar 门机制 UI 探针：离屏加载 Main.qml，验证决策条挂载与信号联动（无需 API Key）"""
import os, sys, tempfile

# 隔离用户配置：测试不得写入 ~/.qianbi_novel（防书架被污染）
_FH = tempfile.mkdtemp(prefix="qbn_gate_fakehome_")
os.environ["USERPROFILE"] = _FH

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, os.getcwd())

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer, QElapsedTimer

app = QGuiApplication(sys.argv)

# ---- 造一个有内容的演示项目 ----
from app import project
from app.core import state as st, memory

tmp = tempfile.mkdtemp(prefix="qbn_gate_proj_")
proj = project.create_project(tmp, "门机制探针")
project.write_idea_info(proj, "悬疑脑洞", "番茄", "主角捡到能改命的笔记", 100)
prose = "# 第1章 雨夜入局\n\n" + ("雨点敲在窗棂上，他翻开那本笔记，写下了第一行字。" * 30)
titles = {1: "雨夜入局", 2: "摊牌", 3: "意外来客"}
for n in (1, 2, 3):
    path = project.get_chapter_path(proj, n, titles[n])
    project.write_file(path, prose.replace("第1章", f"第{n}章").replace("雨夜入局", titles[n]))
stt = st.load_state(proj)
stt["total_chapters"] = 60
stt["stage"] = st.STAGE_PROSE
st.save_state(proj, stt)

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
gate_bar = win.findChild(QQuickItem, "gateBar")
assert gate_bar is not None, "gateBar objectName not found"

def pump(ms=300):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        app.processEvents()

results = []
results.append(("初始 hidden", gate_bar.property("waiting") is False))

# ---- 模拟 G5L 门：信号 → showGate → waiting/visible ----
bridge.gateAsked.emit("G5L", 3, "第 3 章上下文就绪，即将开写草稿（目标 2800 字）。")
pump()
results.append(("G5L 后 waiting", gate_bar.property("waiting") is True))
results.append(("G5L 后 visible", gate_bar.property("visible") is True))

os.makedirs("tests_output", exist_ok=True)
screen = app.primaryScreen()
img = screen.grabWindow(win.winId()).toImage()
img.save(os.path.join("tests_output", "gate_g5l_bar.png"))
results.append(("截图 gate_g5l_bar.png", os.path.exists("tests_output/gate_g5l_bar.png")))

# G5L 是软门：不可回退
results.append(("G5L 不可回退", gate_bar.property("rollbackable") is False))

# ---- 换 G9 硬门：可回退 ----
bridge.gateAsked.emit("G9", 3, "第 3 章已定稿（3024 字）。下一步：进入第 4 章。")
pump()
results.append(("G9 后 waiting", gate_bar.property("waiting") is True))
results.append(("G9 可回退", gate_bar.property("rollbackable") is True))

# ---- 关键 QML 告警白名单检查：只允许历史存量无害告警 ----
# 基线告警（门机制改动前已存在，git diff 确认非本次引入）：
#  * Main.qml:67  StandardKey.Save 的 Qt 多键绑定提示
#  * Main.qml:827 / Pip:130 / Main:764  ToolTip.visible:hovered|containsMouse 惰性解析
#  * ReaderView:226-227 drawer 抽屉目录的惰性引用
#  * Main.qml:437  Unable to assign [undefined] to bool（存量惰性绑定）
mute = ("QML Layout", "QQuickText", "anchor", "cycle",
        "multiple key bindings", "hovered is not defined",
        "containsMouse", "drawer is not defined", "Unable to assign")
new_warns = [w for w in warns if not any(m in w for m in mute)]
if new_warns:
    print("QML warnings:", new_warns[:5])
results.append(("无新增 QML 告警", len(new_warns) == 0))

print("=== StepGateBar UI 探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)