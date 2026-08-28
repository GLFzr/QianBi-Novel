# -*- coding: utf-8 -*-
"""质量闸门：字数校验 + 本地 AI 味扫描 → 裁决微循环走向

策略（config.gates.strategy）：
- mark_continue（默认）：修复失败 → 标待修继续写
- strict：修复失败 → 自动暂停等人（auto_pause）
"""
from .. import config as cfg_mod
from .. import deslop, project


class GateResult:
    def __init__(self):
        self.word_ok = True
        self.word_actual = 0
        self.word_target = 0
        self.need_enrich = False
        self.blocking_findings = []
        self.advisory_findings = []
        self.deslop_rounds_used = 0
        self.review_blocking = []       # 审校阻塞问题（文本）
        self.review_advisory = []        # 审校建议（文本）
        self.review_verdict = ""         # 最终审核 Agent 总评：PASS/PASS_WITH_NOTES/REJECT/REJECT_HARD
        self.review_rounds_used = 0
        self.final_status = "pass"   # pass / needs_fix

    @property
    def blocking_count(self) -> int:
        return len(self.blocking_findings)

    @property
    def advisory_count(self) -> int:
        return len(self.advisory_findings)

    def to_record(self) -> dict:
        return {
            "words": self.word_actual,
            "deslop_blocking": self.blocking_count,
            "deslop_advisory": self.advisory_count,
            "review_blocking": len(self.review_blocking),
            "status": self.final_status,
        }


def check_words(text: str, target: int, tolerance: float = 0.1) -> tuple:
    """返回 (ok, actual)；actual 低于 target*(1-tolerance) 则不达标"""
    actual = project.count_chars(text)
    return actual >= int(target * (1 - tolerance)), actual


def check_word_bounds(text: str, target: int, tolerance: float = 0.2) -> tuple:
    """字数双界检查：返回 (low_ok, high_ok, actual)

    low_ok  = actual >= target*(1-tolerance)         （不足需扩写）
    high_ok = actual <= target*(1+tolerance)         （超出需压缩）
    tolerance 默认 0.2：超 20% 视为超标（与写作 prompt 口径一致）。
    """
    actual = project.count_chars(text)
    low_ok = actual >= int(target * (1 - tolerance))
    high_ok = actual <= int(target * (1 + tolerance))
    return low_ok, high_ok, actual


def scan_deslop(text: str) -> tuple:
    """返回 (blocking_findings, advisory_findings)"""
    findings = deslop.scan_text(text)
    blocking = [f for f in findings if f.level == "blocking"]
    advisory = [f for f in findings if f.level == "advisory"]
    return blocking, advisory


def resolve_failed(ctx, reason: str, gr: GateResult):
    """修复（去味/审校）轮次耗尽仍失败时，按策略裁决。

    - mark_continue：标待修，继续写
    - strict：自动暂停等人处理（用户点「继续」后仍按待修继续）
    """
    gr.final_status = "needs_fix"
    strategy = ctx.cfg.get("gates", {}).get("strategy", cfg_mod.GATE_MARK_CONTINUE)
    if strategy == cfg_mod.GATE_STRICT:
        ctx.auto_pause(f"{reason}，自动修复后仍未通过，请人工处理")
    else:
        ctx.log("warn", f"{reason}，已标记「待修」，继续写作（可在章节详情中人工修改）")
