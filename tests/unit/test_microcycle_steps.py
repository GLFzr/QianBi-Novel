# -*- coding: utf-8 -*-
"""chapter_microcycle 七步 pin（B4/C02，B3 切段安全网）

钉住 stages.chapter_microcycle（stages.py:1547-2408）的步骤顺序与每步副作用：
  _ORDER = ["assemble", "draft", "enrich", "scan", "deslop", "review", "finalize"]
  8 个 ctx.step 落点：assemble(:1679) / draft(:1728) / enrich 扩写环(:1828) /
  enrich 压缩环(:1910) / scan(:1955) / deslop(:1989) / review 修复环(:2107) /
  finalize(:2220)。

每个测试都是行为快照：步骤序列 + 每步到达时刻的可观测副作用（草稿落盘时机、
断点记录的 step_done、审校票持久化、定稿落库与断点清除）。LLM 用相位队列假件
（test_chapter_resume 同思路）；除假 client 外全真身。
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app import project as pj
from app.core import state as st
from app.core import stages

# 七步 canon（与 stages.chapter_microcycle 内 _ORDER 逐字对应；B3 切段后不许变）
CANONICAL_ORDER = ["assemble", "draft", "enrich", "scan", "deslop", "review", "finalize"]


def test_step_constants_match_canonical_order():
    """STEP_* 常量即 _ORDER 的模块级锚——七步键名与顺序不许漂移"""
    assert [st.STEP_ASSEMBLE, st.STEP_DRAFT, st.STEP_ENRICH, st.STEP_SCAN,
            st.STEP_DESLOP, st.STEP_REVIEW, st.STEP_FINALIZE] == CANONICAL_ORDER


# ---------- 夹具 ----------

_BASE = "草稿内容这是一段完整的测试正文。"          # 16 字/句
_DRAFT = "## 第1章 开端\n\n" + _BASE * 40          # ≈645 字（目标 600 ±10% 内）
_DRAFT_BLOCKING = ("## 第1章 开端\n\n" + _BASE * 39
                   + "这不是巧合，而是命运的伏笔。")  # not-is 阻断句（≈643 字）
_PASS_REVIEW = (
    "===A_GOLDEN_OPEN=== pass 开篇有钩子 【原文引证：“%s”】\n"
    "===B_PAYOFF=== pass 爽点当章结算 【原文引证：“%s”】\n"
    "===C_FINGER=== pass 金手指合规\n"
    "===D_PLOT=== pass 因果自洽\n"
    "===E_CHARACTER=== pass 声口一致\n"
    "===F_HOOK=== pass 章尾有钩\n"
    "===TOTAL=== pass=6 marginal=0 fail=0\n"
    "===VERDICT===\nPASS\n===ITEMS===\n===END===\n"
) % (_BASE, _BASE)
_REJECT_REVIEW = (
    "===E_CHARACTER=== fail 执事台词与性格不符 【原文引证：“%s”】\n"
    "===VERDICT===\nREJECT\n===ITEMS===\n"
    "- [阻塞] E_CHARACTER 台词与性格不符（引证：%s）\n"
    "===END===\n"
) % (_BASE, _BASE)


class _PhaseQueueClient:
    """按相位出队的假 client：prose/enrich/trim/deslop/review_fix/review 各一条队列"""

    def __init__(self, responses=None):
        self.responses = {k: list(v) for k, v in (responses or {}).items()}
        self.calls = []                 # 相位序列

    def _next(self, phase):
        self.calls.append(phase)
        q = self.responses.get(phase)
        if not q:
            return ""
        return q.pop(0) if len(q) > 1 else q[0]

    def chat_stream(self, prompt, on_chunk=None, phase="", **kw):
        return self._next(phase)

    def chat(self, prompt, **kw):
        return self._next("chat")


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _PinCtx:
    """微循环假 ctx：记录 ctx.step 序列 + 每步到达时刻的副作用快照"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.logs = []
        self.last_prompt = ""
        self.review_raw = ""
        self.gen_trace = []
        self.gen_worldbooks = {}
        self.timeline = []              # [(num, step_key, 快照 dict)]

    # --- 调度器接口 ---
    def gate(self, key, summary="", chapter=0):
        return ""

    def consume_gate_idea(self):
        return ""

    def checkpoint(self):
        pass

    def step(self, num, key):
        self.timeline.append((num, key, self._snapshot()))

    def log(self, level, msg):
        self.logs.append(f"{level}|{msg}")

    def stream_chunk(self, text):
        pass

    def stream_stage(self, label):
        pass

    def auto_pause(self, reason):
        self.logs.append(f"auto_pause|{reason}")

    # --- 副作用快照 ---
    def _snapshot(self):
        cs = st.get_chapter_step(self.proj)
        return {"draft_on_disk": os.path.exists(pj.chapter_draft_path(self.proj, 1)),
                "step_done": cs.get("step_done", ""),
                "votes": len(cs.get("votes") or [])}


