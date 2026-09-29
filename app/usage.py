# -*- coding: utf-8 -*-
"""Token 用量统计（插件）：本地持久化 + 多维聚合 + 成本估算 + 准实时告警

- 落点 ~/.qianbi_novel/usage/usage.jsonl，每行一条调用记录
  （ts/ymd/slot/model/in/out/latency + hit/miss/phase/reasoning；旧文件缺后面几列，读取时按 0/空兜底）
- 内存聚合缓存：启动全量读入，运行中增量累计；跨天自动切分
- 费率表（元/百万 tokens）：flash/mini 档 1.0/2.0，其余 2.0/8.0——可被 config.usage_prices 覆盖
- 线程安全：LLM 工作线程调用 record()，用锁保护内存结构
- C35 G5 准实时告警：record() 后置规则引擎（顶格稿/单章成本/缺记账行）——
  S6a 起规则/视图/落账下沉 core.ledger_view（纯视图）+ core.anomaly_persist
  （state/session_events 写通道），本模块只喂行与门面转发（公开 API 一字不变，
  详见 ledger_view 的 ANOMALY_RULES 口径注记）
- C39 成本面板取数侧：book_scope_summary/chapter_costs/chapter_cost/
  anomalies_snapshot（纯读台账，盲区优先于 0，详见对应注记）
"""
import datetime
import json
import logging
import os
import threading

from .core import ledger_view as _lv

logger = logging.getLogger("qianbi.usage")

DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage")
FILE = os.path.join(DIR, "usage.jsonl")

_lock = threading.Lock()
_chapter = 0   # 当前章号（章循环入口经 set_chapter 设置；0＝未知，用量行如实落 0）
_cache = None   # {"ymd": 当天日期串, "days": {ymd: {"in","out","calls","by_model","by_slot"}}}


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
    global _cache
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
                        # 缺记账规则的查询面，视图本体在 core.ledger_view）。
                        # 历史成本按默认费率累计——自定义费率只影响本进程增量，回放
                        # 口径的这点漂移换「跨进程不瞎报」。
                        _lv.rebuild(r)
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
        hits = _lv.observe(rec)   # C35 G5：账记完立刻裁决（锁内评，锁外落账）
    for _hit in hits:
        _lv.emit(_hit)


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
                    t["hit"] += m["hit"]
                    t["miss"] += m["miss"]
                    t["reasoning"] += m["reasoning"]
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
            _lv.cost_of(model, m["in"], m["out"], cfg)
            for model, m in scope["by_model"].items()), 2)
    return out


# ==================== C39 成本面板：book-scope 三层聚合（纯读台账）====================
#
# B 方案「常驻消费层」的取数侧（docs/落地计划附录A 卡 C39 / w4_model_orch §3 方案 B）。
# summary() 是进程内存聚合，没有「本书」维度——台账行本身无 project 列（record()
# 不带项目，跨书共用一份 usage.jsonl），章级调用（ch>0）是唯一诚实的本书代理。
# 三层口径：
#   today = ymd == 今天（全部行；费率对 in/out 线性，逐行累计与 summary 的按模型
#           聚合同值）
#   month = ymd 前缀 == 本月（全部行）
#   book  = ch > 0 的行（本书口径＝章级流水线行；多书共用台账时为各书章级行合计，
#           面板文案写明这一近似，不猜不装）；since_ts 非空时再卡 ts >= since_ts
#           的会话窗口（w4 §3 B 的原始口径，缺省全史）。
# 「盲区优先于 0」（验收②）：范围内没有任何行 → known=False，UI 显示「盲区」
# 而非 ¥0.00——「没记账」与「花了 0 元」是两句话；命中率同理，hit+miss=0
# （渠道不回缓存明细/全盲区）时不给率值，不伪装成 0%。盲区 token 单列（W-5 口径，
# cache_caliber 直接复用），既不进命中率分子也不进分母。


def _scope_accum() -> dict:
    return {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0, "blind": 0,
            "cost": 0.0, "known": False, "hit_rate": None}


def _as_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _scope_add(acc: dict, rec: dict, cfg: dict) -> None:
    i, o = _as_int(rec.get("in")), _as_int(rec.get("out"))
    h, m, b = cache_caliber({"in": i, "hit": _as_int(rec.get("hit")),
                             "miss": _as_int(rec.get("miss"))})
    acc["in"] += i
    acc["out"] += o
    acc["calls"] += 1
    acc["hit"] += h
    acc["miss"] += m
    acc["blind"] += b
    acc["cost"] += _lv.cost_of(str(rec.get("model") or ""), i, o, cfg)
    acc["known"] = True


