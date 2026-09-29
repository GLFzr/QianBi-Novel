# -*- coding: utf-8 -*-
"""台账派生视图与告警裁决（C35 G4/G5 + C39 章级成本视图；S6a 自 app/usage.py 下沉）

- 章级相位/成本内存视图：usage.record() 实时喂入（observe）+ usage._load() 从盘上
  台账回放（rebuild）——chapter_accounted（G4 看门狗查询）与 chapter_cost（C39
  append_history 取数口）跨进程恢复后查询仍然成立。
- G5 规则引擎（observe→hits）与异常落账出口（report_anomaly）：命中先记内存镜像，
  再经 persist 钩子落 state['anomalies'] + 项目/追踪/session_events.jsonl。
- 规则与视图口径逐字承自 app/usage.py（C35 原文），详见 usage 侧 ANOMALY_RULES 注记。

S6a 依赖倒置（拆 usage↔core SCC，本模块刻意零 app 依赖、纯 stdlib）：
  - ensure 钩子：查询前的懒加载（usage._ensure_today 读台账文件回放视图）。文件
    归属与路径 monkeypatch 面留在 app.usage（app-top→core 合法方向），由 usage
    导入期 bind_ensure 装订；未装订（极端：core 单独被测）时只读内存视图。
  - persist 钩子：state['anomalies']/session_events 落账由 core.anomaly_persist
    提供（core→core 合法），其导入期自装订；未装订时只留镜像与日志（与「未登记
    项目」同语义，绝不抛错——告警是观测件，绝不碰记账与主流水线）。
- 线程安全：LLM 工作线程 observe/emit，看门狗线程 report/查询；_lock 保护视图与
  镜像。ensure 在取 _lock 之前调用（usage._lock → _lock 单向嵌套，不反转）。
"""
import datetime
import json
import logging
import threading

# 与 usage 同一日志命名空间：告警日志逐字节承袭 C35 行为
logger = logging.getLogger("qianbi.usage")

ACCOUNTING_PHASES = frozenset({"tracking", "chapter_summary", "global_summary",
                               "canon_audit", "canon_audit_review"})
DEFAULT_COST_ALERT_CNY = 0.8   # T3 实算：失控章 ~0.97 元、正常章 ~0.1-0.4 元，0.8 居中分界
_ANOMALY_KEEP = 200            # 内存镜像上限（state 侧 500 条，见 anomaly_persist）

_lock = threading.Lock()
_alert_proj = ""        # 当前项目（orchestrator.run 启动登记；空=规则照评，只留内存与日志）
_alert_cost_cny = DEFAULT_COST_ALERT_CNY
_chapter_phases = {}    # {ch: set(phase)}——本进程见过 + rebuild 从盘上台账回放的
_chapter_cost = {}      # {ch: 单章累计估算成本（元）}
_last_prose_ch = 0      # 最近开写过 prose 的章号（回放取最大；0=尚无）
_flagged = set()        # 本进程已告警过的 (rule, ch)
_anomalies = []         # 告警内存镜像（尾部 _ANOMALY_KEEP 条）

# 默认费率（元/百万 tokens）：与 router.estimate_cost 口径一致
DEFAULT_PRICES = {"flash": (1.0, 2.0), "mini": (1.0, 2.0), "_default": (2.0, 8.0)}

# ---- S6a 装订钩子（依赖倒置，见模块 docstring）----
_ensure = None          # 查询前懒加载（usage._ensure_today）；None=只读内存视图
_persist = None         # 异常落账（anomaly_persist.persist）；None=只留镜像与日志


def bind_ensure(fn) -> None:
    """装订查询前懒加载（app.usage 导入期调用一次；usage 重载（单测隔离）会重装订）"""
    global _ensure
    _ensure = fn


def bind_persist(fn) -> None:
    """装订异常落账（core.anomaly_persist 导入期调用一次）"""
    global _persist
    _persist = fn


def _prices(cfg: dict) -> dict:
    prices = dict(DEFAULT_PRICES)
    prices.update((cfg.get("usage_prices") or {}))
    return prices


def cost_of(model: str, tin: int, tout: int, cfg: dict = None) -> float:
    """按费率表估算成本（元）"""
    model = (model or "").lower()
    prices = _prices(cfg or {})
    for tag, rates in prices.items():
        if tag != "_default" and tag in model:
            in_rate, out_rate = rates
            break
    else:
        in_rate, out_rate = prices["_default"]
    return tin / 1e6 * in_rate + tout / 1e6 * out_rate


