# -*- coding: utf-8 -*-
"""Token 用量统计（插件）：本地持久化 + 多维聚合 + 成本估算

- 落点 ~/.qianbi_novel/usage/usage.jsonl，每行一条调用记录
  （ts/ymd/slot/model/in/out/latency + hit/miss/phase；旧文件缺后三列，读取时按 0/空兜底）
- 内存聚合缓存：启动全量读入，运行中增量累计；跨天自动切分
- 费率表（元/百万 tokens）：flash/mini 档 1.0/2.0，其余 2.0/8.0——可被 config.usage_prices 覆盖
- 线程安全：LLM 工作线程调用 record()，用锁保护内存结构
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
_cache = None   # {"ymd": 当天日期串, "days": {ymd: {"in","out","calls","by_model","by_slot"}}}

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


def _new_day() -> dict:
    return {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0,
            "by_model": {}, "by_slot": {}}


def _bump(day: dict, model: str, slot: str, tin: int, tout: int,
          hit: int = 0, miss: int = 0):
    day["in"] += tin
    day["out"] += tout
    day["calls"] += 1
    day["hit"] += hit
    day["miss"] += miss
    for key, sub in (("by_model", model or "unknown"), ("by_slot", slot or "unknown")):
        m = day[key].setdefault(sub, {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0})
        m["in"] += tin
        m["out"] += tout
        m["calls"] += 1
        m["hit"] += hit
        m["miss"] += miss


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
                              int(r.get("hit", 0) or 0), int(r.get("miss", 0) or 0))
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


def record(cfg: dict, model: str, slot: str, tin: int, tout: int, latency: float = 0.0,
           hit: int = 0, miss: int = 0, phase: str = ""):
    """记录一次 LLM 调用（工作线程安全）。tin/tout 为该次响应的 usage 计数

    hit/miss 为 DeepSeek prompt_cache_hit_tokens / prompt_cache_miss_tokens（缺省 0）；
    phase 为调用阶段标签（缺省空串）。旧调用不传时 jsonl 落 0/空，保持向后兼容。
    """
    if tin <= 0 and tout <= 0:
        return
    now = datetime.datetime.now()
    ymd = now.strftime("%Y-%m-%d")
    rec = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "ymd": ymd,
           "model": model or "", "slot": slot or "",
           "in": int(tin), "out": int(tout), "latency": round(float(latency or 0), 2),
           "hit": int(hit or 0), "miss": int(miss or 0), "phase": phase or ""}
    with _lock:
        day = _ensure_today()   # 先加载历史（含跨天切分），再落盘本条，避免双计
        try:
            os.makedirs(DIR, exist_ok=True)
            with open(FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("用量落盘失败（忽略）: %s", e)
        _bump(day, model, slot, int(tin), int(tout), int(hit or 0), int(miss or 0))


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
            for bucket_key in ("by_model", "by_slot"):
                for model, m in (d.get(bucket_key) or {}).items():
                    t = total[bucket_key].setdefault(
                        model, {"in": 0, "out": 0, "calls": 0, "hit": 0, "miss": 0})
                    t["in"] += m["in"]
                    t["out"] += m["out"]
                    t["calls"] += m["calls"]
                    t["hit"] += m.get("hit", 0)
                    t["miss"] += m.get("miss", 0)
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
