# -*- coding: utf-8 -*-
"""设定名词账本（B2/WA3-a，移植 cn-ai-novel-skills「设定词典」四字段，0.23.0）

四字段语义（outline-template「设定词典」表 + chapter-guide「新名词首现管理」）：
- first_chapter         首现章节：首现登记时自动填，此后不变（判断「本章是否首现」）
- reader_known_chapter  读者已知：揭示兑现后更新（把新揭示升格为读者已知）；
                        None=读者尚不知完整真相（写作约束：表述不得越过此边界）
- truth                 完整真相：作者视角真相，登记时一次写全（防作者被自己的
                        模糊表述带偏）；update_truth 仅供作者显式修正
- reveal_planned_ch     计划揭示：软到期窗口——与卡2 伏笔 recovery_window 同构，
                        但对象是设定名词而非情节伏笔（到期未揭示=due）

纯本地零 LLM；sidecar `追踪/设定账本.json`（version+entries，按 name 去重、
aliases 归并——以别名再登记或既有名词出现在新条目别名里都归并为同一条）。
所有 IO fail-open：sidecar 缺失/损坏按空账本处理，读路径零副作用，下次写时重建。

状态卡对接（只加适配不改结构）：state_card._build_sections 把 state_card_lines()
追加进「活跃伏笔(作者真相)」栏；账本 sidecar 不存在时返回 []，卡片输出与
0.22 逐字一致（证据在场才注入，不读配置——l0_checks 同款纪律）。
"""
from __future__ import annotations

import json
import os
import re

SIDECAR_VERSION = 1
_DUE_SOON_CHAPTERS = 5        # 与 tracking_store 卡2 同款：距计划揭示 ≤5 章即入临期
_TRUTH_CAP = 30               # 状态卡行内作者真相截断

_NUM_RE = re.compile(r"\d+")


def _norm(s: str) -> str:
    """名词归一化（去空白与书名号/引号外壳），归并判定的唯一口径"""
    return re.sub(r"\s+", "", (s or "")).strip("《》「」『』“”\"'")


def _sidecar_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "设定账本.json")


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load(proj: str) -> dict:
    """账本全量（缺失/损坏 → 空账本，读路径零副作用）"""
    data = _read_json(_sidecar_path(proj))
    if data and isinstance(data.get("entries"), list):
        data.setdefault("version", SIDECAR_VERSION)
        return data
    return {"version": SIDECAR_VERSION, "entries": []}


def _save(proj: str, data: dict) -> None:
    data["version"] = SIDECAR_VERSION
    _write_json(_sidecar_path(proj), data)


def _find(entries: list, name: str) -> int | None:
    """按名词或别名定位条目下标（归一化精确匹配优先）"""
    key = _norm(name)
    if not key:
        return None
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        if _norm(e.get("name")) == key:
            return i
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        if any(_norm(a) == key for a in (e.get("aliases") or [])):
            return i
    return None


def _merge_entries(base: dict, incoming: dict, extra: list) -> dict:
    """归并：既有非空字段不变量优先（首现不变/真相不变），空位由后来者补"""
    aliases = []
    for src in ([base.get("aliases")] + [e.get("aliases") for e in extra] +
                [incoming.get("aliases")] + [[incoming.get("name")]]):
        for a in src or []:
            n = _norm(a)
            if n and n != _norm(base.get("name")) and n not in {_norm(x) for x in aliases}:
                aliases.append(str(a).strip())
    merged = dict(base)
    merged["aliases"] = aliases
    for k in ("category", "truth"):
        if not str(merged.get(k) or "").strip():
            v = str(incoming.get(k) or "").strip()
            if not v:
                for e in extra:
                    v = str(e.get(k) or "").strip()
                    if v:
                        break
            merged[k] = v
    for k in ("reader_known_chapter", "reveal_planned_ch"):
        vals = [merged.get(k)] + [e.get(k) for e in extra] + [incoming.get(k)]
        nums = [int(v) for v in vals if isinstance(v, int)]
        if nums:
            merged[k] = min(nums)          # 读者已知/计划揭示都取最早承诺
    fc = [merged.get("first_chapter")] + [e.get("first_chapter") for e in extra]
    fcs = [int(v) for v in fc if isinstance(v, int)]
    if fcs:
        merged["first_chapter"] = min(fcs)
    return merged


def register(proj: str, num: int, name: str, category: str = "", truth: str = "",
             reveal_planned_ch: int | None = None, aliases: list | None = None) -> tuple:
    """登记设定名词（首现自动填 first_chapter=num）。

    同名/别名/既有名词出现在新条目别名里 → 归并为同一条（entries 去重）；
    既有非空字段一律保留（首现不变、真相不变），空位由本次登记补齐。
    Returns: (entry, created)
    """
    name = str(name or "").strip()
    if not name:
        return (None, False)
    data = load(proj)
    entries = data.setdefault("entries", [])
    incoming = {"name": name,
                "aliases": [str(a or "").strip() for a in (aliases or []) if str(a or "").strip()],
                "category": str(category or "").strip(),
                "first_chapter": int(num),
                "reader_known_chapter": None,
                "truth": str(truth or "").strip(),
                "reveal_planned_ch": int(reveal_planned_ch) if reveal_planned_ch else None}
    idx = _find(entries, name)
    merged_aliases = {_norm(a) for a in incoming["aliases"]}
    extra = []
    if idx is not None:
        extra.append(entries[idx])
    # 既有名词出现在本次别名里 → 一并归并
    for i, e in enumerate(entries):
        if i == idx or not isinstance(e, dict):
            continue
        if _norm(e.get("name")) in merged_aliases:
            extra.append(e)
    if extra:
        base = extra[0]
        merged = _merge_entries(base, incoming, extra[1:])
        keep = [e for i, e in enumerate(entries)
                if not any(e is x for x in extra)]
        keep.append(merged)
        data["entries"] = keep
        _save(proj, data)
        return (merged, False)
    entries.append(incoming)
    _save(proj, data)
    return (incoming, True)


