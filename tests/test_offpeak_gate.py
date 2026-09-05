# -*- coding: utf-8 -*-
"""离峰挂机门（app/core/offpeak.py）：is_peak 边界 + wait_until_offpeak 注入时钟测试

不触网、不真睡：sleep/clock/log 全部注入。运行：
    python -m pytest tests/test_offpeak_gate.py -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())

from app.core import offpeak

# 固定参照日（UTC）：2026-09-07=周一、09-11=周五、09-12/13=周末
MON, FRI, SAT, SUN = 7, 11, 12, 13


def utc(day, h, m=0, s=0):
    return datetime(2026, 9, day, h, m, s, tzinfo=timezone.utc)


class FakeClock:
    """可调用时钟：每次读表返回当前值并快进 step 秒（模拟时间流逝）"""

    def __init__(self, start, step_seconds):
        self.now = start
        self.step = timedelta(seconds=step_seconds)
        self.calls = 0

    def __call__(self):
        cur = self.now
        self.calls += 1
        self.now += self.step
        return cur


def test_is_peak_weekday_boundaries():
    # 01:00–04:00 窗口：含头不含尾
    assert offpeak.is_peak(utc(MON, 0, 59)) is False
    assert offpeak.is_peak(utc(MON, 1, 0)) is True
    assert offpeak.is_peak(utc(MON, 1, 0, 0) + timedelta(seconds=1)) is True
    assert offpeak.is_peak(utc(MON, 3, 59)) is True
    assert offpeak.is_peak(utc(MON, 3, 59, 59)) is True
    assert offpeak.is_peak(utc(MON, 4, 0)) is False
    # 06:00–10:00 窗口
    assert offpeak.is_peak(utc(MON, 5, 59)) is False
    assert offpeak.is_peak(utc(MON, 6, 0)) is True
    assert offpeak.is_peak(utc(MON, 9, 59)) is True
    assert offpeak.is_peak(utc(MON, 9, 59, 59)) is True
    assert offpeak.is_peak(utc(MON, 10, 0)) is False
    # 窗口外的时段
    assert offpeak.is_peak(utc(MON, 23, 30)) is False
    assert offpeak.is_peak(utc(MON, 12, 0)) is False


def test_is_peak_weekend_all_day_offpeak():
    for day in (SAT, SUN):
        for h, m in ((0, 59), (1, 0), (2, 0), (4, 0), (5, 0), (6, 0),
                     (9, 59), (10, 0), (12, 0), (23, 59)):
            assert offpeak.is_peak(utc(day, h, m)) is False, (day, h, m)
    # 周五凌晨照常是 peak，周五 23:xx 已 off-peak
    assert offpeak.is_peak(utc(FRI, 2, 0)) is True
    assert offpeak.is_peak(utc(FRI, 23, 30)) is False


def test_is_peak_accepts_naive_and_non_utc():
    assert offpeak.is_peak(datetime(2026, 9, 7, 2, 0)) is True          # naive 视为 UTC
    assert offpeak.is_peak(datetime(2026, 9, 12, 2, 0)) is False        # 周六 naive
    # 东八区 aware 时间：UTC 周一 02:00 = 北京时间周一 10:00，仍按 UTC 口径判定
    cst = timezone(timedelta(hours=8))
    assert offpeak.is_peak(datetime(2026, 9, 7, 10, 0, tzinfo=cst)) is True


def test_next_offpeak():
    assert offpeak.next_offpeak(utc(MON, 1, 0)) == utc(MON, 4, 0)    # 第一窗口尾
    assert offpeak.next_offpeak(utc(MON, 6, 30)) == utc(MON, 10, 0)  # 第二窗口尾
    assert offpeak.next_offpeak(utc(MON, 5, 0)) == utc(MON, 5, 0)    # 已在 off-peak：就是现在
    assert offpeak.next_offpeak(utc(SAT, 2, 0)) == utc(SAT, 2, 0)    # 周末全天 off-peak


def test_wait_returns_true_after_offpeak_arrives():
    sleeps, logs = [], []
    clock = FakeClock(utc(MON, 6, 30), step_seconds=1800)   # 每次读表快进 30 分钟
    ok = offpeak.wait_until_offpeak(log=logs.append, stop_check=lambda: False,
                                    sleep=sleeps.append, clock=clock)
    assert ok is True
    assert sleeps and all(s == offpeak.POLL_SECONDS for s in sleeps)
    # 06:30 起等到 10:00 边界：7 轮快进（07:00…09:30…10:00 读表）
    assert clock.now == utc(MON, 10, 30)
    assert logs, "进入等待时应 log 一条"
    assert logs[0] == "离峰挂机中：当前为 peak 时段，预计 10:00 续跑（已等 0 分钟）"
    assert len(logs) == 1   # 未跨天，不再补文案


def test_wait_immediate_true_when_already_offpeak():
    sleeps, logs = [], []
    ok = offpeak.wait_until_offpeak(log=logs.append, sleep=sleeps.append,
                                    clock=lambda: utc(MON, 5, 0))
    assert ok is True
    assert sleeps == [] and logs == []   # 不在 peak：不等待也不 log


def test_wait_stop_check_returns_false_without_sleeping():
    sleeps, logs = [], []
    ok = offpeak.wait_until_offpeak(log=logs.append, stop_check=lambda: True,
                                    sleep=sleeps.append, clock=lambda: utc(MON, 2, 0))
    assert ok is False
    assert sleeps == []


def test_wait_stop_check_mid_wait():
    sleeps = []
    state = {"n": 0}

    def stop_after_two():
        state["n"] += 1
        return state["n"] > 2

    ok = offpeak.wait_until_offpeak(stop_check=stop_after_two, sleep=sleeps.append,
                                    clock=FakeClock(utc(MON, 6, 0), step_seconds=60))
    assert ok is False
    assert len(sleeps) == 2   # 停止请求即刻让路，不多睡


def test_wait_timeout_small_cap():
    # cap=0.01h=36s：睡满一轮 30s 未到，第二轮前超 36s → 警告并返回 False
    sleeps, logs = [], []
    ok = offpeak.wait_until_offpeak(log=logs.append, max_wait_hours=0.01,
                                    sleep=sleeps.append,
                                    clock=FakeClock(utc(MON, 2, 0), step_seconds=30))
    assert ok is False
    assert len(sleeps) == 2
    assert any("超过" in m and "放弃等待" in m for m in logs)


def test_wait_timeout_default_cap_always_peak():
    # 恒为 peak 的时钟 + 默认 14h 上限：1680 轮（50400s）后放弃，不无限挂死
    sleeps, logs = [], []
    ok = offpeak.wait_until_offpeak(log=logs.append, sleep=sleeps.append,
                                    clock=lambda: utc(MON, 2, 0))
    assert ok is False
    assert len(sleeps) == int(14 * 3600 / offpeak.POLL_SECONDS)
    assert any("放弃等待" in m for m in logs)


def test_log_none_is_tolerated():
    ok = offpeak.wait_until_offpeak(log=None, sleep=lambda s: None,
                                    clock=FakeClock(utc(MON, 6, 30), step_seconds=3600))
    assert ok is True
