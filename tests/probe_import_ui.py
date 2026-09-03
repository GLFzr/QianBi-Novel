# -*- coding: utf-8 -*-
"""外部文档导入探针（#9）：拆解 → 预览映射 → 勾选才落盘 → 契约页整批撤销

真 QML 对话框 + 真 Bridge + 真文件，只把 LLM 调用换成 canned 产物。
要验的都是「一做歪就伤作者」的事：
① 未验真的条目默认不勾选，且原因给得出来；
② 一个都没勾 → 项目文件字节不变；
③ 同人导入的世界书分区以《原作名》标识，分歧点真的变成 must 契约；
④ 撤销只回滚属于该批的内容，作者改过的不碰。
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

from app import project, importdoc
import app.ui.bridge as bridge_mod

QML_MSG = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC = """《守夜人》设定集（原作：爱潜水的乌贼）

灯序共九境，晋升必须服食主材料，失控者化为烛妖。
主角周夜是第七境守灯人，右手戴一枚会数数的骨戒。
每月只能点灯三次，第四次灯灭即人灭。

本书分歧点：第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒。
原作进程：原作第一卷，周夜在灯塔之下杀死了前任守灯人。

第3章 替身
周夜把骨戒转了半圈，灯塔下的水面上没有倒影。
他记得这一夜原作里死的是两个人，不是一个。
"""

PRODUCT = """===原作===
书名：《守夜人》｜作者：爱潜水的乌贼
灯序共九境，晋升必须服食主材料，失控者化为烛妖。
引证：灯序共九境，晋升必须服食主材料，失控者化为烛妖

===世界书===
- 周夜（人物）：第七境守灯人，右手戴一枚会数数的骨戒
引证：主角周夜是第七境守灯人，右手戴一枚会数数的骨戒

===正则===
- 每月只能点灯三次，第四次灯灭即人灭｜level：must｜scope：全书
引证：每月只能点灯三次，第四次灯灭即人灭

===分歧点===
- 第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒
引证：第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒

===原作进程===
原作第一卷｜原作第1章｜周夜在灯塔之下杀死了前任守灯人
引证：原作第一卷，周夜在灯塔之下杀死了前任守灯人

===正文 第3章===
第3章 替身
周夜把骨戒转了半圈，灯塔下的水面上没有倒影。

