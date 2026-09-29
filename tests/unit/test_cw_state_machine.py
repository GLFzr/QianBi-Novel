# -*- coding: utf-8 -*-
"""共写状态机护栏（C25：CW-G4~G7 + w4_cowrite §5.2 缺口 3/4/5/6）

段1（C25a）：
- 缺口4：同一状态两次 save 崩溃一致性（`_on_cw_sum_done` 定稿 save + 指针 save，
  第二次崩 → 盘上必须停在第一次的完整态，绝不留半份 JSON 或幽灵指针）；
- 缺口5 / CW-G7：打回级联 × 已锁定章 × 非空追踪 → 先出确认卡再动手；
  确认后归档清单=级联矩阵逐项、锁定标记原样、追踪/伏笔表原样、
  supervised/auto_fix 下游痕清除；
- CW-G4：锁定闸上限入账（超标不拦但 violations 必须有「超标 N%」账）
  + `_start_cw_outline_validation` 截断到最新批 ±2（缺口6：60 章书 prompt ≤ cap）。

段2（C25b）：CW-G5 取消代际化（缺口3 交叠完成序）+ OutlineBatchWorker
半提交对账回执 + CW-G6 反哺看门狗——见文件后半（追加）。
"""
import json
import os

import pytest

from app import project
from app.core import co_dialogue, co_writing, state as st
from app.core.co_writing import CoWriting
from app.ui import bridge as bmod


# ---------- 桩件 ----------

class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


class _Toast:
    def __init__(self):
        self.items = []

    def emit(self, level, msg):
        self.items.append((level, msg))


def make_proj(tmp_path, name="cwsm"):
    return project.create_project(str(tmp_path), name)


def full_products(proj, upto=4):
    """造出全部共写产物：五阶段产物 + 细纲 1..upto 章"""
    project.write_file(os.path.join(proj, "设定", "题材定位.md"),
                       "# 题材定位\n\n## 主要角色表\n| 角色 | 定位 |")
    project.write_file(os.path.join(proj, "大纲", "大纲.md"),
                       "# 全书大纲\n\n## 第1章-第30章 开篇单元\n预计总字数：100")
    project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n力量体系…")
    project.write_file(os.path.join(proj, "设定", "正则.md"),
                       "## 正则（逻辑约束规则集）\n- 规则：…｜level：must｜scope：全书")
    project.write_file(os.path.join(proj, "大纲", "单元总纲.md"), "## 单元总纲\n- 单元主题：开篇")
    for n in range(1, upto + 1):
        project.write_file(project.get_outline_path(proj, n),
                           f"### 第 {n} 章：事件{n}\n- 核心事件：事件{n}\n- 字数目标：3000")
        os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
        with open(os.path.join(proj, "正文", f"第{n:04d}章.md"), "w", encoding="utf-8") as f:
            f.write("正文内容。" * 100)


def mark_chapter_locked(proj, num):
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    path = os.path.join(proj, "正文", f"第{num:04d}章.md")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("正文内容。")
    project.set_chapter_locked(proj, num, True)


def seed_marks(state, nums):
    """supervised/auto_fix 痕（正文阶段逐章记账）+ 阶段钉在 cw_prose"""
    cw = st.ensure_cw(state)
    cw["mode"] = "cw"
    cw["stage"] = st.STAGE_CW_PROSE
    cw["supervised"] = {str(n): "08-31 20:00" for n in nums}
    cw["auto_fix"] = {str(n): 1 for n in nums}
    cw["last_outline_batch"] = [max(nums) - 1, max(nums)]
    return state