def _mutate(proj: str, name: str, fn) -> dict | None:
    data = load(proj)
    entries = data.setdefault("entries", [])
    idx = _find(entries, name)
    if idx is None:
        return None
    fn(entries[idx])
    _save(proj, data)
    return entries[idx]


def mark_reader_known(proj: str, name: str, num: int) -> dict | None:
    """揭示兑现：读者已知边界推进到 num（揭示后更新；重复登记取最早章）"""
    def fn(e):
        old = e.get("reader_known_chapter")
        e["reader_known_chapter"] = min(int(old), int(num)) if isinstance(old, int) else int(num)
    return _mutate(proj, name, fn)


def update_truth(proj: str, name: str, truth: str) -> dict | None:
    """作者显式修正完整真相（登记时一次写全，本操作只留人工修正口）"""
    def fn(e):
        e["truth"] = str(truth or "").strip()
    return _mutate(proj, name, fn)


def set_reveal(proj: str, name: str, ch: int) -> dict | None:
    """设定/调整计划揭示章（软到期窗口）"""
    def fn(e):
        e["reveal_planned_ch"] = int(ch)
    return _mutate(proj, name, fn)


def _state_of(e: dict, num: int) -> str:
    """按章号三态：hidden（揭示前读者未知）/ due（到达计划揭示章仍未揭示）/ known（揭示后已知）"""
    rkc = e.get("reader_known_chapter")
    if isinstance(rkc, int) and rkc <= num:
        return "known"
    rpc = e.get("reveal_planned_ch")
    if isinstance(rpc, int) and rpc <= num:
        return "due"
    return "hidden"


def query(proj: str, num: int) -> list:
    """按章号查询：此刻读者已知什么/真相是什么/计划何时揭示。

    每条 {name, aliases, category, first_chapter, reader_known_chapter, truth,
    reveal_planned_ch, state(hidden|due|known), reader_known(bool)}，按首现章排序。
    """
    out = []
    for e in load(proj).get("entries") or []:
        if not isinstance(e, dict) or not str(e.get("name") or "").strip():
            continue
        item = dict(e)
        item["state"] = _state_of(e, num)
        item["reader_known"] = item["state"] == "known"
        out.append(item)
    out.sort(key=lambda x: (x.get("first_chapter") if isinstance(x.get("first_chapter"), int) else 0,
                            str(x.get("name"))))
    return out


def query_one(proj: str, name: str, num: int) -> dict | None:
    key = _norm(name)
    for item in query(proj, num):
        if _norm(item.get("name")) == key or any(
                _norm(a) == key for a in (item.get("aliases") or [])):
            return item
    return None


def reveal_due(proj: str, cur_num: int, horizon: int = _DUE_SOON_CHAPTERS) -> list:
    """揭示窗口临期/超期条目（未揭示已知）：[(entry, tag)]。

    tag ∈ {"已超N章", "到期", "剩N章"}；仅含 reveal_planned_ch 已登记且
    cur_num 未越过 horizon 的条目（证据在场才注入），按计划揭示章升序。
    """
    out = []
    for e in load(proj).get("entries") or []:
        if not isinstance(e, dict):
            continue
        if _state_of(e, cur_num) == "known":
            continue
        rpc = e.get("reveal_planned_ch")
        if not isinstance(rpc, int):
            continue
        if rpc > cur_num + horizon:
            continue
        if cur_num > rpc:
            tag = "已超%d章" % (cur_num - rpc)
        elif cur_num == rpc:
            tag = "到期"
        else:
            tag = "剩%d章" % (rpc - cur_num)
        out.append((e, tag))
    out.sort(key=lambda t: t[0].get("reveal_planned_ch") or 0)
    return out


def state_card_lines(proj: str, cur_num: int, cap: int = 4,
                     horizon: int = _DUE_SOON_CHAPTERS) -> list:
    """状态卡「活跃伏笔(作者真相)」栏适配行（只加适配不改结构）。

    「〔设定〕「名」（类别）首现第N章｜读者已知：…｜作者真相：…｜计划揭示：…」；
    sidecar 缺失/空 → []（卡片输出与 0.22 逐字一致）。
    """
    lines = []
    for e, tag in reveal_due(proj, cur_num, horizon)[:cap]:
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        cat = str(e.get("category") or "").strip()
        fc = e.get("first_chapter")
        known_ch = e.get("reader_known_chapter")
        truth = str(e.get("truth") or "").strip()[:_TRUTH_CAP] or "待补"
        rpc = e.get("reveal_planned_ch")
        reader = "第%d章起已知真相" % known_ch if isinstance(known_ch, int) else "尚不知完整真相"
        head = "〔设定〕「%s」%s｜读者已知：%s｜作者真相：%s" % (
            name, ("（%s）" % cat) if cat else "", reader, truth)
        if isinstance(rpc, int):
            head += "｜计划第%d章揭示（%s）" % (rpc, tag)
        if isinstance(fc, int):
            head += "｜首现第%d章" % fc
        lines.append(head)
    return lines
