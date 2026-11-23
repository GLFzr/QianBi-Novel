# -*- coding: utf-8 -*-
"""0.20.4 Q2-b/Q2-d 回归：改写净增益闸 + 章内改写预算。

背景：三测 E5（ch4 30 发缝合怪 / ch6 扩写堆料 0.44）与 ICLR 2310.01798
（无外部信号自改写必然变差）——采纳判据从「非空+长度」升级为「本地指标净增益」。
"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from app.core import rewrite_gate, stages


class _Ctx:
    def __init__(self, cfg=None, proj=""):
        self.cfg = cfg or {}
        self.proj = proj
        self._rewrite_used = 0
        self._rewrite_budget_logged = False

    def log(self, level, msg):
        pass


# ---- 纯函数闸 ----

def test_gate_accepts_clean_rewrite():
    before = "陈默推开值班室的门，登记簿摊在桌上。他把钢笔放在窗口。" * 8
    after = before + "\n陈默的指尖在纸页边缘停了半秒，他抬眼看了看墙上的钟。"
    ok, reasons = rewrite_gate.gate_rewrite(before, after)
    assert ok, reasons


def test_gate_rejects_length_crash():
    before = "陈默推开值班室的门，登记簿摊在桌上。" * 40
    after = "陈默进门登记。"
    ok, reasons = rewrite_gate.gate_rewrite(before, after)
    assert not ok and any("长度骤减" in r for r in reasons)


def test_gate_rejects_pileup_repeat():
    """堆料：改写稿大段复读原稿已有句（四元组复现率劣化）。"""
    unit = "他缓缓抬起头，目光落在那扇半开的窗户上，窗外的雨还没有停。"
    before = unit + "值班员翻了一页登记簿，没有抬头。" + unit + "灯管闪了一下。"
    # after：把复读块再翻倍（复现率显著上升）
    after = (unit * 2) + "值班员翻了一页登记簿。" + (unit * 3)
    ok, reasons = rewrite_gate.gate_rewrite(before, after)
    assert not ok and any("复现" in r or "阻断" in r or "总量" in r for r in reasons), reasons


def test_gate_rejects_name_loss():
    before = "陈默把钢笔放在窗口。李医生翻了一页登记簿。陈默收回手。"
    after = "他把钢笔放在窗口。医生翻了一页登记簿。他收回手。" * 3
    ok, reasons = rewrite_gate.gate_rewrite(before, after, names=("陈默", "李医生"))
    assert not ok and any("角色丢失" in r for r in reasons)


def test_gate_failopen_without_names():
    """空名册（无账本的书）：名册断言跳过（fail-open），其余判据照常。"""
    before = "他把钢笔放在窗口，登记簿摊在桌上。" * 10
    after = before + "他又看了一眼。"
    ok, _ = rewrite_gate.gate_rewrite(before, after, names=())
    assert ok


# ---- stages 接线 ----

def test_rewrite_adopt_passthrough_for_ungated_phase():
    ctx = _Ctx()
    out = stages._rewrite_adopt(ctx, "enrich", 3, "原稿", "改稿")
    assert out == "改稿"   # enrich 不在 GATED_PHASES：透传


def test_rewrite_adopt_reject_returns_original():
    ctx = _Ctx()
    before = "陈默推开值班室的门，登记簿摊在桌上。" * 40
    crash = "陈默进门。"
    out = stages._rewrite_adopt(ctx, "deslop", 3, before, crash)
    assert out == before   # 拒收=回退原稿


def test_rewrite_adopt_zero_edit_passthrough():
    ctx = _Ctx()
    assert stages._rewrite_adopt(ctx, "trim", 3, "同一稿", "同一稿") == "同一稿"


def test_rewrite_budget_exhaustion(monkeypatch):
    ctx = _Ctx({"writing": {"rewrite_budget": 2}})
    ctx._rewrite_used = 2
    assert stages._rewrite_budget_exhausted(ctx, "deslop", 5) is True
    ctx2 = _Ctx({"writing": {"rewrite_budget": 2}})
    ctx2._rewrite_used = 1
    assert stages._rewrite_budget_exhausted(ctx2, "deslop", 5) is False
    # 缺省预算 6
    ctx3 = _Ctx()
    ctx3._rewrite_used = 5
    assert stages._rewrite_budget_exhausted(ctx3, "deslop", 5) is False


def test_rewrite_phase_budget_shortcircuits(monkeypatch):
    """预算耗尽时 _rewrite_phase 不发调用直接回原稿。"""
    ctx = _Ctx({"writing": {"rewrite_budget": 1}})
    ctx._rewrite_used = 1

    def _boom(*a, **k):  # 任何底层路径被触达即失败
        raise AssertionError("预算耗尽后不得发起改写调用")

    monkeypatch.setattr(stages, "_stream", _boom)
    monkeypatch.setattr(stages, "_session_ask", _boom)
    out = stages._rewrite_phase(ctx, None, "writing", "deslop",
                                "{prose}", {}, prose="原稿正文" * 50, num=7)
    assert out == "原稿正文" * 50