class _RbSelf:
    """_rollback_to / confirmRollbackCw 的轻量 self（不起 Qt 实例）"""

    def __init__(self, proj):
        self.proj = proj
        self._cw = CoWriting(proj)
        self._cw_view = st.STAGE_CW_PROSE
        self._pending_rollback = ""
        self.toast = _Toast()
        self.rollbackConfirm = _Sig()
        self.opened = []
        self.refreshed = 0
        # confirmRollbackCw 内部走 self._rollback_to——替身上补一条绑定
        self._rollback_to = lambda stage, confirmed=False: bmod.Bridge._rollback_to(
            self, stage, confirmed)

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)

    def _cw_open_product(self, stage):
        self.opened.append(stage)

    def _cw_refresh(self):
        self.refreshed += 1

    def refreshQueue(self):
        self.refreshed += 1

    def _get_cw_stage_key(self):
        return st.ensure_cw(st.load_state(self.proj)).get("stage", st.STAGE_CW_PROJECT)


# ---------- 缺口4：同一状态两次 save 崩溃一致性 ----------

class _SumSelf:
    """_on_cw_sum_done 的轻量 self（两次 save 流的主宰）"""

    def __init__(self, proj, stage):
        self.proj = proj
        self._cw = CoWriting(proj)
        self._cw_view = stage
        self.toast = _Toast()
        self.cwReportChanged = _Sig()
        self.autopen = 0
        self._cw_cancelled = False

    def refreshUsage(self):
        pass

    def _cw_save_state(self, state):
        st.save_state(self.proj, state)

    def _write_cw_products(self, stage, product):
        project.write_file(os.path.join(
            self.proj, st.CW_STAGE_PRODUCTS.get(stage, ["设定/题材定位.md"])[0]), product)

    def _get_cw_stage_key(self):
        return st.ensure_cw(st.load_state(self.proj)).get("stage", st.STAGE_CW_PROJECT)

    def _cw_open_product(self, stage):
        pass

    def _cw_refresh(self):
        pass

    def refreshQueue(self):
        pass

    def _autopen_prose_chapter(self):
        self.autopen += 1
        return 0


