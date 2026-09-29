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

from app import project
from app.core import co_dialogue, co_writing, state as st
from app.ui import bridge as bmod


class _Recorder:
    """构造即失败——被断言「零请求」的路径上出现任何 worker/客户端实例化即红"""

    def __init__(self, *a, **kw):
        raise AssertionError("该路径不应构造 LLM worker/客户端（零网络请求）")


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
        self.cwStageChanged = _Sig()
        self.refreshUsage = lambda: None

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)

    def _get_cw_stage_key(self):
        return st.ensure_cw(st.load_state(self.proj)).get("stage", st.STAGE_CW_PROJECT)


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


# ---------- F3：supervisor 报告结论门 ----------

PASS = "### 主 Agent 报告\n- 衔接：OK\n- 结论：通过（无需改动）"
NEEDS_FIX_NO_DIR = "- 结论：需调整（问题存在但未给指令）"
NO_CONCLUSION = "自由发挥的一段报告，没有结论行。"


def _seed_proj(tmp_path, name):
    proj = str(tmp_path / name)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    st.save_state(proj, {"current_chapter": 2, "total_chapters": 10})
    return proj


def test_f3_marker_only_on_parsed_pass(tmp_path):
    """F3 护栏：痕只在「解析成功∧通过」写；需调整/解析失败不置痕——修复前恒置痕（红）"""
    for text, want_marker in [(PASS, True), (NEEDS_FIX_NO_DIR, False), (NO_CONCLUSION, False)]:
        proj = _seed_proj(tmp_path, f"p{int(want_marker)}{len(text)}")
        fs = _SlotSelf(proj)
        bmod.Bridge._on_cw_supervisor_done(fs, text)
        supervised = st.ensure_cw(st.load_state(proj)).get("supervised", {})
        assert bool(supervised.get("2")) is want_marker, f"{text[:12]}… 置痕={want_marker} 才对"


def test_f3_parse_fail_not_pass_caliber(tmp_path):
    """F3 护栏：无结论行 ≠「比对完成」口径；attention 点亮越权出口"""
    fs = _SlotSelf(_seed_proj(tmp_path, "pf"))
    bmod.Bridge._on_cw_supervisor_done(fs, NO_CONCLUSION)
    assert fs._cw_supervisor_attention is True
    toasts = " | ".join(str(c) for c in fs.toast.calls)
    assert "结论行" in toasts and "衔接比对完成" not in toasts


def test_f3_needs_fix_no_autolock_and_attention(tmp_path, monkeypatch):
    """F3 护栏：需调整 → 无痕（不直通锁定）+ attention 亮 + 自动派单仍走（F2 compose）"""
    fs = _SlotSelf(_seed_proj(tmp_path, "pn"))
    fs.dispatched = []
    fs._dispatch_cw_rewrite = lambda num, d, report_ts="": fs.dispatched.append((num, d))
    monkeypatch.setattr(bmod.QTimer, "singleShot", lambda ms, fn: fn())
    bmod.Bridge._on_cw_supervisor_done(fs, "- 结论：需调整\n- 【改写指令】改开头。")
    assert not st.ensure_cw(st.load_state(fs.proj)).get("supervised", {}).get("2")
    assert fs._cw_supervisor_attention is True and len(fs.dispatched) == 1


def test_f3_force_lock_records_caliber(tmp_path):
    """F3 护栏：越权/跳过留痕分口径 skipped / overridden"""
    fs = _SlotSelf(_seed_proj(tmp_path, "pl"))
    fs._chapter_text = "正文。" * 2000          # 过字数闸
    fs._chapter_path = ""
    fs.confirmChapterLocked = lambda: None      # 锁定闸本身另有测，此处只看痕
    bmod.Bridge._on_cw_supervisor_error(fs, "401")
    bmod.Bridge.forceLockChapter(fs)
    assert st.ensure_cw(st.load_state(fs.proj))["supervised"]["2"].startswith("skipped:")
    fs2 = _SlotSelf(_seed_proj(tmp_path, "pl2"))
    fs2._chapter_text = "正文。" * 2000
    fs2._chapter_path = ""
    fs2.confirmChapterLocked = lambda: None
    fs2._cw_supervisor_attention = True         # 比对跑了但被无视
    bmod.Bridge.forceLockChapter(fs2)
    assert st.ensure_cw(st.load_state(fs2.proj))["supervised"]["2"].startswith("overridden:")


