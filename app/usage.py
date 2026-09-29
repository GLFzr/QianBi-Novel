# -*- coding: utf-8 -*-
"""Token 用量统计（插件）：本地持久化 + 多维聚合 + 成本估算 + 准实时告警

- 落点 ~/.qianbi_novel/usage/usage.jsonl，每行一条调用记录
  （ts/ymd/slot/model/in/out/latency + hit/miss/phase/reasoning；旧文件缺后面几列，读取时按 0/空兜底）
- 内存聚合缓存：启动全量读入，运行中增量累计；跨天自动切分
- 费率表（元/百万 tokens）：flash/mini 档 1.0/2.0，其余 2.0/8.0——可被 config.usage_prices 覆盖
- 线程安全：LLM 工作线程调用 record()，用锁保护内存结构
- C35 G5 准实时告警：record() 后置规则引擎（顶格稿/单章成本/缺记账行），
  命中落 state['anomalies'] + 项目/追踪/session_events.jsonl（详见 ANOMALY_RULES 注记）
"""
import datetime
import json
import logging
import os
import threading

logger = logging.getLogger("qianbi.usage")

DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage")
FILE = os.path.join(DIR, "usage.jsonl")

_lock = threading.Lock()
_chapter = 0   # 当前章号（章循环入口经 set_chapter 设置；0＝未知，用量行如实落 0）
_cache = None   # {"ymd": 当天日期串, "days": {ymd: {"in","out","calls","by_model","by_slot"}}}

# ==================== C35 G5：台账准实时告警（台账从「只写不读」变成实时裁决层）====================
#
# T3 v1 实录（docs/落地计划附录A 卡 C35 / w2_t31_rootcause.md §1.3、§3）：1705 行台账
# 里躺着 16384 顶格输出、125k 审校输入、41 章起相位真空三大量化异常，但台账只写不读，
# 30 章静默停摆零告警。G5 把裁决挂在 record() 出口：命中规则即 report_anomaly 落账。
#
# ANOMALY_RULES（level：error=疑似事故 / warn=成本越限）：
#   ① prose_maxed_out   prose 相位输出 tokens 顶格（out >= max_tokens）——服务端钳位
#                       截断的指纹（T3 ch41-44 连续精确 16384）。**降级口径（写明）**：
#                       渠道不报 max_tokens（请求没带/被网关剥参，sent 缺该键）或渠道
#                       不回 usage（out<=0 时不落行）→ 无从裁决，记 logger.debug 留痕、
#                       不告警不落账——「不知道」不许伪装成「正常」也不许伪装成「异常」。
#   ② chapter_cost_over 单章累计估算成本 ≥ usage_alerts.chapter_cost_cny（缺省 0.8 元，
#                       orchestrator 经 set_project 下发 cfg；回放历史行按默认费率累计）
#   ③ tracking_missing  下一章 prose 已开写（章页翻过）而上一章在台账里没有任何记账
#                       相位行（ACCOUNTING_PHASES）——「正文已落库、收尾记账窗口被杀」
#                       的指纹（T3 ch41-46 相位真空）。跨进程恢复时从盘上台账回放重建
#                       视图，只对「最后未愈合的尾部断档」翻页告警，历史老坑不翻旧账。
#
# 去重：同 (rule, ch) 每进程只报一次（_flagged）；落 state 前再按已存 anomalies
# 条目去重（跨进程防重）。告警镜像 _anomalies 留尾部 _ANOMALY_KEEP 条供测试/调试。

ACCOUNTING_PHASES = frozenset({"tracking", "chapter_summary", "global_summary",
                               "canon_audit", "canon_audit_review"})
DEFAULT_COST_ALERT_CNY = 0.8   # T3 实算：失控章 ~0.97 元、正常章 ~0.1-0.4 元，0.8 居中分界
_ANOMALY_KEEP = 200            # 内存镜像上限（state 侧 500 条，见 report_anomaly）
_STATE_ANOMALY_KEEP = 500

