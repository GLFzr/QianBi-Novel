# -*- coding: utf-8 -*-
"""质量闸门：字数校验、AI味扫描分流、失败策略三决策"""
from app import config as cfg_mod
from app.core import gates


class MockCtx:
    def __init__(self, strategy=None):
        self.cfg = {}
        if strategy:
            self.cfg = {"gates": {"strategy": strategy}}
        self.logs = []
        self.paused = []

    def log(self, level, msg):
        self.logs.append((level, msg))

    def auto_pause(self, msg):
        self.paused.append(msg)


# ---- 字数 ----

def test_check_words_boundary():
    text = "字" * 2700
    ok, actual = gates.check_words(text, target=3000, tolerance=0.1)
    assert ok is True and actual == 2700
    ok2, _ = gates.check_words("字" * 2699, target=3000, tolerance=0.1)
    assert ok2 is False


def test_check_word_bounds_both_sides():
    low_ok, high_ok, actual = gates.check_word_bounds("字" * 3000, 3000)
    assert low_ok and high_ok and actual == 3000
    low_ok2, _, _ = gates.check_word_bounds("字" * 2000, 3000)   # 低于 -20%
    assert low_ok2 is False
    _, high_ok3, _ = gates.check_word_bounds("字" * 4000, 3000)  # 高于 +20%
    assert high_ok3 is False


# ---- AI 味扫描分流 ----

def test_scan_deslop_splits_blocking_advisory():
    # 确定性句式 → blocking；认知告知为密度型（≥3 处）→ advisory
    text = "他不是愤怒，而是绝望。他知道真相。她明白一切。我意识到太迟了。"
    blocking, advisory = gates.scan_deslop(text)
    b_rules = {f.rule for f in blocking}
    assert "not-is-comparison" in b_rules
    a_rules = {f.rule for f in advisory}
    assert "telling-cognition" in a_rules


# ---- GateResult ----

def test_gate_result_to_record():
    gr = gates.GateResult()
    gr.word_actual = 3200
    gr.blocking_findings = [1, 2]
    gr.advisory_findings = [1]
    gr.review_blocking = ["x"]
    gr.final_status = "needs_fix"
    rec = gr.to_record()
    assert rec["words"] == 3200
    assert rec["deslop_blocking"] == 2
    assert rec["deslop_advisory"] == 1
    assert rec["review_blocking"] == 1
    assert rec["status"] == "needs_fix"


# ---- 修复失败策略三决策 ----

def test_resolve_failed_mark_continue_logs_and_continues():
    ctx = MockCtx()  # 缺省策略 = mark_continue
    gr = gates.GateResult()
    gates.resolve_failed(ctx, "去味 2 轮后仍有 3 处阻断", gr)
    assert gr.final_status == "needs_fix"
    assert ctx.paused == []
    assert any(lvl == "warn" for lvl, _ in ctx.logs)


def test_resolve_failed_strict_pauses():
    ctx = MockCtx(strategy=cfg_mod.GATE_STRICT)
    gr = gates.GateResult()
    gates.resolve_failed(ctx, "审校 2 轮仍 REJECT", gr)
    assert gr.final_status == "needs_fix"
    assert len(ctx.paused) == 1
    assert "人工处理" in ctx.paused[0]