===大纲===
（无）
"""


class _FakeWorker(bridge_mod.QThread):
    """顶掉真 LLM：信号与 _DocImportWorker 同名同签名，run 里直接吐 canned 产物"""
    sig_progress = bridge_mod.Signal(int, int)
    sig_reasoning = bridge_mod.Signal(str)
    sig_done = bridge_mod.Signal(bool, list, str)

    def __init__(self, cfg, proj, chunks, parent=None):
        super().__init__(parent)
        self.aborted = False

    def abort(self):
        self.aborted = True

    def run(self):
        if self.aborted:
            self.sig_done.emit(False, [], "已取消导入")
            return
        self.sig_progress.emit(1, 1)
        self.sig_done.emit(True, [PRODUCT], "")


app = QGuiApplication(sys.argv)
qInstallMessageHandler(lambda m, c, msg: QML_MSG.append(msg))
TMP = tempfile.mkdtemp(prefix="qbn_import_")
PROJ = project.create_project(TMP, "导入探针书")
DOC = os.path.join(TMP, "守夜人设定集.txt")
with open(DOC, "w", encoding="utf-8") as f:
    f.write(SRC)

bridge_mod._DocImportWorker = _FakeWorker
b = bridge_mod.Bridge()
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


def walk(item):
    """item view 的 delegate 只挂在视觉树上，findChildren 一条也找不到"""
    for c in item.childItems():
        yield c
        yield from walk(c)


def _find_qml(root, name):
    """按 objectName 找 QML 对象。

    Dialog 的根是 QQuickPopup（QObject，**不是** QQuickItem），
    所以 findChild(QQuickItem, …) 永远找不到它——必须递归走 children()。
    """
    if root.objectName() == name:
        return root
    for c in root.children():
        got = _find_qml(c, name)
        if got is not None:
            return got
    return None


def dlg():
    d = _find_qml(win, "importDialog")
    assert d is not None, "找不到 importDialog"
    return d


def rendered(root_name, from_obj=None):
    """某个 ListView/ScrollView 里**渲染出来的文本**（delegate 只在视觉树上）"""
    root = from_obj if from_obj is not None else win
    it = _find_qml(root, root_name)
    if it is None or not isinstance(it, QQuickItem):
        return []
    return [str(c.property("text")) for c in walk(it) if c.property("text")]


def read(rel):
    return project.read_file(os.path.join(PROJ, rel))


def snapshot():
    out = {}
    for d in ("设定", "大纲", "正文", "追踪"):
        base = os.path.join(PROJ, d)
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isfile(p):
                out[os.path.relpath(p, PROJ)] = open(p, encoding="utf-8").read()
    return out


def guard(fn):
    """探针里任何一步抛异常都必须收尾退出——否则事件循环一直跑，失败看起来像卡死"""
    def wrapped():
        try:
            fn()
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            results.append((fn.__name__ + " 抛出异常", False))
            finish()
    return wrapped


@guard
def step1():
    win.setProperty("activePanel", "contract")
    d = dlg()
    check("顶栏有导入按钮", _find_qml(win, "importBtn") is not None)
    d.open()
    pump(260)
    check("对话框可见", bool(d.property("visible")))
    hint = _find_qml(d, "importEmptyHint")
    check("未解析时给出空态提示",
          hint is not None and "还没有解析结果" in str(hint.property("text"))
          and bool(hint.property("visible")))
    before = snapshot()
    b.startImportDocument(DOC)
    pump(400)
    items = b.importItems()
    check("解析出条目", len(items) > 0)
    check("落点含原作概况与分歧点",
          {i["key"] for i in items} >= {"canon", "divergence", "worldbook",
                                        "regex", "canon_timeline", "prose"})
    check("原作名被识别", next(i for i in items if i["key"] == "canon")["canon"] == "守夜人")
    check("分歧点落到 设定/正则.md",
          next(i for i in items if i["key"] == "divergence")["target"].endswith(
              os.path.join("设定", "正则.md")))
    check("建议契约单独标出且预勾选",
          [i for i in items if i["suggested"]][0]["checked"] is True)
    check("未验真条目不混在勾选里",
          all(i["checked"] for i in items if i["trust"])
          and all(not i["checked"] for i in items if not i["trust"]))
    txt = rendered("importListScroll", d)
    check("预览里看得到落点路径", any("→" in t and ".md" in t for t in txt))
    check("预览里看得到验真凭据", any("逐字比对" in t or "引证验真" in t for t in txt))
    check("预览里看得到原作标记", any("原作《守夜人》" in t for t in txt))
    check("大纲缺失被如实列出", any("全书大纲" in m["label"]
                                    for m in importdoc.missing_slots(b._import_plans)))
    check("识别到原作时不再报缺原作概况",
          not any(m["key"] == "canon" for m in importdoc.missing_slots(b._import_plans)))
    check("解析阶段一个字节都没写", snapshot() == before)
    QTimer.singleShot(60, step2)


@guard
def step2():
    d = dlg()
    b.setImportAllChecked(False)
    pump(160)
    before = snapshot()
    b.confirmImport()
    pump(200)
    check("全不选时确认导入零副作用", snapshot() == before)
    btn = _find_qml(d, "importConfirmBtn")
    check("确认按钮在零勾选下不可用", bool(btn.property("enabled")) is False)
    b.setImportAllChecked(True)
    pump(160)
    b.confirmImport()
    pump(300)
    wb = read(project.WORLDBOOK_PATH)
    check("世界书分区用原作名标识", "## 原作·守夜人" in wb and "## 导入·" not in wb)
    check("原作实体入册", "周夜" in wb)
    rules = project.regex_rules(PROJ)
    check("分歧点成 must 契约且带章域",
          any("骨戒提前觉醒" in r["rule"] and r["level"] == "must"
              and r["scope"].startswith("第1章") for r in rules))
    check("建议契约一并写入", any("既成事实不得改写" in r["rule"] for r in rules))
    check("原作进程进时间线表", "周夜在灯塔之下杀死了前任守灯人" in read("追踪/时间线.md"))
    check("正文按章建档", os.path.isfile(os.path.join(PROJ, "正文", "第003章_替身.md")))
    check("导入记录不进项目文件列表",
          not any(f["rel"].endswith("导入记录.json") for f in b.projectFiles()))
    batches = b.importBatches()
    check("导入批次可查", len(batches) == 1 and batches[0]["canon"] == "守夜人")
    QTimer.singleShot(60, step3)


@guard
def step3():
    p = _find_qml(win, "contractPanel")
    p.refresh()
    pump(200)
    check("契约页显示导入批次", int(p.property("batchCount")) == 1)
    check("批次行渲染出原作名",
          any("原作《守夜人》" in t for t in rendered("importBatchCard", p)))
    path = os.path.join(PROJ, "正文", "第003章_替身.md")
    project.write_file(path, "第3章 替身\n作者自己重写过。\n")
    p.askRevert(b.importBatches()[0]["id"])
    pump(120)
    check("撤销要二次确认", str(p.property("pendingRevert")) != "" and os.path.isfile(path))
    p.askRevert(b.importBatches()[0]["id"])
    pump(250)
    check("被编辑过的章节文件保留",
          os.path.isfile(path) and "作者自己重写过" in project.read_file(path))
    check("世界书分区随内容一并删除", "周夜" not in read(project.WORLDBOOK_PATH))
    check("分歧点契约被撤销",
          not any("骨戒提前觉醒" in r["rule"] for r in project.regex_rules(PROJ)))
    check("时间线行被撤销",
          "周夜在灯塔之下杀死了前任守灯人" not in read("追踪/时间线.md"))
    p.refresh()
    pump(120)
    check("撤完批次清单清空", int(p.property("batchCount")) == 0)
    QTimer.singleShot(60, finish)


def finish():
    print("=== 外部文档导入探针 ===")
    bad = [m for m in QML_MSG if "Import" in m or "Contract" in m]
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
