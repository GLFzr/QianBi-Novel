# -*- coding: utf-8 -*-
"""C17 G1 字数预算断路器（卡8-G1=QW-E1）+ trim 最低压缩量守卫

- 断路器：首稿字数 > 目标×(1+容差)×N（writing.word_overflow_breaker，出厂 3）→
  跳过 trim/deslop/审校直转 need_human，record 带 word_overflow，事件账留痕；
  strict 策略走 resolve_failed→auto_pause。
- trim 守卫：压缩量 < 应压缩量（pre×cut_pct%）一半的压缩稿拒绝采纳（等长稿被拒）；
  trim_over 打标 warn→error。
- 正常稿零行为变化（无断路、无守卫拒绝，步骤序列与 0.21 逐项一致）。

LLM 用相位队列假件（test_microcycle_steps 同思路）；除假 client 外全真身。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import json

from app import project as pj
from app.core import state as st
from app.core import stages

_BASE = "草稿内容这是一段完整的测试正文。"          # 16 字/句
_DRAFT = "## 第1章 开端\n\n" + _BASE * 40          # ≈645 字（目标 600 ±10% 内）
_TEN_X = "## 第1章 开端\n\n" + _BASE * 400         # ≈6405 字（目标 600 → 10 倍稿）


class _PhaseQueueClient:
    """按相位出队的假 client：记录全部相位调用序（断路=后续 rewrite/deslop/review 零调用）"""

    def __init__(self, responses=None):
        self.responses = {k: list(v) for k, v in (responses or {}).items()}
        self.calls = []

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
    """微循环假 ctx（test_microcycle_steps 同构）"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.logs = []
        self.last_prompt = ""
        self.review_raw = ""
        self.paused = []
        self.timeline = []

    def gate(self, key, summary="", chapter=0):
        return ""

    def consume_gate_idea(self):
        return ""

    def checkpoint(self):
        pass

    def step(self, num, key):
        self.timeline.append((num, key))

    def log(self, level, msg):
        self.logs.append(f"{level}|{msg}")

    def stream_chunk(self, text):
        pass

    def stream_stage(self, label):
        pass

    def auto_pause(self, reason):
        self.paused.append(reason)


def _mk_proj(tmp_path, name="断路器书"):
    proj = str(tmp_path / name)
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(pj.get_outline_path(proj, 1), "### 开端\n- 核心事件：少年拾到玉简")
    return proj


def _cfg(target=600, **gates_extra):
    gates = {"review_enabled": False, "deslop_max_rounds": 1, "word_enrich_rounds": 1}
    gates.update(gates_extra)
    return {"gates": gates,
            "writing": {"chapter_word_target": target},
            "llm": {"max_retries": 0}}


def _steps(ctx):
    return [k for _n, k in ctx.timeline]