def set_project(proj: str, cfg: dict = None) -> None:
    """登记当前项目与告警阈值（orchestrator.run 启动时调用一次）。

    登记后 record() 命中规则会把异常落进该项目 pipeline_state.json 的 anomalies
    键，并同步 record_event 到 项目/追踪/session_events.jsonl；未登记（proj 空）
    时规则照常评估，只留内存镜像与日志，不写任何项目状态（单测/旁路调用安全）。
    阈值取 cfg['usage_alerts']['chapter_cost_cny']，缺省 DEFAULT_COST_ALERT_CNY。
    """
    global _alert_proj, _alert_cost_cny
    _alert_proj = proj or ""
    try:
        _alert_cost_cny = float(
            ((cfg or {}).get("usage_alerts") or {}).get("chapter_cost_cny",
                                                        DEFAULT_COST_ALERT_CNY))
    except (TypeError, ValueError):
        _alert_cost_cny = DEFAULT_COST_ALERT_CNY


def reset() -> None:
    """清空告警视角的内存状态（单测隔离用；生产路径只在进程生命周期内自然累积）"""
    global _last_prose_ch
    _chapter_phases.clear()
    _chapter_cost.clear()
    _flagged.clear()
    _anomalies.clear()
    _last_prose_ch = 0


def chapter_accounted(num: int) -> bool:
    """G4 相位看门狗查询：该章在台账里是否出现过任一记账相位行。

    台账行由 record() 实时维护 + rebuild 从盘上历史回放——跨进程恢复后查询仍然成立。
    """
    if _ensure is not None:
        _ensure()               # 首查懒加载（取 usage._lock，勿在 _lock 内调用防嵌套反转）
    with _lock:
        return bool(_chapter_phases.get(int(num or 0), set()) & ACCOUNTING_PHASES)


def chapter_cost(num: int):
    """单章累计估算成本（元）：读内存视图（record 实时 + rebuild 回放）。

    append_history 落 history 行的取数口；该章在台账里没有任何行时返回 None——
    「没记账」落缺字段，不伪装成 0（与盲区口径同一句话）。"""
    if _ensure is not None:
        _ensure()
    with _lock:
        v = _chapter_cost.get(int(num or 0))
        return None if v is None else round(float(v), 6)


def rebuild(rec: dict) -> None:
    """从盘上台账回放一行（usage._load 逐行喂入；只建视图，不触发规则不加镜像）"""
    ch = int(rec.get("ch", 0) or 0)
    if ch <= 0:
        return
    global _last_prose_ch
    with _lock:
        phase = str(rec.get("phase") or "")
        _chapter_phases.setdefault(ch, set()).add(phase)
        _chapter_cost[ch] = round(_chapter_cost.get(ch, 0.0) + cost_of(
            str(rec.get("model") or ""), int(rec.get("in", 0) or 0),
            int(rec.get("out", 0) or 0)), 6)
        if phase == "prose" and ch > _last_prose_ch:
            _last_prose_ch = ch


