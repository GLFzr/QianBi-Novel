# -*- coding: utf-8 -*-
"""剧情反哺全链路探针（不发任何真实 LLM 请求，FakeRouter 供电）

验证：
① 全链路：MEMORY_BACKFLOW_PROMPT 装配 → parse_backflow → 世界书「追加登记」/
   伏笔表补丁/摘要链落盘 + backflowed 登记；
② 幂等：同份输出重跑 → 不重复新增，「首见第N章」保留；
③ 外部直改世界书：分区外已出现的名字不再登记（跳过）；
④ 缺细纲：无本章细纲也能跑通（占位进 prompt）；
⑤ 中断：LLM 返回后中断请求 → 一个字节不写；
⑥ 触发去重：_maybe_backflow 新鲜不重跑 / 正文改过再跑；
⑦ runBackfill：已新鲜章跳过、缺章提示、未登记章排队；
⑧ NeedsFixDialog 补跑入口（backfillNumsField）存在。
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from probe_guard import arm_config_guard

arm_config_guard()

from PySide6.QtCore import QUrl, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from app.core import co_dialogue, memory, state as st
from app import project
from app.ui.bridge import Bridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.abspath(os.path.join(ROOT, "tests_output", "backflow_probe_proj"))

WARNINGS = []


def _capture(mode, ctx, msg):
    WARNINGS.append(f"{mode}: {ctx.file}:{ctx.line} {msg}")


qInstallMessageHandler(_capture)

PROSE = "# 第4章 柳三更守夜\n柳三更在岐山城当更夫，第一夜点起老灯笼。" * 8

REPLY = """===新实体===
柳三更｜人物｜岐山城守夜更夫，掌老灯笼
顾拾遗｜人物｜世界书已收录，不应重复登记
===新规则===
点灯限额｜每月只能点灯三次，超限折寿
===伏笔变动===
新增｜七次之约｜规则契约｜第60-75章卷末
回收｜旧灯笼的刻痕真相
===偏离点===
细纲要求三招切磋，正文未落地（细纲：三招切磋 → 正文：仅斗嘴）
===一句话摘要===
柳三更首夜点灯守夜，旧灯笼刻痕秘密初露"""

REPLY2 = """===新实体===
柳三更｜人物｜描述被模型改写了，但首见章号必须保留
沈银帮｜组织｜正文新出现的神秘组织
===新规则===
（无）
===伏笔变动===
（无）
===偏离点===
（无）
===一句话摘要===
（略）"""


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.reply

    def chat_stream(self, prompt, on_chunk=None, **kw):
        self.prompts.append(prompt)
        return self.reply


class _FakeRouter:
    def __init__(self, reply):
        self.c = _FakeClient(reply)

    def client(self, slot):
        return self.c


def build_fixture():
    if os.path.isdir(PROJ):
        shutil.rmtree(PROJ)
    for d in ["设定", "大纲", "正文", "追踪"]:
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    with open(os.path.join(PROJ, "设定", "世界书.md"), "w", encoding="utf-8") as f:
        f.write("# 世界书\n\n顾拾遗属灯盟保守派末代。\n")
    with open(os.path.join(PROJ, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("## 主要角色表\n- 顾拾遗：灯盟末代。\n")
    with open(os.path.join(PROJ, "正文", "第004章_柳三更守夜.md"), "w", encoding="utf-8") as f:
        f.write(PROSE)
    with open(os.path.join(PROJ, "追踪", "伏笔.md"), "w", encoding="utf-8") as f:
        f.write("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                "|------|------|----------|------|----------|------|\n"
                "| 旧灯笼的刻痕 | 道具谜团 | 第2章 | 新设 | 第30章前 | |\n")
    # 注意：故意不建 大纲/细纲_第004章.md（缺细纲场景）
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


def _worldbook():
    return project.read_file(os.path.join(PROJ, "设定", "世界书.md"))


def step1_full_chain():
    r = _FakeRouter(REPLY)
    w = co_dialogue.MemoryBackflowWorker({}, PROJ, 4, PROSE, router=r)
    w.run()
    wb = _worldbook()
    check("世界书出现「追加登记」分区", project.WORLDBOOK_BACKFLOW_HEADING in wb)
    check("新实体柳三更已登记（首见第4章）",
          "**柳三更**（人物）" in wb and "首见第4章" in wb)
    check("新规则点灯限额已登记", "点灯限额" in wb and "每月只能点灯三次" in wb)
    check("分区外已收录的顾拾遗未重复登记", "**顾拾遗**" not in wb)
    check("分区外既有内容逐字保留", "顾拾遗属灯盟保守派末代。" in wb)
    check("prompt 注入世界书基准", "顾拾遗属灯盟保守派末代" in w.last_prompt)
    check("缺细纲占位进 prompt", "（无本章细纲）" in w.last_prompt)
    fs = project.read_file(os.path.join(PROJ, "追踪", "伏笔.md"))
    check("伏笔新增七次之约（反哺登记）", "七次之约" in fs and "反哺登记" in fs)
    check("既有伏笔旧灯笼的刻痕被标记已回收",
          "已回收" in fs and "第4章回收（反哺）" in fs)
    sm = project.read_file(os.path.join(PROJ, "追踪", "章节摘要.md"))
    check("一句话摘要入链", "第4章" in sm and "旧灯笼刻痕秘密初露" in sm)
    state = st.load_state(PROJ)
    check("backflowed 已登记且报告含偏离点",
          "4" in (state.get("backflowed") or {})
          and "偏离点" in state["backflowed"]["4"]["report"])
    QTimer.singleShot(100, step2_idempotent)


def step2_idempotent():
    w = co_dialogue.MemoryBackflowWorker({}, PROJ, 4, PROSE, router=_FakeRouter(REPLY))
    w.run()
    wb = _worldbook()
    check("重跑不重复新增柳三更", wb.count("**柳三更**") == 1)
    check("重跑不重复新增伏笔", project.read_file(
        os.path.join(PROJ, "追踪", "伏笔.md")).count("七次之约") == 1)
    check("重跑不重复回收（已回收行不再命中）",
          project.read_file(os.path.join(PROJ, "追踪", "伏笔.md")).count("第4章回收（反哺）") == 1)
    QTimer.singleShot(100, step3_outside_edit)


def step3_outside_edit():
    # 外部直改世界书：分区**外**人工写入「沈银帮」→ 模型再报它时应跳过
    path = os.path.join(PROJ, "设定", "世界书.md")
    doc = project.read_file(path)
    prefix, section, suffix = memory._split_worldbook_section(doc)
    new_doc = prefix.rstrip("\n") + "\n\n沈银帮是一伙夜贼。\n"
    if section:
        new_doc += "\n" + section
    if suffix:
        new_doc += "\n" + suffix
    project.write_file(path, new_doc + "\n")
    w = co_dialogue.MemoryBackflowWorker({}, PROJ, 4, PROSE, router=_FakeRouter(REPLY2))
    w.run()
    wb = _worldbook()
    check("外部已收录的沈银帮不再进追加登记", "**沈银帮**" not in wb)
    check("原位更新保留首见第4章",
          "描述被模型改写了" in wb and wb.count("首见第4章") >= 1
          and "首见第4章" in wb.split("柳三更")[1][:200])
    QTimer.singleShot(100, step4_interrupt)


def step4_interrupt():
    import time as _time
    before = _worldbook()
    fs_before = project.read_file(os.path.join(PROJ, "追踪", "伏笔.md"))
    w = co_dialogue.MemoryBackflowWorker({}, PROJ, 4, PROSE,
                                         router=_FakeRouter(REPLY))
    # 模拟真实取消：worker 线程运行中（chat 期间）用户点了取消 → 落盘前必须停手
    def _slow_chat(prompt, **kw):
        _time.sleep(0.3)
        return REPLY
    w.router.c.chat = _slow_chat
    w.start()
    _time.sleep(0.1)
    w.requestInterruption()
    check("中断等待：线程在时限内退出", bool(w.wait(3000)))
    check("中断后世界书一个字节未动", _worldbook() == before)
    check("中断后伏笔表一个字节未动",
          project.read_file(os.path.join(PROJ, "追踪", "伏笔.md")) == fs_before)
    QTimer.singleShot(100, step5_trigger_dedupe)


def step5_trigger_dedupe():
    starts = []
    b._start_backflow = lambda n: starts.append(n)
    b._backflow_worker = None
    b._maybe_backflow(4)          # backflowed 新鲜（正文未再改）→ 跳过
    check("新鲜登记：_maybe_backflow 不重跑", starts == [])
    # 模拟正文改过（mtime 前移 3 秒，越过 1s 容差）
    p = os.path.join(PROJ, "正文", "第004章_柳三更守夜.md")
    import time
    t = time.time() + 3
    os.utime(p, (t, t))
    b._maybe_backflow(4)
    check("正文改过：_maybe_backflow 重跑", starts == [4])
    QTimer.singleShot(100, step6_backfill)


def step6_backfill():
    starts = []
    b._start_backflow = lambda n: starts.append(n)
    b._backflow_worker = None
    b._backflow_queue = []
    # step5 把第4章正文 mtime 前移了 → 先把正文时间还原并重新登记，恢复「新鲜」
    import time
    p = os.path.join(PROJ, "正文", "第004章_柳三更守夜.md")
    past = time.time() - 60
    os.utime(p, (past, past))
    st.mark_backflowed(PROJ, st.load_state(PROJ), 4, "probe re-mark")
    with open(os.path.join(PROJ, "正文", "第005章_夜行.md"), "w", encoding="utf-8") as f:
        f.write("# 第5章 夜行\n正文。")
    b.runBackfill("4,5,9")        # 4 新鲜跳过 / 5 待跑 / 9 缺章
    check("补跑：只排队未登记且正文存在的章", starts == [5])
    b._backflow_queue = []
    QTimer.singleShot(100, step7_qml)


def step7_qml():
    dlg = None
    for c in win.findChildren(object):
        try:
            if c.objectName() == "needsFixDialog":
                dlg = c
                break
        except Exception:
            pass
    check("NeedsFixDialog 存在", dlg is not None)
    field = None
    if dlg:
        for c in dlg.findChildren(object):
            try:
                if c.objectName() == "backfillNumsField":
                    field = c
                    break
            except Exception:
                pass
    check("补跑入口输入框存在（backfillNumsField）", field is not None)
    errs = [w for w in WARNINGS if "ReferenceError" in w or "TypeError" in w]
    check("无 ReferenceError/TypeError 警告", not errs)
    for w in errs:
        print("  QML>", w)
    print("PROBE_DONE " + ("FAIL" if check.failed else "PASS"), flush=True)
    QTimer.singleShot(100, app.quit)


QTimer.singleShot(600, step1_full_chain)
rc = app.exec()
shutil.rmtree(PROJ, ignore_errors=True)
sys.exit(0 if not check.failed and rc == 0 else 1)
