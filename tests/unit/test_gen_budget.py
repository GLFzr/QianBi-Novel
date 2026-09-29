# -*- coding: utf-8 -*-
"""D1 预算宪法回归（app/core/orchestrator.py GenBudget + app/llm/client.py 观察者）

覆盖：四轴超限各一断言（假 client 计数注入——事件经 client 观察者总线到账，与
生产同一入口）、熔断三连（auto_pause toast 信号 + gen_budget_exceeded 异常落账
走 C35 G5 通道 + 预算消耗回执）、正常章零误伤（出厂上限全绿跑 + 章界重置不带入）、
config 出厂键钉。全部离线零 API。
"""
import os
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app import config as cfg_mod
from app import project as pj
from app.core import ledger_view as lv
from app.core import state as st
from app.core import stages
from app.core.orchestrator import Orchestrator as _Orch
from app.core.orchestrator import GEN_BUDGET_DEFAULTS, GenBudget
from app.llm import client as llm_client


# ---------- 假件与夹具 ----------

@pytest.fixture(autouse=True)
def _lv_isolated():
    """告警落账登记的项目不跨用例泄漏（lv 是进程级单例）"""
    yield
    lv.set_project("", None)
    lv.reset()


def _proj(tmp_path, name="预算书", *, chapter=False):
    proj = str(tmp_path / name)
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(os.path.join(proj, "大纲", "大纲.md"), "## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n")
    pj.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n边陲小城，灵气稀薄。\n")
    if not chapter:
        pj.write_file(pj.get_outline_path(proj, 1), "### 第 1 章：开端\n- 核心事件：少年拾到玉简\n")
    state = st.load_state(proj)
    state["total_chapters"] = 1
    st.save_state(proj, state)
    return proj


def _orch(proj, gen_budget=None):
    cfg = {"writing": {}}
    if gen_budget is not None:
        cfg["writing"]["gen_budget"] = gen_budget
    return _Orch(proj, cfg)


@contextmanager
def window(orch, num=1):
    """章周期窗口（与 run() 同一对接线：注册观察者→重开窗口→finally 注销）"""
    llm_client.add_call_observer(orch._on_llm_call)
    orch._budget.reset(num)
    orch._budget_active = True
    try:
        yield orch
    finally:
        llm_client.remove_call_observer(orch._on_llm_call)
        orch._budget_active = False


class _TripCollector:
    """熔断观测：sig_auto_paused（→UI toast）+ 日志 + 异常台账查询"""

    def __init__(self, orch):
        self.paused, self.logs = [], []
        orch.sig_auto_paused.connect(self.paused.append)
        orch.sig_log.connect(lambda lvl, msg: self.logs.append((lvl, msg)))

    def anomalies(self, proj):
        state = st.load_state(proj)
        return [a for a in (state.get("anomalies") or [])
                if isinstance(a, dict) and a.get("rule") == "gen_budget_exceeded"]


# ---------- config 出厂键 ----------

def test_config_default_gen_budget():
    """writing.gen_budget 出厂=AINW 宪法原值（32 次/147456 tok/单次 32768/60 分钟），全部可配"""
    assert cfg_mod.DEFAULT_CONFIG["writing"]["gen_budget"] == dict(GEN_BUDGET_DEFAULTS)
    assert GEN_BUDGET_DEFAULTS == {"max_calls": 32, "max_total_tokens": 147456,
                                   "max_single_tokens": 32768, "max_minutes": 60}


def test_budget_configure_overrides_and_garbage():
    """cfg 覆盖生效；垃圾值/0/负=该轴不设限（诚实放行好过误杀）"""
    b = GenBudget({"max_calls": 5, "max_total_tokens": "abc", "max_minutes": -1})
    assert b.limits["max_calls"] == 5.0
    assert b.limits["max_total_tokens"] == 0.0, "垃圾值按不设限"
    assert b.limits["max_single_tokens"] == GEN_BUDGET_DEFAULTS["max_single_tokens"], "缺省键回出厂值"
    assert b.limits["max_minutes"] == 0.0, "负值=关"


# ---------- client 观察者总线（接入口）----------

def _boom(box):
    def _fn(ev):
        box.append(ev)
        raise RuntimeError("observer boom")
    return _fn


def test_client_observer_registry():
    """add/remove 幂等且可注销；观察者异常不穿回调用链（预算是观测件）"""
    got, boomed = [], []
    bad = _boom(boomed)
    llm_client.add_call_observer(got.append)
    llm_client.add_call_observer(got.append)   # 幂等
    llm_client.add_call_observer(bad)
    try:
        llm_client._emit_call_event({"tin": 7})
        assert got == [{"tin": 7}], "观察者收到事件原样字典（且只收一份）"
        assert boomed == [{"tin": 7}], "抛异常的观察者也被调用过"
        llm_client.remove_call_observer(got.append)
        llm_client._emit_call_event({"tin": 8})
        assert got == [{"tin": 7}], "注销后不再接收"
        assert len(boomed) == 2, "观察者异常被总线吞掉，不影响其他观察者"
    finally:
        llm_client.remove_call_observer(got.append)
        llm_client.remove_call_observer(bad)
    llm_client.remove_call_observer(got.append)   # 未注册再注销=静默
    assert got == [{"tin": 7}] and len(boomed) == 2