def _mk_proj(tmp_path):
    proj = str(tmp_path / "微循环书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(pj.get_outline_path(proj, 1),
                  "### 开端\n- 核心事件：少年拾到玉简")   # 无「第N章」引用：sanitize 惰性，断点指纹稳定
    return proj


def _cfg(target=600, **gates_extra):
    gates = {"review_enabled": False, "deslop_max_rounds": 1, "word_enrich_rounds": 1}
    gates.update(gates_extra)
    return {"gates": gates,
            "writing": {"chapter_word_target": target},
            "llm": {"max_retries": 0}}


def _steps(ctx):
    return [k for _n, k, _s in ctx.timeline]


def _snapshots(ctx, key):
    return [s for _n, k, s in ctx.timeline if k == key]


# ---------- 1. 全绿快路径：无扩写/无去味/审校关 ----------

def test_happy_path_step_order_and_side_effects(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_DRAFT]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert _steps(ctx) == ["assemble", "draft", "scan", "finalize"], \
        f"快路径步骤序列漂移：{_steps(ctx)}"
    assert {n for n, _k, _s in ctx.timeline} == {1}, "ctx.step 的章号必须恒为当前章"
    # 每步副作用快照
    assert _snapshots(ctx, "assemble")[0] == {"draft_on_disk": False, "step_done": "", "votes": 0}
    assert _snapshots(ctx, "draft")[0]["draft_on_disk"] is False, "草稿步开始时盘上无草稿"
    scan_snap = _snapshots(ctx, "scan")[0]
    assert scan_snap["draft_on_disk"] and scan_snap["step_done"] == "enrich", \
        "扫描步到达时草稿必须已落盘且断点记到 enrich（方案 H）"
    # 终态
    assert record["num"] == 1 and record.get("words", 0) > 0
    assert st.get_chapter_step(proj) == {}, "定稿后章内断点必须清除"
    chapters = pj.list_chapters(proj)
    assert len(chapters) == 1 and "草稿内容" in pj.read_file(chapters[0][2])
    assert pj.count_chars(pj.read_file(pj.chapter_draft_path(proj, 1))) > 0


# ---------- 2. 字数不足：enrich 步插入 draft 与 scan 之间 ----------

def test_word_gate_enrich_inserts_step(tmp_path):
    proj = _mk_proj(tmp_path)
    long_text = "## 第1章 开端\n\n" + _BASE * 40 + "补写的后续情节让这一章更完整。" * 88
    client = _PhaseQueueClient({"prose": [_DRAFT], "enrich": [long_text]})
    ctx = _PinCtx(proj, _cfg(target=2000), client)
    stages.chapter_microcycle(ctx, 1)

    assert _steps(ctx) == ["assemble", "draft", "enrich", "scan", "finalize"]
    assert any("字数不足" in lg and "自动扩写" in lg for lg in ctx.logs)
    assert _snapshots(ctx, "enrich")[0]["draft_on_disk"] is False, \
        "扩写环期间草稿尚未落盘（落盘点在字数闸门之后）"
    scan_snap = _snapshots(ctx, "scan")[0]
    assert scan_snap["draft_on_disk"] and scan_snap["step_done"] == "enrich"
    assert st.get_chapter_step(proj) == {}   # 收尾清除


