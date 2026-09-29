# -*- coding: utf-8 -*-
"""共写桥面槽级回归（B6 前三组 / w5 F1-F3 钉测）

覆盖：
- F1：_start_cw_supervisor 类内重复定义护栏（inspect 活源钉测）+ error→逃生门链；
- F2：M5 改写派单必须走 compose（撰写模式）；
- F3：supervisor 报告结论门——痕只在「解析成功∧通过」写、口径分档 skipped/overridden。

形态说明：F1 的「类内重复定义（后者静默覆盖前者）」只有 inspect.getsource(类)
能钉——unit 桩测与单函数 AST 检查都看不见覆盖关系（w4 §5.3 结论）。
"""
import inspect
import os

from app.core import co_dialogue, co_writing, state as st
from app.ui import bridge as bmod


class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


class _SlotSelf:
    """_on_cw_supervisor_done / _on_cw_supervisor_error / forceLockChapter 的轻量 self"""

    def __init__(self, proj):
        os.makedirs(os.path.join(str(proj), "正文"), exist_ok=True)
        st.save_state(str(proj), {"current_chapter": 2, "total_chapters": 10})
        self.proj = str(proj)
        self._cur_num = 2
        self._cw = co_writing.CoWriting(self.proj)
        self._cw_cancelled = False
        self._cw_worker = None
        self._cw_supervisor_failed = False
        self._cw_supervisor_attention = False
        self.toast = _Sig()
        self.cwReportChanged = _Sig()
        self.supervisorFailedChanged = _Sig()
        self.supervisorAttentionChanged = _Sig()
        self.refreshUsage = lambda: None

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)


# ---------- F1：supervisor 唯一定义 + C2 接线 ----------

def test_f1_supervisor_defined_once_with_c2_wiring():
    """F1 护栏：类内重复定义（后者覆盖前者）+ 活版丢 C2 接线 = 事故形态即红"""
    cls_src = inspect.getsource(bmod.Bridge)
    assert cls_src.count("def _start_cw_supervisor") == 1, \
        "_start_cw_supervisor 类内重复定义：Python 后者静默覆盖前者（F1 事故形态）"
    live = inspect.getsource(bmod.Bridge._start_cw_supervisor)
    assert "_on_cw_supervisor_error" in live, "活版 error 未接 C2 专用槽——逃生门死路"
    assert "_cw_supervisor_failed = False" in live, "活版未复位 failed 旗标"
    assert "worker.error.connect(self._on_cw_error)" not in live


def test_f1_error_lights_escape(tmp_path):
    """F1 行为面：supervisor error → failed 旗标 True + toast 给出跳过出口（假 self 替身）"""
    fs = _SlotSelf(tmp_path / "f1")
    bmod.Bridge._on_cw_supervisor_error(fs, "review 槽 401")
    assert fs._cw_supervisor_failed is True
    assert any("跳过比对" in str(c) for c in fs.toast.calls)