def _scope_finish(acc: dict) -> dict:
    acc["cost"] = round(acc["cost"], 4)
    if acc["hit"] + acc["miss"] > 0:
        acc["hit_rate"] = round(acc["hit"] / (acc["hit"] + acc["miss"]), 4)
    return acc


def book_scope_summary(cfg: dict = None, path: str = None,
                       since_ts: str = "") -> dict:
    """三层聚合（纯读台账 JSONL，不碰内存缓存）→ {"today","book","month"}。

    每层含 in/out/calls/cost/hit/miss/blind/hit_rate/known；坏行跳过（与 _load
    同容忍度）。path 供测试注入；since_ts（"YYYY-MM-DD HH:MM:SS"）只约束 book 层。
    文件缺失/范围内无行 → 该层 known=False，费用/命中率由 UI 显示「盲区」。"""
    p = path or FILE
    today = _today()
    month = today[:7]
    scopes = {"today": _scope_accum(), "month": _scope_accum(),
              "book": _scope_accum()}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        ymd = str(r.get("ymd") or (r.get("ts") or "")[:10])
                        try:
                            ch = int(r.get("ch", 0) or 0)
                        except (TypeError, ValueError):
                            ch = 0              # 脏章号按「章外行」计，不炸整表扫描
                    except Exception:  # noqa: BLE001
                        continue
                    if ymd == today:
                        _scope_add(scopes["today"], r, cfg)
                    if ymd.startswith(month):
                        _scope_add(scopes["month"], r, cfg)
                    if ch > 0 and (not since_ts or str(r.get("ts") or "") >= since_ts):
                        _scope_add(scopes["book"], r, cfg)
        except OSError as e:
            logger.warning("台账读取失败（成本面板按盲区显示）: %s", e)
    return {k: _scope_finish(v) for k, v in scopes.items()}


def chapter_costs(cfg: dict = None, path: str = None, limit: int = 10) -> list:
    """章级成本列表（纯读）：[{ch, cost, in, out, calls, hit, miss, blind}]。

    按章号降序取最近 limit 章；章号是台账里唯一的服务侧归属键（无 project 列），
    故列表即「本书流水线行」视角——多书共台账时旧书章号一并入列，按号排序天然
    以最近的书为主。ch<=0（章外调用）不入列。"""
    p = path or FILE
    per: dict = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        ch = int(r.get("ch", 0) or 0)
                        if ch <= 0:
                            continue
                        acc = per.setdefault(ch, _scope_accum())
                        _scope_add(acc, r, cfg)
                    except Exception:  # noqa: BLE001
                        continue
        except OSError as e:
            logger.warning("台账读取失败（章级成本按空显示）: %s", e)
    out = []
    for ch in sorted(per, reverse=True)[:max(0, int(limit or 0))]:
        acc = _scope_finish(per[ch])
        acc["ch"] = ch
        out.append(acc)
    return out


# ==================== S6a 拆环：视图/规则/告警层门面（API 一字不变）====================
#
# C35 G4/G5 + C39 章级成本视图的规则引擎、内存镜像与落账出口下沉 core.ledger_view
# （纯 stdlib 视图层）；state['anomalies']/session_events 写通道下沉
# core.anomaly_persist。原先 usage 函数内延迟 import state/volume_session 正是
# usage↔core SCC 的闭环比——现在方向定格：app.usage → core（合法向下），state /
# orchestrator 查询走 core.ledger_view，不再上探 app-top。
# 以下别名保持既有消费面（bridge 成本面板、llm.client、单测的 um.*）零改动。

set_project = _lv.set_project
report_anomaly = _lv.report_anomaly
chapter_accounted = _lv.chapter_accounted
chapter_cost = _lv.chapter_cost
anomalies_snapshot = _lv.anomalies_snapshot
reset_watch_state = _lv.reset
cost_of = _lv.cost_of
ACCOUNTING_PHASES = _lv.ACCOUNTING_PHASES
DEFAULT_COST_ALERT_CNY = _lv.DEFAULT_COST_ALERT_CNY
DEFAULT_PRICES = _lv.DEFAULT_PRICES
_anomalies = _lv._anomalies   # 镜像身份透传（单测钉 _pairs(um._anomalies) 直读）

# 查询前懒加载装订：chapter_accounted/chapter_cost 首查触发台账文件回放
# （ensure 在 ledger_view 取锁之前调用，锁序 usage._lock → _view._lock 单向）
_lv.bind_ensure(_ensure_today)