# ---------- 3. 阻断级扫描命中：deslop 步插入 scan 之后 ----------

def test_deslop_step_fires_on_blocking_findings(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [_DRAFT]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert _steps(ctx) == ["assemble", "draft", "scan", "deslop", "finalize"]
    assert any("去味改写（第 1 轮）" in lg for lg in ctx.logs)
    # 去味后落库的是改写稿（无 not-is 句式）
    chapters = pj.list_chapters(proj)
    assert "这不是巧合" not in pj.read_file(chapters[0][2])
    assert st.get_chapter_step(proj) == {}


# ---------- 4. 审校 REJECT→修复→复检 PASS：review 步插入 ----------

def test_review_repair_step_and_vote_persistence(tmp_path):
    proj = _mk_proj(tmp_path)
    fake_conn = {"id": "rv", "name": "rv", "base_url": "https://example.test",
                 "api_key": "sk-test", "model": "test-model"}
    cfg = _cfg(review_enabled=True, review_votes=1, review_votes_recheck=1,
               review_max_rounds=3)
    cfg["connections"] = [fake_conn]
    cfg["slots"] = {"writing": "rv", "helper": "rv", "review": "rv"}
    client = _PhaseQueueClient({"prose": [_DRAFT],
                                "review": [_REJECT_REVIEW, _PASS_REVIEW],
                                "review_fix": [_DRAFT]})
    ctx = _PinCtx(proj, cfg, client)
    record = stages.chapter_microcycle(ctx, 1)

    assert _steps(ctx) == ["assemble", "draft", "scan", "review", "finalize"]
    assert any("6 维审校 REJECT" in lg and "修复（第 1 轮" in lg for lg in ctx.logs)
    review_snap = _snapshots(ctx, "review")[0]
    assert review_snap["votes"] == 1, "修复环启动时第一张 REJECT 票已持久化（vote_saver）"
    assert st.get_chapter_step(proj) == {}, "定稿后断点（含审校票）清除"


# ---------- 5. 断点续跑：step_done=deslop → 只走 finalize ----------

def test_resume_from_deslop_pins_remaining_steps(tmp_path):
    proj = _mk_proj(tmp_path)
    pj.write_file(pj.chapter_draft_path(proj, 1), _DRAFT)
    outline = pj.read_file(pj.get_outline_path(proj, 1))
    fp = hashlib.sha1(outline.encode("utf-8")).hexdigest()[:12]
    st.save_chapter_step(proj, 1, step_done="deslop", draft_path="正文/.drafts/第001章.md",
                         votes=[], outline_fp=fp)
    client = _PhaseQueueClient({"prose": [_DRAFT]})
    ctx = _PinCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)

    # 实测行为（快照钉死）：断点在 deslop 后，assemble/draft/deslop 全跳过，但
    # scan 的 ctx.step 信号无条件发出（:1955）——只是扫描工作被 skip_scan_deslop 跳过
    assert _steps(ctx) == ["scan", "finalize"], f"断点续跑步骤漂移：{_steps(ctx)}"
    assert any("跳过扫描与去味" in lg for lg in ctx.logs), "scan 步应标记为断点跳过（不重扫）"
    assert "prose" not in client.calls, "断点续跑不许重写草稿"
    assert any("断点续跑" in lg or "断点恢复" in lg for lg in ctx.logs)
    assert st.get_chapter_step(proj) == {}
    assert len(pj.list_chapters(proj)) == 1