def test_supervisor_report_has_conclusion():
    """F3 判定函数：有结论行=True（通过/需调整都算解析成功），无=False"""
    assert co_dialogue.supervisor_report_has_conclusion(PASS) is True
    assert co_dialogue.supervisor_report_has_conclusion(NEEDS_FIX_NO_DIR) is True
    assert co_dialogue.supervisor_report_has_conclusion(NO_CONCLUSION) is False
    assert co_dialogue.supervisor_report_has_conclusion("") is False
    assert co_dialogue.supervisor_report_has_conclusion(None) is False


# ---------- C07：单元范围即时校验（A6）/ 阶段预告表（A8）/ 自动开章（A7）----------

class _EditorSelf(_SlotSelf):
    """带编辑器工作副本桩的 self（_autopen_prose_chapter → openChapter 所需）"""

    def __init__(self, proj):
        super().__init__(proj)
        from types import SimpleNamespace
        self._cur_num = 0
        self._chapter_path = ""
        self._chapter_text = ""
        self._chapter_findings = []
        self._editor_dirty = False
        self._working_text = ""
        self._last_edit_action = ""
        self._draft_timer = SimpleNamespace(stop=lambda: None)
        self.chapterTextChanged = _Sig()
        self.chapterFindingsChanged = _Sig()
        self.currentChapterChanged = _Sig()
        self.editorDirtyChanged = _Sig()
        self.openChapter = lambda num: bmod.Bridge.openChapter(self, num)


def _mk_chapter(proj, num):
    os.makedirs(os.path.join(str(proj), "正文"), exist_ok=True)
    path = os.path.join(str(proj), "正文", f"第{num:04d}章.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("正文内容。")
    return path


def test_cw_unit_range_span_warn_zero_request(tmp_path, monkeypatch):
    """A6 护栏：跨度 >10 即时 warn（登记照常落盘）；≤10 维持 ok 口径；全程零请求"""
    fs = _SlotSelf(_seed_proj(tmp_path, "span"))
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "SummarizeWorker", _Recorder)
    bmod.Bridge.setCwUnitRange(fs, 1, 15, "开篇单元")
    toasts = " | ".join(str(c) for c in fs.toast.calls)
    assert "超过 10 章" in toasts
    unit = st.ensure_cw(st.load_state(fs.proj)).get("unit", {})
    assert unit.get("start") == 1 and unit.get("target_end") == 15   # 登记仍落盘
    fs.toast.calls.clear()
    bmod.Bridge.setCwUnitRange(fs, 1, 10, "开篇单元")
    toasts = " | ".join(str(c) for c in fs.toast.calls)
    assert "单元已登记" in toasts and "超过" not in toasts


def test_cw_next_stage_preview_table():
    """A8 护栏：五张「下一步」预告逐字在表——键=推进后的新阶段，覆盖②③④⑤⑥"""
    table = bmod.CW_NEXT_PREVIEW
    assert set(table) == {"cw_core", "cw_outline", "cw_worldbook", "cw_unit", "cw_prose"}
    assert table["cw_core"] == "下一步「核心设定」：直接点「生成草案」让 Agent 先出一版，你再挑毛病"
    assert table["cw_outline"] == "下一步「剧情总纲」：同样可以先「生成草案」"
    assert table["cw_worldbook"] == (
        "下一步「世界书与正则」：这里的「正则」默认是必须成立的规则清单，不用懂正则表达式")
    assert table["cw_unit"] == "下一步「单元细纲」：先登记写作范围（已帮你预填第 1~10 章）"
    assert table["cw_prose"] == "下一步「正文写作」：稿纸已替你打开，点「生成草案」让写作 Agent 出第一版"