def observe(rec: dict) -> list:
    """record 后置规则评估（usage.record 在其文件锁内调用）：返回命中的异常列表。

    命中即登记 _flagged 去重；规则自身故障绝不外抛（记账主流程优先）。
    """
    global _last_prose_ch
    hits = []
    try:
        ch = int(rec.get("ch") or 0)
        phase = str(rec.get("phase") or "")
        tin, tout = int(rec.get("in") or 0), int(rec.get("out") or 0)
        if ch <= 0:
            return hits
        with _lock:
            _chapter_phases.setdefault(ch, set()).add(phase)
            _chapter_cost[ch] = round(_chapter_cost.get(ch, 0.0) + cost_of(
                str(rec.get("model") or ""), tin, tout), 6)
            if phase == "prose" and ch > _last_prose_ch:
                prev = _last_prose_ch
                _last_prose_ch = ch   # 章页翻过：本章成为新的「最近 prose 章」
                # ③ 记账窗口已随章页翻过：上一章直到此刻都没等到任何记账相位行
                if prev > 0 and not (_chapter_phases.get(prev, set()) & ACCOUNTING_PHASES):
                    key = ("tracking_missing", prev)
                    if key not in _flagged:
                        _flagged.add(key)
                        hits.append({
                            "rule": "tracking_missing", "level": "error", "ch": prev,
                            "msg": (f"第 {prev} 章正文已落库但台账无任何记账相位行"
                                    f"（tracking/章摘要/全局摘要/清算皆无）——"
                                    f"收尾记账窗口被中断的典型信号"),
                            "fields": {"phase_scan": sorted(
                                _chapter_phases.get(prev, set()))}})
            cost = _chapter_cost[ch]
            if cost >= _alert_cost_cny and ("chapter_cost_over", ch) not in _flagged:
                _flagged.add(("chapter_cost_over", ch))
                hits.append({
                    "rule": "chapter_cost_over", "level": "warn", "ch": ch,
                    "msg": (f"第 {ch} 章累计成本 {cost:.2f} 元已越限"
                            f"（阈值 {_alert_cost_cny:.2f} 元）"),
                    "fields": {"cost": cost, "threshold": _alert_cost_cny}})
            if phase == "prose":
                mt = (rec.get("sent") or {}).get("max_tokens")
                if tout > 0 and isinstance(mt, (int, float)) and mt > 0:
                    if tout >= mt and ("prose_maxed_out", ch) not in _flagged:
                        _flagged.add(("prose_maxed_out", ch))
                        hits.append({
                            "rule": "prose_maxed_out", "level": "error", "ch": ch,
                            "msg": (f"第 {ch} 章 prose 输出 {tout} tokens 顶格"
                                    f"（=max_tokens）——疑似截断/失控稿"),
                            "fields": {"out": tout, "max_tokens": int(mt)}})
                else:
                    # 降级口径（写明）：渠道不报 max_tokens（sent 缺该键）或不回 usage
                    # （tout<=0）→ 无从裁决顶格，只留 debug 痕迹，不告警不落账。
                    logger.debug("台账告警降级：prose 行缺 max_tokens/usage"
                                 "（ch=%s out=%s sent=%s），不判定顶格", ch, tout,
                                 rec.get("sent"))
    except Exception as e:  # noqa: BLE001
        logger.debug("台账告警规则评估失败（忽略）: %s", e)
    return hits


def report_anomaly(rule: str, level: str, ch: int = 0, msg: str = "",
                   **fields) -> bool:
    """异常落账的唯一出口：内存镜像 + state['anomalies'] + session_events 事件。

    返回是否真正新增（同 (rule, ch) 已在 state 里时只返回 False，不重复落）。
    落账走 persist 钩子（core.anomaly_persist，core→core 合法方向——S6a 拆环：
    app-top 不再反向持 core 写通道）。任何失败降级 debug 日志——告警是观测件，
    绝不碰记账与主流水线。
    """
    entry = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "rule": str(rule), "ch": int(ch or 0), "level": str(level),
             "msg": str(msg or "")}
    entry.update({k: v for k, v in fields.items() if v is not None})
    with _lock:
        _anomalies.append(entry)
        if len(_anomalies) > _ANOMALY_KEEP:
            del _anomalies[: len(_anomalies) - _ANOMALY_KEEP]
    if not _alert_proj:
        return True
    try:
        if _persist is None:    # 未装订（纯内存模式）：与「未登记项目」同语义
            return True
        return _persist(_alert_proj, entry)
    except Exception as e:  # noqa: BLE001
        logger.debug("告警落账失败（不影响记账主流程）: %s", e)
        return False


def emit(hit: dict) -> None:
    """规则命中 → 分级日志 + report_anomaly 落账（usage.record 锁外调用）"""
    level = str(hit.get("level") or "warn")
    (logger.error if level == "error" else logger.warning)(
        "台账告警[%s] 第%s章 %s", hit.get("rule"), hit.get("ch"), hit.get("msg", ""))
    try:
        report_anomaly(hit.get("rule"), level, ch=hit.get("ch") or 0,
                       msg=hit.get("msg", ""), **(hit.get("fields") or {}))
    except Exception as e:  # noqa: BLE001
        logger.debug("告警落账失败（忽略）: %s", e)


def anomalies_snapshot(limit: int = 20) -> list:
    """告警内存镜像只读视图（尾部 limit 条深拷贝）——成本面板消费，外部不许改账。"""
    n = max(0, int(limit or 0))
    with _lock:
        tail = _anomalies[-n:] if n else list(_anomalies)
        return json.loads(json.dumps(tail))