# ---------- 四轴超限（假 client 计数注入）----------

def test_axis_max_calls_trips(tmp_path):
    """次数轴：事件经真观察者总线到账，第 max_calls+1 次触发熔断三连"""
    proj = _proj(tmp_path)
    lv.set_project(proj, {})
    orch = _orch(proj, {"max_calls": 2})
    col = _TripCollector(orch)
    with window(orch, num=7):
        for _ in range(2):
            llm_client._emit_call_event({"tin": 10, "tout": 5})
        assert not orch._budget.tripped, "在限次数零误伤"
        llm_client._emit_call_event({"tin": 10, "tout": 5})
    assert orch._budget.tripped and orch._budget.violations == ["max_calls"]
    assert orch._budget.calls == 3
    assert col.paused and "预算宪法熔断" in col.paused[0], "auto_pause（sig_auto_paused→toast）"
    hits = col.anomalies(proj)
    assert hits and hits[0]["ch"] == 7, "异常落账进 state.anomalies（C35 G5 通道）"
    assert hits[0]["calls"] == 3 and hits[0]["violated"] == "max_calls"
    assert any("预算消耗报告" in msg for _lvl, msg in col.logs), "回执=预算消耗报告"


def test_axis_max_total_tokens_trips(tmp_path):
    """累计 tokens 轴：两次累计越过上限即熔断"""
    proj = _proj(tmp_path)
    lv.set_project(proj, {})
    orch = _orch(proj, {"max_total_tokens": 100})
    col = _TripCollector(orch)
    with window(orch, num=2):
        llm_client._emit_call_event({"tin": 60, "tout": 0})
        assert not orch._budget.tripped
        llm_client._emit_call_event({"tin": 0, "tout": 60})
    assert orch._budget.tripped and orch._budget.violations == ["max_total_tokens"]
    assert orch._budget.total_tokens == 120
    assert col.anomalies(proj) and col.paused


def test_axis_max_single_tokens_trips(tmp_path):
    """单次峰值轴：一发越限立即熔断（峰值口径=in+out）"""
    proj = _proj(tmp_path)
    lv.set_project(proj, {})
    orch = _orch(proj, {"max_single_tokens": 50})
    col = _TripCollector(orch)
    with window(orch, num=3):
        llm_client._emit_call_event({"tin": 30, "tout": 30})
    assert orch._budget.tripped and orch._budget.violations == ["max_single_tokens"]
    assert orch._budget.single_tokens == 60
    assert col.anomalies(proj) and col.paused


def test_axis_max_minutes_trips(tmp_path, monkeypatch):
    """时长轴：无调用也会越限——checkpoint 兜底裁决（不会因时长白挂一整章）"""
    proj = _proj(tmp_path)
    lv.set_project(proj, {})
    orch = _orch(proj, {"max_minutes": 60})
    paused = []
    monkeypatch.setattr(orch, "auto_pause", lambda reason: paused.append(reason),
                        raising=True)
    with window(orch, num=4):
        assert not orch._budget.exceeded()
        orch._budget.t0 = time.monotonic() - 3601   # 快进 60 分钟
        orch.checkpoint()   # D1：checkpoint 兜底裁决（auto_pause 已替身，不阻塞）
    assert orch._budget.tripped and orch._budget.violations == ["max_minutes"]
    assert paused and "max_minutes" in paused[0]


def test_axis_minutes_via_finish(tmp_path):
    """时长轴收口兜底：_budget_finish 末次裁决（观察者只评调用到账时刻）"""
    proj = _proj(tmp_path)
    lv.set_project(proj, {})
    orch = _orch(proj, {"max_minutes": 60})
    col = _TripCollector(orch)
    with window(orch, num=5):
        orch._budget.t0 = time.monotonic() - 3601
        orch._budget_finish()
    assert orch._budget.tripped and orch._budget.violations == ["max_minutes"]
    assert col.paused and col.anomalies(proj)
    assert not orch._budget_active, "收口后窗口必须关闭"


# ---------- 回执内容 ----------