def _events(proj):
    path = os.path.join(proj, "追踪", "session_events.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


# ---------- 1. 10 倍稿：断路器触发，rewrite/deslop/review 调用数=0 ----------

def test_ten_fold_draft_skips_downstream(tmp_path):
    proj = _mk_proj(tmp_path)
    # 假件对 trim/deslop 都回 10 倍稿：若断路器失效，trim 循环会烧满 2 轮
    client = _PhaseQueueClient({"prose": [_TEN_X], "trim": [_TEN_X], "deslop": [_TEN_X]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert "enrich" not in client.calls and "trim" not in client.calls \
        and "deslop" not in client.calls and "review" not in client.calls, \
        f"断路后不许有任何下游改写/审校调用：{client.calls}"
    assert _steps(ctx) == ["assemble", "draft", "finalize"], f"步骤漂移：{_steps(ctx)}"
    assert any("G1 字数断路器" in lg and lg.startswith("error|") for lg in ctx.logs)
    # 直转人工 + 事件账留痕 + 记录携带 word_overflow
    assert st.is_chapter_need_human(st.load_state(proj), 1), "必须标记 chapter_need_human"
    evs = [e for e in _events(proj) if e.get("event") == "word_overflow"]
    assert len(evs) == 1 and evs[0]["ch"] == 1 and evs[0]["actual"] > 6000
    assert record.get("word_overflow") is True and record.get("status") == "needs_fix"
    assert record.get("words", 0) > 6000


# ---------- 2. strict 策略：断路器 → auto_pause ----------

def test_ten_fold_draft_strict_auto_pauses(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_TEN_X]})
    ctx = _PinCtx(proj, _cfg(strategy="strict"), client)
    stages.chapter_microcycle(ctx, 1)

    assert ctx.paused and "字数严重超标" in ctx.paused[0], "strict 必须经 resolve_failed 自动暂停"
    assert "trim" not in client.calls and "deslop" not in client.calls


# ---------- 3. 正常稿零行为变化 ----------

def test_normal_draft_zero_behavior_change(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_DRAFT]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert _steps(ctx) == ["assemble", "draft", "scan", "finalize"], f"快路径漂移：{_steps(ctx)}"
    assert not any("断路器" in lg for lg in ctx.logs)
    assert "word_overflow" not in record
    assert record.get("status") == "pass" and not ctx.paused
    assert not [e for e in _events(proj) if e.get("event") == "word_overflow"]
    # 645 字在断路器上限（600×1.1×3=1980）之下、达标窗之内
    assert 540 <= record.get("words", 0) <= 660


# ---------- 4. 等长 trim 稿被最低压缩量守卫拒绝 ----------

def test_trim_equal_length_rejected(tmp_path):
    proj = _mk_proj(tmp_path)
    # 1.5 倍稿（990 字 > 目标 600×1.1=660 → 进 trim；< 断路器上限 1980 不触发断路）
    over = "## 第1章 开端\n\n" + _BASE * 60
    client = _PhaseQueueClient({"prose": [over], "trim": [over]})   # trim 回等长稿=压缩量 0
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    # 等长稿两轮都被拒（0 < 应压缩 297 字的一半），最终 trim_over 打标（error 级）
    assert client.calls.count("trim") == 2, f"等长稿应两次进 trim：{client.calls}"
    assert any("压缩稿拒绝采纳" in lg for lg in ctx.logs)
    assert any(lg.startswith("error|") and "trim_over" in lg for lg in ctx.logs), \
        "trim_over 打标必须升 error 级"
    evs = [e for e in _events(proj) if e.get("event") == "trim_over"]
    assert len(evs) == 2, "两轮守卫拒绝各记一条 trim_over"
    # 拒绝后正文保持原稿（未被等长"压缩稿"污染），照常走 scan/finalize
    # （trim 复用 enrich 步信号，两轮=两个 enrich step，test_microcycle_steps 同款）
    assert _steps(ctx) == ["assemble", "draft", "enrich", "enrich", "scan", "finalize"]
    assert record.get("words", 0) > 900 and not record.get("word_overflow")
    assert not st.is_chapter_need_human(st.load_state(proj), 1), "trim 守卫不标人工"


# ---------- 5. 达标压缩稿照常采纳（守卫不误伤正常压缩） ----------

def test_trim_valid_shortening_adopted(tmp_path):
    proj = _mk_proj(tmp_path)
    over = "## 第1章 开端\n\n" + _BASE * 60                    # 990 字，应压缩 ≈297 字
    shortened = "## 第1章 开端\n\n" + _BASE * 40               # 645 字，压缩 345 ≥ 297/2
    client = _PhaseQueueClient({"prose": [over], "trim": [shortened]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert client.calls.count("trim") == 1 and not any("拒绝采纳" in lg for lg in ctx.logs)
    assert any("压缩后" in lg and "达标" in lg for lg in ctx.logs)
    assert 540 <= record.get("words", 0) <= 660


# ---------- 6. 断路器阈值可配：N=5 时 3.2 倍稿放行、出厂 3 时同稿断路 ----------

def test_breaker_threshold_configurable(tmp_path):
    three_x = "## 第1章 开端\n\n" + _BASE * 130               # ≈2085 字 = 3.4 倍稿
    cfg = _cfg()
    cfg["writing"]["word_overflow_breaker"] = 5               # 上限 = 600×1.1×5 = 3300
    proj = _mk_proj(tmp_path, "阈值书N5")
    ctx = _PinCtx(proj, cfg, _PhaseQueueClient({"prose": [three_x], "trim": [three_x]}))
    stages.chapter_microcycle(ctx, 1)

    assert not any("断路器" in lg for lg in ctx.logs), "N=5 时 3.2 倍稿不许断路"
    assert "word_overflow" not in _events(proj) or \
        not [e for e in _events(proj) if e.get("event") == "word_overflow"]
    # 对照组：同稿出厂 N=3（上限 1980）→ 断路，trim 零调用
    proj2 = _mk_proj(tmp_path, "阈值书出厂")
    ctx2 = _PinCtx(proj2, _cfg(), _PhaseQueueClient({"prose": [three_x]}))
    stages.chapter_microcycle(ctx2, 1)
    assert any("断路器" in lg for lg in ctx2.logs)
    assert [e for e in _events(proj2) if e.get("event") == "word_overflow"]
