# -*- coding: utf-8 -*-
"""字数闸门 + 陈旧防护探针（#41：短章为何能静默过审；不发任何真实 LLM 请求）

验证：
① 本地预检：短章 → [字数] 阻断 + REJECT，细纲字数目标优先；
② 共写查验短路：CwProseCheckWorker review 模式零 LLM 直出规范报告；
③ 锁定闸门：短章点「确定」→ lockBlocked 信号 + 强锁对话框弹出，未锁定；
④ 强锁通道：「仍要锁定」→ 锁定成功 + forced_locks 留痕，重复强锁不留重复痕；
⑤ 陈旧防护：正文改过之后旧审校结论 → 队列标「过期·待复审」而非 untracked。
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from probe_guard import arm_config_guard

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import co_dialogue, gates, state as st
from app import mustscan, project
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "wordblock_probe_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)

SHORT_PROSE = "# 第4章 短章测试\n" + "这一章字数明显不够。" * 15   # 约 160 字


class _FakeClient:
    def __init__(self):
        self.prompts = []

    def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return "不应被调用的回复"

    def chat_stream(self, prompt, on_chunk=None, **kw):
        self.prompts.append(prompt)
        return "不应被调用的回复"


class _FakeRouter:
    def __init__(self):
        self.c = _FakeClient()

    def client(self, slot):
        return self.c


def build_fixture():
    if os.path.isdir(PROJ):
        shutil.rmtree(PROJ)
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    with open(os.path.join(PROJ, "大纲", "细纲_第004章.md"), "w", encoding="utf-8") as f:
        f.write("字数目标：2000\n核心事件：短章闸门测试。\n")
    with open(os.path.join(PROJ, "正文", "第004章_短章测试.md"), "w", encoding="utf-8") as f:
        f.write(SHORT_PROSE)
    st.save_state(PROJ, {"stage": "writing", "current_chapter": 4, "total_chapters": 10})


build_fixture()

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
b._open_project(PROJ, silent=True)


def check(name, ok):
    print(("[OK ] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        check.failed = True


check.failed = False

LOCK_BLOCKED = []
LOCK_BLOCKED_DETAIL = []
b.lockBlocked.connect(lambda num, reason, actual, target, kind:
                      LOCK_BLOCKED.append((num, reason, actual, target, kind)))
# Q6：伴随详情信号——全量违规/当前值/阈值/两侧后果必须同批到齐
b.lockBlockedDetail.connect(lambda num, detail:
                            LOCK_BLOCKED_DETAIL.append((num, detail)))


def step1_precheck():
    items, blocking, verdict = gates.word_count_precheck(
        PROJ, 4, SHORT_PROSE, b.cfg)
    check("短章预检判 REJECT", verdict == "REJECT")
    check("阻断文案为 [字数] 且引用细纲目标 2000",
          len(blocking) == 1 and blocking[0].startswith("[字数]") and "2000" in blocking[0])
    check("下限 = 2000×0.9 = 1800", "1800" in blocking[0])
    check("预检条目可直接进 v2 登记结构",
          items[0]["dim"] == "D_PLOT" and items[0]["level"] == "fail")
    QTimer.singleShot(100, step2_cw_shortcircuit)


def step2_cw_shortcircuit():
    r = _FakeRouter()
    w = co_dialogue.CwProseCheckWorker(b.cfg, PROJ, 4, SHORT_PROSE,
                                       mode="review", router=r)
    w.run()
    check("共写查验短路：审校槽零调用", r.c.prompts == [])
    check("短路报告含 [字数] 阻断且判 REJECT",
          "[字数]" in w.result_text and "REJECT" in w.result_text)
    QTimer.singleShot(100, step3_lock_gate)


def step3_lock_gate():
    b._cur_num = 4
    b._chapter_text = SHORT_PROSE
    b.confirmChapterLocked()
    check("短章确定 → lockBlocked 信号发出", len(LOCK_BLOCKED) == 1)
    check("信号携带章号/实际字数/目标",
          LOCK_BLOCKED and LOCK_BLOCKED[0][0] == 4
          and LOCK_BLOCKED[0][2] == project.count_chars(SHORT_PROSE)
          and LOCK_BLOCKED[0][3] == 2000)
    check("闸门类型标注为 word（决定强锁对话框文案）",
          bool(LOCK_BLOCKED) and LOCK_BLOCKED[0][4] == "word")
    check("Q6 详情伴随信号同发：违规全清单=逐条列表且含首条",
          bool(LOCK_BLOCKED_DETAIL) and LOCK_BLOCKED_DETAIL[0][0] == 4
          and isinstance(LOCK_BLOCKED_DETAIL[0][1].get("violations"), list)
          and len(LOCK_BLOCKED_DETAIL[0][1]["violations"]) >= 1
          and "1800" in " ".join(LOCK_BLOCKED_DETAIL[0][1]["violations"]))
    check("Q6 详情携带当前值/阈值与两侧后果",
          bool(LOCK_BLOCKED_DETAIL)
          and LOCK_BLOCKED_DETAIL[0][1].get("current_value") == project.count_chars(SHORT_PROSE)
          and LOCK_BLOCKED_DETAIL[0][1].get("threshold") == 2000
          and bool(LOCK_BLOCKED_DETAIL[0][1].get("continue_consequence"))
          and bool(LOCK_BLOCKED_DETAIL[0][1].get("rollback_consequence")))
    check("短章未被静默锁定", not project.is_chapter_locked(PROJ, 4))
    QTimer.singleShot(400, step4_force_dialog)


def step4_force_dialog():
    dlg = None
    for c in win.findChildren(object):
        try:
            if c.objectName() == "forceLockDialog":
                dlg = c
                break
        except Exception:
            pass
    check("强锁确认对话框已由信号弹出", dlg is not None and bool(dlg.property("opened")))
    check("主窗记录未达标章号与目标字数",
          int(win.property("lockBlockNum") or 0) == 4
          and int(win.property("lockBlockTarget") or 0) == 2000)
    b.forceConfirmChapterLocked()
    check("「仍要锁定」→ 章节锁定成功", project.is_chapter_locked(PROJ, 4))
    state = st.load_state(PROJ)
    check("强锁审计痕已留（含字数理由）",
          "4" in (state.get("forced_locks") or {})
          and "[字数]" in state["forced_locks"]["4"].get("reason", ""))
    b.forceConfirmChapterLocked()      # 已锁定再强锁 → 早退，不重复留痕
    state = st.load_state(PROJ)
    check("重复强锁不留重复痕", "4" in state.get("forced_locks", {}))
    if dlg:
        dlg.metaObject().invokeMethod(dlg, "close")
    QTimer.singleShot(200, step4b_contract_multi)


def step4b_contract_multi():
    """WP-23：锁门详情的分母必须是真的——契约路径造 ≥2 条阻断。

    字数闸门物理上只产 1 条 blocking（word 夹具区分不了「全量」与「首条」），
    可区分的是正则契约路径：正文同时命中 2 条 must 禁用规则。
    断言 len(violations)==阻断条数——「改回首条」与「删掉第二条规则」都红。"""
    rules = ("- 禁止出现违背物理的瞬移描写：`一眨眼就到了|瞬间移动到`｜level：must｜mode：forbid\n"
             "- 禁止主角直接喊出功法名：`大罗金仙诀|九转玄功`｜level：must｜mode：forbid\n")
    project.write_file(os.path.join(PROJ, "设定", "正则.md"),
                       "# 本书正则契约\n" + rules)
    long_prose = ("# 第5章 契约试炼\n\n" + (
        "他从巷口走出来，街边的灯笼一盏一盏亮起，卖馄饨的摊子冒着热气。"
        "老者抬头看了他一眼，又低下头去搅动锅里的汤。他没有停留，"
        "沿着石板路一直往北，走过桥，桥下的水流很急，拍在石头上碎成沫子。"
        "城门口的兵丁懒散地靠着墙，长枪斜在肩上，谁也没注意到他的影子被灯光拉得很长。") * 24)
    long_prose += "情急之下他施展大罗金仙诀，一眨眼就到了城门另一侧。"
    project.write_file(project.get_chapter_path(PROJ, 5, "契约试炼"), long_prose)
    from app.core import gates as _gates
    _wi, _wb, _wv = _gates.word_count_precheck(PROJ, 5, long_prose, b.cfg)
    check("第 5 章字数达标（不触发字数闸门，确保走契约路径）",
          _wv == "" and not _wb)
    _items, c_blocking, c_verdict = mustscan.contract_precheck(PROJ, 5, long_prose)
    check("夹具确实命中 2 条 must 契约（分母真实性：删掉第二条规则本条即红）",
          c_verdict == "REJECT" and len(c_blocking) == 2)
    b._cur_num = 5
    b._chapter_text = long_prose
    before = len(LOCK_BLOCKED_DETAIL)
    b.confirmChapterLocked()
    detail = LOCK_BLOCKED_DETAIL[-1][1] if len(LOCK_BLOCKED_DETAIL) > before else {}
    check("契约 ≥2 条阻断 → 详情全清单逐条携带（violations 改回首条即红）",
          len(detail.get("violations", [])) == len(c_blocking)
          and all(any(t in v for v in detail.get("violations", []))
                  for t in ("一眨眼就到了", "大罗金仙诀")))
    check("旧 lockBlocked 信号与详情同发（contract 类型、条数一致）",
          bool(LOCK_BLOCKED) and LOCK_BLOCKED[-1][4] == "contract"
          and bool(detail.get("violations")))
    check("章 5 未被静默锁定", not project.is_chapter_locked(PROJ, 5))
    project.write_file(os.path.join(PROJ, "设定", "正则.md"), "")   # 还原空契约
    project.write_file(os.path.join(PROJ, "设定", "正则.md"), "")   # 还原空契约
    QTimer.singleShot(150, step5_stale)


def step5_stale():
    # 造一条「过去的」审校结论，然后把正文 mtime 推到其后 → 结论过期
    state = st.load_state(PROJ)
    st.save_review_findings(PROJ, state, 4, "PASS", [], [], [])
    p = os.path.join(PROJ, "正文", "第004章_短章测试.md")
    t = time.time() + 5
    os.utime(p, (t, t))
    check("正文晚于结论 → is_review_stale 为真",
          st.is_review_stale(PROJ, st.load_state(PROJ), 4))
    b.refreshQueue()
    row = None
    for it in b.chapterModel._items:
        if it.get("num") == 4:
            row = it
            break
    check("队列把该章标为「过期」", row is not None and row.get("state") == "stale")
    check("过期备注提示待复审", row is not None and "过期" in row.get("note", ""))
    QTimer.singleShot(100, step6_warnings)


def step6_warnings():
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_precheck)
rc = app.exec()
shutil.rmtree(PROJ, ignore_errors=True)
sys.stdout.flush()
sys.stderr.flush()
# A-2/A-10 同款对策：WP-23 新增步骤后 Qt 析构期偶发 access violation(0xC0000005)
# 把 PASS 的退码改写成崩溃码——os._exit 跳过析构，退码=判定结果
sys.stdout.flush(); sys.stderr.flush()
import atexit as _ax  # v4复验：arm_config_guard 的真 config 还原挂在 atexit，os._exit 会跳掉它
_ax._run_exitfuncs()
os._exit(0 if not check.failed and rc == 0 else 1)