_alert_proj = ""        # 当前项目（orchestrator.run 启动登记；空=规则照评，只留内存与日志）
_alert_cost_cny = DEFAULT_COST_ALERT_CNY
_chapter_phases = {}    # {ch: set(phase)}——本进程见过 + _load 从盘上台账回放的
_chapter_cost = {}      # {ch: 单章累计估算成本（元）}
_last_prose_ch = 0      # 最近开写过 prose 的章号（回放取最大；0=尚无）
_flagged = set()        # 本进程已告警过的 (rule, ch)
_anomalies = []         # 告警内存镜像（尾部 _ANOMALY_KEEP 条）

# 默认费率（元/百万 tokens）：与 router.estimate_cost 口径一致
DEFAULT_PRICES = {"flash": (1.0, 2.0), "mini": (1.0, 2.0), "_default": (2.0, 8.0)}


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


def _today() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


# ---- W-5 计量口径：盲区 token 的唯一定义（chapter_curve / cost_ledger 共用）----
#
# 一条用量行的输入只有三种归属：上报为命中、上报为未命中、**网关根本没回缓存明细**。
# 第三种过去被两个工具各算各的——chapter_curve 把它按 miss 计（保守，账面虚高），
# cost_ledger 干脆不计价（虚低）。同一份数据两个数，判据就废了。现在统一：
# 盲区既不进 hit% 的分子也不进分母，单独报 blind_tok，钱给**账面/真实**两个口径。


def cache_caliber(rec: dict) -> tuple:
    """用量行 → (hit, miss, blind)：in 中未被任何缓存字段解释的部分即盲区 token。

    上报了 prompt_cache_hit/miss 的行 blind=0；只回 cached_tokens 的行由
    client._record_usage 折算成 (cached, in-cached)；什么都没回（hit=miss=0 而
    in>0，含无 hit 键的历史行）整条落盲区——**不许猜命中**。"""
    i = int(rec.get("in") or 0)
    h = int(rec.get("hit") or 0)
    m = int(rec.get("miss") or 0)
    if h + m >= i:
        return h, m, 0
    return h, m, i - h - m


def blind_spread(hit: int, miss: int, blind: int) -> tuple:
    """盲区按**本渠道已知行的实测命中率**摊派 → (add_hit, add_miss)。

    全盲（没有任何已知行）时无从摊派，只能全按 miss 计（与账面口径一致）。"""
    blind = int(blind or 0)
    if blind <= 0:
        return 0, 0
    known = int(hit or 0) + int(miss or 0)
    if known <= 0:
        return 0, blind
    add_hit = int(round(blind * (int(hit) / known)))
    return add_hit, blind - add_hit


def _new_day() -> dict:
    return {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0, "reasoning": 0,
            "by_model": {}, "by_slot": {}}


def _bump(day: dict, model: str, slot: str, tin: int, tout: int,
          hit: int = 0, miss: int = 0, reasoning: int = 0):
    day["in"] += tin
    day["out"] += tout
    day["calls"] += 1
    day["hit"] += hit
    day["miss"] += miss
    day["reasoning"] += reasoning
    for key, sub in (("by_model", model or "unknown"), ("by_slot", slot or "unknown")):
        m = day[key].setdefault(sub, {"in": 0, "out": 0, "calls": 0, "hit": 0,
                                      "miss": 0, "reasoning": 0})
        m["in"] += tin
        m["out"] += tout
        m["calls"] += 1
        m["hit"] += hit
        m["miss"] += miss
        m["reasoning"] += reasoning


def _load():
    """启动全量读入历史（文件损坏容忍：跳过坏行）"""
    global _cache, _last_prose_ch
    days = {}
    if os.path.exists(FILE):
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        day = days.setdefault(r.get("ymd", _today()), _new_day())
                        _bump(day, r.get("model", ""), r.get("slot", ""),
                              int(r.get("in", 0)), int(r.get("out", 0)),
                              int(r.get("hit", 0) or 0), int(r.get("miss", 0) or 0),
                              int(r.get("reasoning", 0) or 0))
                        # G5 回放：历史行重建章级相位/成本视图（chapter_accounted 与
                        # 缺记账规则的查询面）。历史成本按默认费率累计——自定义费率
                        # 只影响本进程增量，回放口径的这点漂移换「跨进程不瞎报」。
                        ch = int(r.get("ch", 0) or 0)
                        if ch > 0:
                            phase = str(r.get("phase") or "")
                            _chapter_phases.setdefault(ch, set()).add(phase)
                            _chapter_cost[ch] = round(_chapter_cost.get(ch, 0.0) + cost_of(
                                str(r.get("model") or ""), int(r.get("in", 0) or 0),
                                int(r.get("out", 0) or 0)), 6)
                            if phase == "prose" and ch > _last_prose_ch:
                                _last_prose_ch = ch
                    except Exception:  # noqa: BLE001
                        continue
        except OSError as e:
            logger.warning("用量文件读取失败（忽略）: %s", e)
    _cache = {"ymd": None, "days": days}


