# -*- coding: utf-8 -*-
"""离峰挂机（v4 分时价）：peak 时段挂起流水线，off-peak 自动续跑。

peak 定义（UTC，weekday 名义 0=周一）：周一至周五 01:00–04:00、06:00–10:00；
边界含头不含尾（01:00 整进入 peak，04:00 整退出），其余全部 off-peak
（DeepSeek v4 分时价：off-peak 全价减半）。纯逻辑模块，不依赖 Qt——
时钟与睡眠全部可注入，挂起循环由调用方（orchestrator 接线）驱动。
"""
import time
from datetime import datetime, timezone

PEAK_WINDOWS = [(1, 0, 4, 0), (6, 0, 10, 0)]   # (start_h, start_m, end_h, end_m)
PEAK_WEEKDAYS = {0, 1, 2, 3, 4}                # 周一~周五（UTC）

POLL_SECONDS = 30               # 挂起轮询间隔：每轮睡 30s 再看表
DEFAULT_MAX_WAIT_HOURS = 14.0   # 最长 peak→off-peak 间隔也远小于它，超过即视为异常


def _as_utc(dt):
    """aware 一律换算到 UTC；naive 视为 UTC（调用方负责给 UTC 口径）"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt


def _minute_of_day(dt) -> int:
    return dt.hour * 60 + dt.minute


def is_peak(dt) -> bool:
    """dt 为 aware/naive 的 UTC 时间（调用方负责给 UTC；naive 视为 UTC）。

    边界含头不含尾：01:00 整是 peak，04:00 整已经是 off-peak。
    """
    dt = _as_utc(dt)
    if dt.weekday() not in PEAK_WEEKDAYS:
        return False
    m = _minute_of_day(dt)
    return any(sh * 60 + sm <= m < eh * 60 + em for sh, sm, eh, em in PEAK_WINDOWS)


def next_offpeak(dt) -> "datetime":
    """给定时刻起，最近一个 off-peak 区间的开始时刻（用于日志倒计时）。

    已处于 off-peak 返回 dt 本身（无需等待）；处于 peak 返回所在窗口的
    结束整点（含头不含尾的边界，结束时刻即 off-peak 起点）。aware 输入
    先换算到 UTC，返回值保持 UTC 口径。
    """
    dt = _as_utc(dt)
    if not is_peak(dt):
        return dt
    m = _minute_of_day(dt)
    for sh, sm, eh, em in PEAK_WINDOWS:
        if sh * 60 + sm <= m < eh * 60 + em:
            return dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    return dt   # pragma: no cover —— is_peak 为真时上方必命中


def _default_clock():
    return datetime.now(timezone.utc)


def _wait_line(cur, waited_seconds: float) -> str:
    eta = next_offpeak(cur).strftime("%H:%M")
    return "离峰挂机中：当前为 peak 时段，预计 %s 续跑（已等 %d 分钟）" % (
        eta, int(waited_seconds // 60))


def wait_until_offpeak(log=None, stop_check=None, sleep=time.sleep,
                       clock=None, max_wait_hours: float = 14.0) -> bool:
    """在 peak 期间阻塞等待，直到进入 off-peak 或 stop_check() 为真。

    - clock: 无参 -> 当前 UTC datetime（默认 lambda: datetime.now(timezone.utc)）
    - 每轮睡 30s（sleep 可注入便于测试；stop_check 每轮先查，为真即刻让路）
    - 进入等待与跨入新的一天时各 log 一条等待文案（log 为 callable(str) 或 None）
    - 等待总时长超过 max_wait_hours 视为异常状态：log 警告后直接返回 False
      （不无限挂死；真实时钟下等待时长按累计睡眠计，注入时钟下按轮数推进）
    - 返回 True=已到 off-peak（含进入时就不在 peak）；False=被 stop 或超时
    """
    clock = clock or _default_clock
    now = clock()
    if not is_peak(now):
        return True
    last_day = now.date()
    waited = 0.0
    if log:
        log(_wait_line(now, 0.0))
    while True:
        if stop_check and stop_check():
            return False
        if waited >= max_wait_hours * 3600:
            if log:
                log("离峰挂机异常：已等待超过 %.1f 小时仍在 peak（时钟或分时配置异常），"
                    "放弃等待直接续跑" % max_wait_hours)
            return False
        sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        now = clock()
        if not is_peak(now):
            return True
        # peak 窗口最晚 10:00 UTC 结束、最早次日 01:00 才恢复，正常等待不会跨天；
        # 这条是防御分支（如用户手动改了窗口表），跨天时补一条进度文案。
        if now.date() != last_day:
            last_day = now.date()
            if log:
                log(_wait_line(now, waited))