def test_cw_sum_done_advance_carries_preview(tmp_path):
    """A8 行为面：确定推进 toast 带下一站预告（cw_core → cw_outline）"""
    fs = _SlotSelf(_seed_proj(tmp_path, "prev"))
    _state = st.load_state(fs.proj)
    st.ensure_cw(_state)["stage"] = st.STAGE_CW_CORE
    st.save_state(fs.proj, _state)
    fs._write_cw_products = lambda stage, product: None
    fs._cw_open_product = lambda stage: None
    fs._cw_refresh = lambda: None
    fs.refreshQueue = lambda: None
    bmod.Bridge._on_cw_sum_done(fs, "## 题材定位\n（总结产物）")
    assert st.ensure_cw(st.load_state(fs.proj)).get("stage") == st.STAGE_CW_OUTLINE
    text = " | ".join(str(c) for c in fs.toast.calls)
    assert "已确定定稿" in text and "剧情总纲" in text and "生成草案" in text


def test_cw_autopen_prose_chapter(tmp_path):
    """A7 护栏：进正文阶段自动打开第 1 个未锁章；已有未锁章开着时不抢编辑器（返回 0）"""
    proj = _seed_proj(tmp_path, "autopen")
    _mk_chapter(proj, 1)
    _mk_chapter(proj, 2)
    project.set_chapter_locked(proj, 1, True)     # 第 1 章已锁 → 应开第 2 章
    fs = _EditorSelf(proj)
    assert bmod.Bridge._autopen_prose_chapter(fs) == 2
    assert fs._cur_num == 2
    # 已有未锁章开着：不扰动（返回 0，调用方不发回执 toast）
    fs2 = _EditorSelf(proj)
    fs2._cur_num = 2
    assert bmod.Bridge._autopen_prose_chapter(fs2) == 0
    assert fs2._cur_num == 2


def test_cw_validate_pass_autopens_with_toast(tmp_path):
    """A7 行为面：细纲校验 PASS → 进 prose + toast 交代稿纸已开（回执有据：advance 在函数内）"""
    fs = _EditorSelf(_seed_proj(tmp_path, "vdpass"))
    _state = st.load_state(fs.proj)
    st.ensure_cw(_state)["stage"] = st.STAGE_CW_UNIT
    st.save_state(fs.proj, _state)
    fs._cw_open_product = lambda stage: None
    fs._cw_sync_messages = lambda: None
    fs._cw_refresh = lambda: None
    fs.refreshQueue = lambda: None
    fs._autopen_prose_chapter = lambda: bmod.Bridge._autopen_prose_chapter(fs)
    bmod.Bridge._on_cw_validate_done(fs, "校验完成，未发现阻塞项。")
    assert st.ensure_cw(st.load_state(fs.proj)).get("stage") == st.STAGE_CW_PROSE
    toasts = " | ".join(str(c) for c in fs.toast.calls)
    assert "正文写作" in toasts and "稿纸" in toasts and fs._cur_num == 1


def test_wizard_conn_ready_summary():
    """A9 护栏：connReadySummary 三槽就绪清单——缺因复用 _slot_readiness 人话"""
    from app import config as cfg_mod
    b = bmod.Bridge()
    b.cfg = {"connections": [], "slots": {}}
    summary = b.connReadySummary
    assert [r["label"] for r in summary] == [cfg_mod.SLOT_LABELS[s] for s in cfg_mod.SLOT_ORDER]
    assert all(r["ready"] is False and r["reason"] for r in summary)
    b.cfg = {"connections": [{"id": "a", "name": "就绪", "base_url": "https://x/v1",
                              "api_key": "sk", "model": "m"}], "slots": {}}
    assert all(r["ready"] is True and r["reason"] == "" for r in b.connReadySummary)