def _ensure_today():
    global _cache
    if _cache is None:
        _load()
    today = _today()
    if _cache["ymd"] != today:
        _cache["days"].setdefault(today, _new_day())
        _cache["ymd"] = today
    return _cache["days"][today]


def set_chapter(num: int) -> None:
    """设置当前章号（供用量行的 ch 字段归属）。

    章循环入口调用一次即可：副本票虽在别的线程，但同属本章。不设置则落 0＝未知，
    比猜一个章号诚实。"""
    global _chapter
    try:
        _chapter = int(num or 0)
    except (TypeError, ValueError):
        _chapter = 0


# ---- C35 G5：告警规则引擎与落账 ----

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


def reset_watch_state() -> None:
    """清空告警视角的内存状态（单测隔离用；生产路径只在进程生命周期内自然累积）"""
    global _last_prose_ch
    _chapter_phases.clear()
    _chapter_cost.clear()
    _flagged.clear()
    _anomalies.clear()
    _last_prose_ch = 0


def chapter_accounted(num: int) -> bool:
    """G4 相位看门狗查询：该章在台账里是否出现过任一记账相位行。

    台账行由 record() 实时维护 + _load 从盘上历史回放——跨进程恢复后查询仍然成立。
    """
    with _lock:
        _ensure_today()
        return bool(_chapter_phases.get(int(num or 0), set()) & ACCOUNTING_PHASES)


def report_anomaly(rule: str, level: str, ch: int = 0, msg: str = "",
                   **fields) -> bool:
    """异常落账的唯一出口：内存镜像 + state['anomalies'] + session_events 事件。

    返回是否真正新增（同 (rule, ch) 已在 state 里时只返回 False，不重复落）。
    任何失败降级 debug 日志——告警是观测件，绝不碰记账与主流水线。
    """
    entry = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "rule": str(rule), "ch": int(ch or 0), "level": str(level),
             "msg": str(msg or "")}
    entry.update({k: v for k, v in fields.items() if v is not None})
    _anomalies.append(entry)
    if len(_anomalies) > _ANOMALY_KEEP:
        del _anomalies[: len(_anomalies) - _ANOMALY_KEEP]
    if not _alert_proj:
        return True
    try:
        from .core import state as _st
        from .core import volume_session as _vs
        state = _st.load_state(_alert_proj)
        lst = state.get("anomalies")
        if not isinstance(lst, list):
            lst = state["anomalies"] = []
        if any(a.get("rule") == entry["rule"] and a.get("ch") == entry["ch"]
               for a in lst if isinstance(a, dict)):
            return False
        lst.append(entry)
        if len(lst) > _STATE_ANOMALY_KEEP:
            del lst[: len(lst) - _STATE_ANOMALY_KEEP]
        _st.save_state(_alert_proj, state)
        _vs.record_event(_alert_proj, "usage_anomaly", rule=entry["rule"],
                         ch=entry["ch"], level=entry["level"], msg=entry["msg"])
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("告警落账失败（不影响记账主流程）: %s", e)
        return False