def test_two_saves_crash_consistency(tmp_path, monkeypatch):
    """缺口4：定稿 save 成功、指针 save 崩溃 → 盘上=第一次的完整可解释态。

    一致性判据：state.json 可加载、阶段指针仍是旧阶段（第二次 save 没成）、
    定稿产物与交接块已在盘上（第一次 save 成了）、项目目录不留 .tmp 尸体。
    """
    proj = make_proj(tmp_path, "crash2save")
    st.save_state(proj, {"cw": {"mode": "cw", "stage": st.STAGE_CW_CORE}})
    fs = _SumSelf(proj, st.STAGE_CW_CORE)
    text = ("主角欲望：活下去；金手指：能听懂雨声。"
            + "\n\n→ 下阶段交接\n- 关键事实：雨声=预警\n- 开放问题：代价未定")

    real_dump = json.dump
    calls = {"n": 0}

    def fake_dump(obj, fh, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("模拟第二次 save 中途崩溃")
        return real_dump(obj, fh, *a, **kw)

    monkeypatch.setattr(st.json, "dump", fake_dump)
    bmod.Bridge._on_cw_sum_done(fs, text)
    monkeypatch.undo()

    disk = st.load_state(proj)
    cw = st.ensure_cw(disk)
    assert cw.get("stage") == st.STAGE_CW_CORE, "指针 save 崩溃后盘上阶段必须仍是旧阶段"
    assert co_writing.CoWriting(proj).handoff_text(disk, st.STAGE_CW_OUTLINE).strip(), \
        "第一次 save（定稿+交接块）必须已落盘——不许两次 save 一起蒸发"
    leftovers = [n for n in os.listdir(proj) if n.endswith(".tmp")]
    assert not leftovers, f"崩溃后项目根残留临时文件：{leftovers}"
    assert any("阶段指针保存失败" in m for _l, m in fs.toast.items), \
        "崩在第二次 save 必须告诉用户「界面显示的下一阶段未落盘」"


def test_rollback_confirm_flow_with_locked_chapters(tmp_path):
    """缺口5 / CW-G7：3 锁定章 + 伏笔表非空 → 打回 cw_core 先出确认卡再动手。

    红判据：确认卡 detail 含锁定章名单与非空追踪；未确认前盘上零删除；
    确认后归档清单=级联矩阵逐项、锁定标记原样、伏笔表原样、
    supervised/auto_fix 痕（被删细纲对应的章）全部清除。
    """
    proj = make_proj(tmp_path, "rblocked")
    full_products(proj, upto=4)
    for n in (1, 2, 3):
        mark_chapter_locked(proj, n)
    with open(os.path.join(proj, "追踪", "伏笔.md"), "a", encoding="utf-8") as f:
        f.write("| 改命笔记的来历 | 1 | 已埋 | 12 | 悬念主线 |\n")
    st.save_state(proj, seed_marks(st.load_state(proj), [1, 2, 3, 4]))

    fs = _RbSelf(proj)
    cascade = st.CW_ROLLBACK_CASCADE[st.STAGE_CW_CORE]
    expect_gone = []
    for pat in cascade:
        if pat.startswith("细纲_"):
            expect_gone += [project.get_outline_path(proj, n) for n in range(1, 5)]
        else:
            expect_gone.append(os.path.join(proj, pat))

    # ① 未确认：先弹确认卡，盘上零删除
    bmod.Bridge._rollback_to(fs, st.STAGE_CW_CORE)
    assert len(fs.rollbackConfirm.calls) == 1, "级联删产物且存在锁定章/非空追踪：必须先弹确认卡"
    stage_key, detail = fs.rollbackConfirm.calls[0]
    assert stage_key == st.STAGE_CW_CORE
    assert list(detail.get("locked") or []) == [1, 2, 3], "确认卡必须点名已锁定章名单"
    assert detail.get("tracking_nonempty") is True, "伏笔表有登记必须如实上报"
    assert len(detail.get("files") or []) == len(expect_gone), "确认卡必须如实清点将删除的产物"
    for p in expect_gone:
        assert os.path.isfile(p), f"未确认就动手删了 {p}"
    assert st.ensure_cw(st.load_state(proj)).get("stage") == st.STAGE_CW_PROSE

    # ② 确认：级联归档 + 锁定/追踪原样 + 痕清除
    bmod.Bridge.confirmRollbackCw(fs)
    for p in expect_gone:
        assert not os.path.isfile(p), f"确认后 {p} 应已失效归档"
    roll_dir = os.path.join(proj, "pipeline_debug", "rollback")
    latest = sorted(d for d in os.listdir(roll_dir) if d.startswith("cw_cw_core_"))[-1]
    assert len(os.listdir(os.path.join(roll_dir, latest))) == len(expect_gone)
    for n in (1, 2, 3):
        assert project.is_chapter_locked(proj, n), f"第 {n} 章锁定标记不得被打回波及"
    with open(os.path.join(proj, "追踪", "伏笔.md"), encoding="utf-8") as f:
        assert "改命笔记的来历" in f.read(), "追踪/伏笔表不打回（确认卡已承诺）"
    cw = st.ensure_cw(st.load_state(proj))
    assert not cw.get("supervised") and not cw.get("auto_fix"), \
        "cw_core 打回删光全部细纲 → supervised/auto_fix 下游痕必须清空"
    assert cw.get("stage") == st.STAGE_CW_CORE
    assert any("4" in m or "细纲" in m for _l, m in fs.toast.items), "打回归执要说清失效规模"


def test_rollback_no_cascade_keeps_old_behavior(tmp_path):
    """cw_prose 打回（无级联产物）不弹卡：保持旧行为直接重议本章"""
    proj = make_proj(tmp_path, "rbprose")
    full_products(proj, upto=2)
    mark_chapter_locked(proj, 1)
    st.save_state(proj, seed_marks(st.load_state(proj), [1, 2]))
    fs = _RbSelf(proj)
    bmod.Bridge._rollback_to(fs, st.STAGE_CW_PROSE)
    assert fs.rollbackConfirm.calls == [], "无级联删除不弹确认卡（没有可失去的东西）"
    assert st.ensure_cw(st.load_state(proj)).get("stage") == st.STAGE_CW_PROSE
    marks = st.ensure_cw(st.load_state(proj)).get("supervised", {})
    assert marks, "无级联打回不清痕（产物一个没删）"


def test_rollback_preview_is_dry_run(tmp_path):
    """preview_rollback 纯预演：不删文件、不建归档目录、不动 state"""
    proj = make_proj(tmp_path, "rbprev")
    full_products(proj, upto=3)
    mark_chapter_locked(proj, 2)
    with open(os.path.join(proj, "追踪", "伏笔.md"), "a", encoding="utf-8") as f:
        f.write("| 测试伏笔 | 1 | 已埋 | 5 | - |\n")
    st.save_state(proj, seed_marks(st.load_state(proj), [2, 3]))
    cw = CoWriting(proj)
    detail = cw.preview_rollback(cw.load(), st.STAGE_CW_UNIT)
    assert detail["files"] == [project.get_outline_path(proj, n) for n in (1, 2, 3)]
    assert detail["locked"] == [2]
    assert detail["tracking_nonempty"] is True
    for n in (1, 2, 3):
        assert os.path.isfile(project.get_outline_path(proj, n)), "预演不许真删"
    assert not os.path.isdir(os.path.join(proj, "pipeline_debug", "rollback"))
    assert st.ensure_cw(st.load_state(proj)).get("stage") == st.STAGE_CW_PROSE


# ---------- CW-G4：锁定闸上限入账 ----------

class _LockSelf:
    """confirmChapterLocked 的轻量 self（锁定闸三条路径全走真闸，零 LLM）"""

    def __init__(self, proj, num, prose, target=3000):
        self.proj = proj
        self._cur_num = num
        self._chapter_path = ""
        self._chapter_text = prose
        self._working_text = ""
        self.cfg = {"writing": {"chapter_word_target": target},
                    "gates": {"word_block_on_review": True, "word_tolerance": 0.1}}
        self.toast = _Toast()
        self.lockBlocked = _Sig()
        self.lockBlockedDetail = _Sig()
        self.locked = []

    def _do_lock_chapter(self, forced=False, reasons=""):
        self.locked.append((forced, reasons))


def test_lock_gate_cap_accounting(tmp_path):
    """CW-G4：25k 字章锁定 → 不拦，但 lockBlockedDetail.violations 必须有「超标 N%」账"""
    proj = make_proj(tmp_path, "cap")
    full_products(proj, upto=1)
    prose = "超" * 25000
    fs = _LockSelf(proj, 1, prose)
    bmod.Bridge.confirmChapterLocked(fs)
    assert fs.locked and fs.locked[0][0] is False, "上限超标不拦锁定（作者主权），照常走确定"
    assert fs.lockBlocked.calls == [], "超标不弹拦截框（不拦）"
    assert len(fs.lockBlockedDetail.calls) == 1, "超标必须经 lockBlockedDetail 入账"
    _num, detail = fs.lockBlockedDetail.calls[0]
    viol = "\n".join(detail.get("violations") or [])
    assert "超标" in viol and "%" in viol, f"violations 缺超标入账：{viol!r}"
    assert "25000" in viol, "入账要带实际字数（对得上账本）"


def test_lock_gate_no_cap_noise_when_in_bounds(tmp_path):
    """CW-G4 零误报：达标章锁定 → 不发超标入账、不发拦截（旧行为原样）"""
    proj = make_proj(tmp_path, "okcap")
    full_products(proj, upto=1)
    fs = _LockSelf(proj, 1, "字" * 3000)
    bmod.Bridge.confirmChapterLocked(fs)
    assert fs.locked and fs.lockBlocked.calls == []
    assert fs.lockBlockedDetail.calls == [], "达标章不得发超标入账（看门狗零误报口径）"


# ---------- CW-G4：细纲校验输入截断（缺口6：prompt 长度界） ----------

class _FakeSig:
    def connect(self, *a):
        pass


class _CaptureWorker:
    """替身 ReviewOutlinesWorker：只记构造参数，绝不 start 真线程"""

    last_instance = None

    def __init__(self, cfg, proj, nums, unit, parent=None):
        self.cfg, self.proj, self.nums, self.unit = cfg, proj, list(nums), dict(unit)
        self.started = False
        self.done, self.error, self.finished = _FakeSig(), _FakeSig(), _FakeSig()
        _CaptureWorker.last_instance = self

    def start(self):
        self.started = True


def _val_self(proj):
    from types import SimpleNamespace
    fs = SimpleNamespace(
        proj=proj, _cw=CoWriting(proj), toast=_Toast(), _cw_sum_worker=None,
        cfg={}, _set_cw_busy=lambda v: None,
    )
    fs._cw_outline_nums = lambda state: bmod.Bridge._cw_outline_nums(fs, state)
    return fs


def test_outline_validation_window_truncated_to_latest_batch(tmp_path, monkeypatch):
    """CW-G4：60 章书校验输入截断到「最新批 ±2」——不随全书线性膨胀"""
    proj = make_proj(tmp_path, "win60")
    for n in range(1, 61):
        project.write_file(project.get_outline_path(proj, n),
                           f"### 第 {n} 章\n- 核心事件：事件{n}")
    state = st.load_state(proj)
    st.ensure_cw(state)["last_outline_batch"] = [56, 57, 58, 59, 60]
    st.save_state(proj, state)

    monkeypatch.setattr(co_dialogue, "ReviewOutlinesWorker", _CaptureWorker)
    fs = _val_self(proj)
    fs._on_cw_validate_done = lambda *a: None
    fs._on_cw_error = lambda *a: None
    bmod.Bridge._start_cw_outline_validation(fs)
    w = _CaptureWorker.last_instance
    assert w is not None and w.started
    assert min(w.nums) >= 54 and max(w.nums) <= 60, f"窗口越界：{w.nums}"
    assert len(w.nums) <= 9, f"批±2 窗口最多 9 章，实得 {len(w.nums)}"
    assert 1 not in w.nums, "全书第 1 章细纲不该进最新批的校验输入"

    # 全量模式：显式入口（full=True）才允许全书
    bmod.Bridge._start_cw_outline_validation(fs, True)
    assert len(_CaptureWorker.last_instance.nums) == 60


def test_outline_validation_prompt_cap_on_sixty_chapter_book(tmp_path):
    """缺口6：60 章夹具 → ReviewOutlinesWorker.last_prompt ≤ cap（不随书厚线性涨）"""
    proj = make_proj(tmp_path, "cap60")
    for n in range(1, 61):
        project.write_file(project.get_outline_path(proj, n),
                           f"### 第 {n} 章\n- 核心事件：OUTLINE_{n:03d}\n- 故事内容：{'细' * 1500}")
    project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n力量体系")
    project.write_file(os.path.join(proj, "设定", "正则.md"), "## 正则\n- 规则：x｜level：must｜scope：全书")

    class _FakeClient:
        def chat(self, prompt):
            return "校验完成，无阻塞"

    class _FakeRouter:
        def __init__(self, *a, **kw):
            pass

        def client(self, _slot):
            return _FakeClient()

    w = co_dialogue.ReviewOutlinesWorker({}, proj, list(range(54, 61)),
                                         {"start": 54, "target_end": 60}, router=_FakeRouter())
    w.run()
    assert w.last_prompt, "worker 未产出 prompt"
    assert "OUTLINE_001" not in w.last_prompt, "第 1 章细纲漏进校验输入（截断失效）"
    assert len(w.last_prompt) < 30000, \
        f"批±2 窗口 prompt 应 ≤3 万字符级，实得 {len(w.last_prompt)}"
