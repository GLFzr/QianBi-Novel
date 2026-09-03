# -*- coding: utf-8 -*-
"""「确定细纲」/「生成下一批」语义探针（#2 + #4）

用户报的原话是：细纲阶段点「确定」实际做的是校验，却顺带把细纲往下一批滚，
跟其它所有阶段的「确定=进入下一步」不一致。本探针把拆开后的两条链钉死：

  确定细纲 = 定稿本单元 → 已有细纲则校验 → 无阻塞才进入「正文写作」
  生成下一批 = 只往后滚一批细纲，阶段一个字都不动

全程零 LLM 调用（三个 worker 都被替身接掉）。
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

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from app import project
from app.core import co_dialogue, state as st
from app.ui.bridge import Bridge

app = QGuiApplication(sys.argv)
TMP = tempfile.mkdtemp(prefix="qbn_outline_confirm_")
PROJ = project.create_project(TMP, "细纲确定探针书")
for n in range(1, 7):
    project.write_file(project.get_outline_path(PROJ, n), "核心事件：事件%02d" % n)

state = st.load_state(PROJ)
cw = st.ensure_cw(state)
cw["mode"] = "cw"
cw["stage"] = st.STAGE_CW_UNIT
cw["unit"] = {"start": 1, "target_end": 30, "topic": "开篇单元"}
co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "user", "本单元把金手指的代价立起来")
st.save_state(PROJ, state)

ran = []


class _FakeWorker(QObject):
    done = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, payload, kind, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.kind = kind
        self._running = True

    def start(self):
        self._running = False
        QTimer.singleShot(0, self._fire)

    def _fire(self):
        if self.kind == "batch":
            # 真 worker 会先把这批细纲落盘再回 done
            for num, _title, content in self.payload:
                project.write_file(project.get_outline_path(PROJ, num), content)
        self.done.emit(self.payload)
        self.finished.emit()

    def isRunning(self):
        return self._running

    def requestInterruption(self):
        pass


def _mk(kind, payload):
    def _cls(cfg, proj, *a, **kw):
        ran.append(kind)
        return _FakeWorker(payload, kind)
    return _cls


results = []


def check(name, ok):
    results.append((name, bool(ok)))


def pump(ms=120):
    import time
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


b = Bridge()
b._open_project(PROJ, silent=True)

UNIT_PRODUCT = "单元总纲：第一段冲突收口。\n\n→ 下阶段交接\n按批出细纲。"
CLEAN = "===BLOCKING===\n无\n===ADVISORY===\n- 建议：第4章可加一处代价"
DIRTY = "===BLOCKING===\n- 第3章主角无代价获得机缘，违反 must 契约\n===ADVISORY===\n无"


# ---------------------------------------------------------------- 确定细纲：校验链
co_dialogue.SummarizeWorker = _mk("summarize", UNIT_PRODUCT)
co_dialogue.ReviewOutlinesWorker = _mk("review", CLEAN)
co_dialogue.OutlineBatchWorker = _mk(
    "batch", [(7, "闭关", "核心事件：事件07"), (8, "出关", "核心事件：事件08")])

b.confirmCwStage()
pump(400)
check("确定细纲：先定稿再校验", ran == ["summarize", "review"])
check("确定细纲：机器阶段推进到正文写作", b._get_cw_stage_key() == st.STAGE_CW_PROSE)

# ---------------------------------------------------------------- 阻塞链：重来一遍
_s = st.load_state(PROJ)
st.ensure_cw(_s)["stage"] = st.STAGE_CW_UNIT
st.save_state(PROJ, _s)
b._cw_view = st.STAGE_CW_UNIT
del ran[:]
co_dialogue.ReviewOutlinesWorker = _mk("review", DIRTY)
b.confirmCwStage()
pump(400)
check("有阻塞：不推进阶段", b._get_cw_stage_key() == st.STAGE_CW_UNIT)
tail = co_dialogue.transcript_text(b._cw.load(), st.STAGE_CW_UNIT)
check("有阻塞：把阻塞原因回话到对话区", "无代价获得机缘" in tail)

# ---------------------------------------------------------------- 生成下一批
del ran[:]
stage_before = b._get_cw_stage_key()
b.generateNextCwOutlines()
pump(400)
check("生成下一批：只起批次 worker", ran == ["batch"])
check("生成下一批：阶段不变", b._get_cw_stage_key() == stage_before)
saved = st.ensure_cw(st.load_state(PROJ))
check("生成下一批：记下最新批次", saved.get("last_outline_batch") == [7, 8])
check("生成下一批：编辑器跟随这批", "事件07" in b.chapterText and "事件08" in b.chapterText)

# ---------------------------------------------------------------- 守卫与文案
b._cw_busy = True
del ran[:]
b.generateNextCwOutlines()
pump(100)
check("忙时不重复起 worker", ran == [])
b._cw_busy = False

nums = [int(n) for n, _p in project.list_outlines(PROJ)]
check("下一批接在已有细纲之后", sorted(nums) == [1, 2, 3, 4, 5, 6, 7, 8])

print("=== 细纲确定/滚动探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