def _eval_rules(rec: dict) -> list:
    """record 后置规则评估（须在 _lock 内调用）：返回命中的异常列表。

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


def _emit_anomaly(hit: dict) -> None:
    """规则命中 → 分级日志 + report_anomaly 落账（在 _lock 外调用）"""
    level = str(hit.get("level") or "warn")
    (logger.error if level == "error" else logger.warning)(
        "台账告警[%s] 第%s章 %s", hit.get("rule"), hit.get("ch"), hit.get("msg", ""))
    try:
        report_anomaly(hit.get("rule"), level, ch=hit.get("ch") or 0,
                       msg=hit.get("msg", ""), **(hit.get("fields") or {}))
    except Exception as e:  # noqa: BLE001
        logger.debug("告警落账失败（忽略）: %s", e)


def record(cfg: dict, model: str, slot: str, tin: int, tout: int, latency: float = 0.0,
           hit: int = 0, miss: int = 0, phase: str = "", reasoning: int = 0,
           sent: dict = None, status: str = ""):
    """记录一次 LLM 调用（工作线程安全）。tin/tout 为该次响应的 usage 计数

    hit/miss 为 DeepSeek prompt_cache_hit_tokens / prompt_cache_miss_tokens（缺省 0）；
    phase 为调用阶段标签（缺省空串）；reasoning 为该次响应的推理 tokens
    （completion_tokens_details.reasoning_tokens，缺省 0）。
    旧调用不传时 jsonl 落 0/空，保持向后兼容（旧行无 reasoning 键，读取按 .get 容错）。
    """
    if tin <= 0 and tout <= 0:
        return
    now = datetime.datetime.now()
    ymd = now.strftime("%Y-%m-%d")
    rec = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "ymd": ymd,
           "model": model or "", "slot": slot or "",
           "in": int(tin), "out": int(tout), "latency": round(float(latency or 0), 2),
           "hit": int(hit or 0), "miss": int(miss or 0), "phase": phase or "",
           "reasoning": int(reasoning or 0), "ch": int(_chapter or 0)}
    if sent:
        # 只记**真正随请求下发**的参数（网关剥参、thinking 未设导致 effort 被丢，
        # 都只有这一格能看出来）；未设置时不落空字段，保持旧行形状
        rec["sent"] = {str(k): sent.get(k) for k in sorted(sent)}
    if status:
        # W-4：白付标记（"empty"=200 但没吐出可用内容、"abort"=用户中止）——
        # 这些发没走成功记账分支，钱却真花了。不分列出来，重试预算就是计费黑洞。
        rec["st"] = str(status)[:16]
    with _lock:
        day = _ensure_today()   # 先加载历史（含跨天切分），再落盘本条，避免双计
        try:
            os.makedirs(DIR, exist_ok=True)
            with open(FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("用量落盘失败（忽略）: %s", e)
        _bump(day, model, slot, int(tin), int(tout), int(hit or 0), int(miss or 0),
              int(reasoning or 0))
        hits = _eval_rules(rec)   # C35 G5：账记完立刻裁决（锁内评，锁外落账）
    for _hit in hits:
        _emit_anomaly(_hit)


def summary(cfg: dict = None) -> dict:
    """聚合视图：今日 / 本月 / 全部 的 tokens、成本、调用数与按模型分组"""
    with _lock:
        _ensure_today()
        days = dict(_cache["days"])

    def agg(day_keys):
        total = _new_day()
        for k in day_keys:
            d = days.get(k)
            if not d:
                continue
            total["in"] += d["in"]
            total["out"] += d["out"]
            total["calls"] += d["calls"]
            total["hit"] += d.get("hit", 0)
            total["miss"] += d.get("miss", 0)
            total["reasoning"] += d.get("reasoning", 0)
            for bucket_key in ("by_model", "by_slot"):
                for model, m in (d.get(bucket_key) or {}).items():
                    t = total[bucket_key].setdefault(
                        model, {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0,
                                "reasoning": 0})
                    t["in"] += m["in"]
                    t["out"] += m["out"]
                    t["calls"] += m["calls"]
                    t["hit"] += m.get("hit", 0)
                    t["miss"] += m.get("miss", 0)
                    t["reasoning"] += m.get("reasoning", 0)
        return total

    today = _today()
    month = today[:7]
    out = {
        "today": agg([today]),
        "month": agg([k for k in days if k.startswith(month)]),
        "all": agg(list(days.keys())),
    }
    for scope in out.values():
        scope["cost"] = round(sum(
            cost_of(model, m["in"], m["out"], cfg)
            for model, m in scope["by_model"].items()), 2)
    return out
