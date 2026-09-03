# -*- coding: utf-8 -*-
"""「本书契约」面板探针（#10）：看得见的规则，改得动的规则

真 QML 面板 + 真 Bridge + 真文件，零 LLM 调用。校验三件容易做歪的事：
① 面板在导航里可达且索引对得上；
② 改/删一条只动它自己那几行，其余条目与标题原样保留；
③ 删除要二次确认（不是一点就没）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard

arm_config_guard()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem

from app import project
from app.ui.bridge import Bridge

QML_MSG = []

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = """## 正则（逻辑约束规则集）

- 规则：突破必须有资源代价｜level：must｜scope：修炼
- 规则：不得出现口水词：`仿佛|似乎`｜level：should｜scope：全书
- 规则：现代货币不得入文：`￥\\d+`｜level：must｜scope：全书
"""

app = QGuiApplication(sys.argv)
qInstallMessageHandler(lambda m, c, msg: QML_MSG.append(msg))
TMP = tempfile.mkdtemp(prefix="qbn_contract_")
PROJ = project.create_project(TMP, "契约面板探针书")
project.write_file(os.path.join(PROJ, project.REGEX_PATH), DOC)

b = Bridge()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bridge", b)
engine.addImportPath(os.path.join(ROOT, "app", "ui", "qml"))
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "app", "ui", "qml", "Main.qml")))
assert engine.rootObjects(), "Main.qml 加载失败"
win = engine.rootObjects()[0]
b._open_project(PROJ, silent=True)

results = []


def check(name, ok):
    results.append((name, bool(ok)))


def pump(ms=200):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


def panel():
    it = win.findChild(QQuickItem, "contractPanel")
    assert it is not None, "找不到 contractPanel"
    return it


def walk(item):
    """递归走 QML 的**视觉树**（childItems）

    item view 的 delegate 只挂 contentItem 作视觉父级，QObject 父级在视图之外，
    所以 findChildren 找不到任何一条规则卡——用 findChildren 会永远数为 0。
    """
    for c in item.childItems():
        yield c
        yield from walk(c)


def rendered_text():
    lv = win.findChild(QQuickItem, "contractRuleList")
    if lv is None:
        return []
    return [str(c.property("text")) for c in walk(lv) if c.property("text")]


def step1():
    check("导航含契约项且后续面板顺移",
          win.panelIndexOf("contract") == 3
          and win.panelIndexOf("notes") == 4
          and win.panelIndexOf("settings") == 6)
    win.setProperty("activePanel", "contract")
    pump(300)
    check("面板可见", bool(panel().property("visible")))
    check("QML 侧收到 3 条", int(panel().property("ruleCount")) == 3)
    check("must 计数正确", int(panel().property("mustCount")) == 2)
    txt = rendered_text()
    check("3 条规则都渲染出来了",
          sum(1 for t in txt if t.startswith("规则：")) == 3)
    check("must/should 徽章渲染", txt.count("must") >= 2 and "should" in txt)
    check("判定式可见", any("`仿佛|似乎`" in t for t in txt))
    rows = b.regexRuleList()
    check("条目带等级与判定式",
          rows[0]["level"] == "must" and rows[1]["pattern"] == "仿佛|似乎"
          and rows[2]["pattern"] == "￥\\d+")
    QTimer.singleShot(60, step2_edit)


def step2_edit():
    panel().startEdit(0)
    panel().setProperty("editRule", "突破必须有灵石代价")
    panel().setProperty("editLevel", "should")
    panel().commitEdit()
    pump(200)
    text = project.read_file(os.path.join(PROJ, project.REGEX_PATH))
    check("改后原文含新写法", "- 规则：突破必须有灵石代价｜level：should｜scope：修炼" in text)
    check("改后别的条目一字未动", "口水词" in text and "现代货币" in text)
    check("标题保留", text.startswith("## 正则"))
    check("界面行随之刷新", b.regexRuleList()[0]["level"] == "should")
    QTimer.singleShot(60, step3_delete)


def step3_delete():
    p = panel()
    p.askDelete(2)
    pump(80)
    mid = project.read_file(os.path.join(PROJ, project.REGEX_PATH))
    check("首次点击只进确认态，不删", "现代货币" in mid
          and int(p.property("pendingDelete")) == 2)
    p.askDelete(2)
    pump(200)
    after = project.read_file(os.path.join(PROJ, project.REGEX_PATH))
    check("二次确认才删", "现代货币" not in after and "口水词" in after)
    txt2 = rendered_text()
    check("删后只剩 2 条渲染", sum(1 for t in txt2 if t.startswith("规则：")) == 2)
    check("删后标题还在", after.startswith("## 正则"))
    QTimer.singleShot(60, finish)


def finish():
    print("=== 本书契约面板探针 ===")
    bad = [m for m in QML_MSG if "ContractPanel" in m]
    for m in bad[:12]:
        print("QML-MSG:", m[:260])
    ok = True
    for name, passed in results:
        print(("PASS" if passed else "FAIL"), name)
        ok = ok and passed
    print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if ok else 1)


QTimer.singleShot(700, step1)
app.exec()