def test_receipt_content(tmp_path):
    """回执=次数/tokens/分钟/章号 + 违限轴；人话版与字典版同源"""
    proj = _proj(tmp_path)
    orch = _orch(proj, {"max_calls": 1})
    orch._budget.reset(5)
    orch._budget.feed(tin=100, tout=50)
    orch._budget.feed(tin=10, tout=0)
    v = orch._budget.exceeded()
    assert v == ["max_calls"]
    rep = orch._budget.receipt(v)
    assert rep["ch"] == 5 and rep["calls"] == 2
    assert rep["total_tokens"] == 160 and rep["single_tokens"] == 150
    assert rep["violated"] == ["max_calls"] and rep["minutes"] >= 0
    assert rep["limits"]["max_calls"] == 1
    text = orch._budget.receipt_text(v)
    assert "第 5 章" in text and "2 次" in text and "160" in text
    assert "分钟" in text and "max_calls" in text


# ---------- 正常章零误伤 ----------

def test_normal_chapter_no_false_trip(tmp_path):
    """出厂上限下 10 发中等调用零误伤；窗口收口后事件不再计数、章界重置归零"""
    proj = _proj(tmp_path)
    orch = _orch(proj, None)   # 缺省=出厂宪法
    col = _TripCollector(orch)
    with window(orch, num=3):
        for _ in range(10):
            llm_client._emit_call_event({"tin": 5000, "tout": 2000})
        assert not orch._budget.tripped and orch._budget.exceeded() == []
        assert orch._budget.calls == 10 and orch._budget.total_tokens == 70000
        assert col.paused == [] and col.anomalies(proj) == []
        orch._budget_finish()
        llm_client._emit_call_event({"tin": 999999, "tout": 0})   # 窗口已关：不计次不熔断
        assert not orch._budget.tripped and orch._budget.calls == 10
    orch._budget.reset(4)   # 下一章窗口：计数归零，上一章消耗不带入
    assert orch._budget.calls == 0 and orch._budget.total_tokens == 0
    assert not orch._budget.tripped


# ---------- run() 级接线（观察者注册/注销 + 熔断不停摆）----------

def test_run_normal_chapter_counts_and_finishes(tmp_path, monkeypatch):
    """全绿跑：微循环内两次在限调用经真总线到账，完本零熔断零异常"""
    proj = _proj(tmp_path)

    def fake_micro(ctx, num, guidance="", ideas=None):
        for _ in range(2):
            llm_client._emit_call_event({"tin": 100, "tout": 50})
        pj.write_file(pj.get_chapter_path(proj, num, "开端"),
                      "## 第1章 开端\n\n" + "正文内容。" * 100)
        return {"num": num, "title": "开端", "words": 600,
                "review_blocking": 0, "status": "pass"}

    monkeypatch.setattr(stages, "chapter_microcycle", fake_micro, raising=True)
    orch = _orch(proj, None)
    col = _TripCollector(orch)
    finished = []
    orch.sig_finished.connect(finished.append)
    orch.run()
    assert finished == ["done"]
    assert col.paused == [], "正常章零误伤"
    assert orch._budget.calls == 2 and orch._budget.num == 1, "窗口内到账（run 注册观察者）"
    assert col.anomalies(proj) == []
    assert not orch._budget_active, "run 结束窗口必须关闭（finally 注销）"


class _ResumeOrchestrator(_Orch):
    """熔断自动续跑替身：人点「继续」的等价物——验证熔断暂停不卡死流水线"""

    def checkpoint(self):
        if self.paused:
            self.resume()
        super().checkpoint()


def test_run_budget_trip_midrun_pauses_then_completes(tmp_path, monkeypatch):
    """超限熔断：章内三连触发（toast 信号+异常台账+回执日志），续跑后仍能完本"""
    proj = _proj(tmp_path)

    def fake_micro(ctx, num, guidance="", ideas=None):
        for _ in range(3):   # 3 次调用 > max_calls=2：第 3 发在观察者处同步熔断
            llm_client._emit_call_event({"tin": 1000, "tout": 0})
        pj.write_file(pj.get_chapter_path(proj, num, "开端"),
                      "## 第1章 开端\n\n" + "重跑落库正文。" * 100)
        return {"num": num, "title": "开端", "words": 600,
                "review_blocking": 0, "status": "pass"}

    monkeypatch.setattr(stages, "chapter_microcycle", fake_micro, raising=True)
    orch = _ResumeOrchestrator(proj, {"writing": {"gen_budget": {"max_calls": 2}}})
    col = _TripCollector(orch)
    finished = []
    orch.sig_finished.connect(finished.append)
    orch.run()
    assert len(col.paused) == 1 and "预算宪法熔断" in col.paused[0]
    assert any("预算消耗报告" in msg and lvl == "error" for lvl, msg in col.logs), "回执必出"
    hits = col.anomalies(proj)
    assert hits and hits[0]["ch"] == 1, "gen_budget_exceeded 落账"
    assert hits[0]["calls"] == 3 and hits[0]["violated"] == "max_calls"
    assert finished == ["done"], "熔断暂停等人处置后续跑不卡死"
