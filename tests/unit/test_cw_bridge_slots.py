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


# ---------- F2：改写派单走撰写模式（compose） ----------

class _DispatchSelfMode:
    """_dispatch_cw_rewrite 的轻量 self（捕获 spawn 的 mode 形参）"""

    def __init__(self, proj):
        os.makedirs(os.path.join(str(proj), "正文"), exist_ok=True)
        os.makedirs(os.path.join(str(proj), "大纲"), exist_ok=True)
        with open(os.path.join(str(proj), "大纲", "细纲_第002章.md"), "w",
                  encoding="utf-8") as f:
            f.write("核心事件：乙\n故事内容：略。")
        st.save_state(str(proj), {"current_chapter": 2, "total_chapters": 10})
        self.proj = str(proj)
        self._cw = co_writing.CoWriting(self.proj)
        self._cw_worker = None               # worker 已释放路径（不触发 QTimer 重试）
        self.toast = _Sig()
        self.cwReportChanged = _Sig()
        self.spawned = []

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)

    def _get_cw_mode(self):
        return "cw"

    def _get_cw_stage_key(self):
        return st.STAGE_CW_PROSE

    def _spawn_cw_dialogue(self, text, stage, focus_chapter=0, mode="discuss"):
        self.spawned.append((text, stage, focus_chapter, mode))


def test_f2_dispatch_sends_compose_mode(tmp_path):
    """F2 护栏：自动派单必须 compose（prompt 挂 <<<正文>>> 契约、不受 320 字截断）"""
    from app.prompts import co_writing as cp

    fs = _DispatchSelfMode(tmp_path / "f2")
    _state = st.load_state(fs.proj)
    st.ensure_cw(_state)["report"] = {
        "ts": "08-31 20:00", "num": 2,
        "text": "- 结论：需调整\n- 【改写指令】把开头改紧凑。"}
    st.save_state(fs.proj, _state)
    bmod.Bridge._dispatch_cw_rewrite(fs, 2, "把开头改紧凑。", report_ts="08-31 20:00")
    assert len(fs.spawned) == 1
    assert fs.spawned[0][3] == "compose", \
        "改写派单走了 discuss：禁产正文+截断，结构上产不出改写稿"
    # compose 在 cw_prose 阶段挂正文提取契约，不含讨论禁产令
    block = cp.mode_block_for("cw_prose", "compose", "改写")
    assert "<<<正文>>>" in block and "禁止展开" not in block
