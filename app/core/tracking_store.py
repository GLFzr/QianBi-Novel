# -*- coding: utf-8 -*-
"""追踪台账结构化存储（V2.1，深度研究 §4 + 台账最小化调研）

设计（事件日志 + 键控 upsert 双通道，禁用"小节照抄"）：
- sidecar JSON 是唯一真源（追踪/角色状态.json / 伏笔表.json）；
- LLM 只输出**本章变更**（JSON：字段 upsert + 追加记录行 + 新角色），本地合并；
- 现有 markdown（角色状态.md/伏笔表.md/时间线.md）降级为**代码渲染的派生视图**，
  供 chapter_header/压缩/共写等既有消费方零改动读取；
- 输出量绑定"本章出场实体数"而非章数——根除"照抄既有记录"的线性膨胀
  （V6 实测：13 章从 1.3k 涨到 8192 截顶）。
- 首次使用时从既有 markdown 惰性播种（老项目零迁移成本）。
任何解析失败由调用方回退全量模式；本模块自身 fail-open。
"""
from __future__ import annotations

import json
import os
import re

CHAR_FIELDS = ("当前身份", "当前能力", "关键关系", "公众形象", "待回收伏笔")
_RECORD_LINE_CAP = 12          # 派生视图里每角色最多带最近 N 条变更记录（防视图膨胀）
_FORESHADOW_COLS = ("伏笔", "类别", "埋设章节", "状态", "计划回收", "备注")


def _sidecar_path(proj: str, kind: str) -> str:
    return os.path.join(proj, "追踪", "%s.json" % kind)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---------------- 角色状态 ----------------

def _seed_characters_from_md(md: str) -> dict:
    """从既有 markdown（`## 名` + `- **字段**：值`）惰性播种 sidecar"""
    chars: dict = {}
    order: list = []
    cur = None
    for line in (md or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            cur = m.group(1).strip()
            if cur not in chars:
                chars[cur] = {k: "" for k in CHAR_FIELDS}
                chars[cur]["_records"] = []
                order.append(cur)
            continue
        if cur:
            fm = re.match(r"^-\s*\*\*(.+?)\*\*[：:]\s*(.*)$", line)
            if fm:
                field, val = fm.group(1).strip(), fm.group(2).strip()
                if field == "状态变更记录":
                    for ch, line_txt in re.findall(r"（第(\d+)章[：:]([^）]*)）", val):
                        chars[cur]["_records"].append({"ch": int(ch), "line": line_txt.strip()})
                elif field in chars[cur]:
                    chars[cur][field] = val
    return {"version": 1, "characters": chars, "order": order}


def load_characters(proj: str) -> dict:
    """角色 sidecar；缺失/损坏时从 markdown 惰性播种（并回写 sidecar）"""
    path = _sidecar_path(proj, "角色状态")
    data = _read_json(path)
    if data and isinstance(data.get("characters"), dict):
        return data
    md_path = os.path.join(proj, "追踪", "角色状态.md")
    md = ""
    try:
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
    except OSError:
        pass
    data = _seed_characters_from_md(md)
    _write_json(path, data)
    return data


def apply_character_updates(proj: str, num: int, updates: list, records: list,
                            new_chars: list) -> list:
    """把 LLM 的键控补丁合并进角色 sidecar。返回变更角色名列表（含新建）。

    updates: [{"id","field","value"}]；records: [{"id","line"}]（append-only 追加
    本章记录行）；new_chars: [{"id", 各字段..., "record"}]（新角色整条建立）。
    未知字段/空 id 忽略（fail-open）；同名键按本章最后一次写入生效。
    """
    data = load_characters(proj)
    chars, order = data["characters"], data.setdefault("order", [])
    changed = []
    for nc in new_chars or []:
        cid = str(nc.get("id") or "").strip()
        if not cid:
            continue
        if cid not in chars:
            chars[cid] = {k: str(nc.get(k) or "") for k in CHAR_FIELDS}
            chars[cid]["_records"] = []
            order.append(cid)
        else:
            for k in CHAR_FIELDS:
                if nc.get(k):
                    chars[cid][k] = str(nc[k])
        line = str(nc.get("record") or "").strip()
        if line:
            chars[cid]["_records"].append({"ch": int(num), "line": line})
        changed.append(cid)
    for u in updates or []:
        cid = str(u.get("id") or "").strip()
        field = str(u.get("field") or "").strip()
        if not cid or field not in CHAR_FIELDS:
            continue
        if cid not in chars:
            chars[cid] = {k: "" for k in CHAR_FIELDS}
            chars[cid]["_records"] = []
            order.append(cid)
        chars[cid][field] = str(u.get("value") or "")
        if cid not in changed:
            changed.append(cid)
    for r in records or []:
        cid = str(r.get("id") or "").strip()
        line = str(r.get("line") or "").strip()
        if not cid or not line:
            continue
        if cid not in chars:
            chars[cid] = {k: "" for k in CHAR_FIELDS}
            chars[cid]["_records"] = []
            order.append(cid)
        chars[cid]["_records"].append({"ch": int(num), "line": line})
        if cid not in changed:
            changed.append(cid)
    _write_json(_sidecar_path(proj, "角色状态"), data)
    return changed


def render_characters_md(proj: str) -> str:
    """从 sidecar 渲染角色状态 markdown（派生视图，供既有消费方零改动读取）"""
    data = load_characters(proj)
    chars, order = data["characters"], data.get("order") or list(data["characters"])
    out = ["# 角色状态追踪", ""]
    for name in order:
        c = chars.get(name)
        if c is None:
            continue
        out.append("## %s" % name)
        for k in CHAR_FIELDS:
            out.append("- **%s**：%s" % (k, c.get(k, "")))
        recs = (c.get("_records") or [])[-_RECORD_LINE_CAP:]
        rec_text = "".join("（第%d章：%s）" % (r["ch"], r["line"]) for r in recs) or "（暂无）"
        out.append("- **状态变更记录**：%s" % rec_text)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def character_brief_table(proj: str, max_chars: int = 1800) -> str:
    """给 LLM 的键值现状表（**不含变更记录历史**——照抄膨胀的根治点）"""
    data = load_characters(proj)
    chars, order = data["characters"], data.get("order") or list(data["characters"])
    lines = []
    used = 0
    for name in order:
        c = chars.get(name) or {}
        fields = "；".join("%s=%s" % (k, (c.get(k) or "").strip() or "无") for k in CHAR_FIELDS)
        line = "- %s：%s" % (name, fields)
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) or "（台账尚空——本章角色将首次入册）"


# ---------------- 伏笔表 ----------------

def parse_foreshadow_md(md: str) -> list:
    """伏笔 markdown 表格 → rows（与 load_foreshadow 的 md 播种同一套解析，纯函数）。

    memory.unfished_foreshadows 用它直接吃 `追踪/伏笔.md`（人工与反哺两条写路径
    的共同可见面），不强迫调用方先落 sidecar。缺列按空串补齐，非表行忽略。
    """
    rows, order = [], []
    for line in (md or "").splitlines():
        t = line.strip()
        if not (t.startswith("|") and t.endswith("|")):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        if len(cells) < 2 or set(t.replace("|", "").strip()) <= {"-", ":", " "}:
            continue
        if cells[0] in ("伏笔", "名称"):
            continue
        row = {k: cells[i] if i < len(cells) else "" for i, k in enumerate(_FORESHADOW_COLS)}
        if row["伏笔"] and row["伏笔"] not in order:
            rows.append(row)
            order.append(row["伏笔"])
    return rows


def load_foreshadow(proj: str) -> dict:
    path = _sidecar_path(proj, "伏笔表")
    data = _read_json(path)
    if data and isinstance(data.get("rows"), list):
        return data
    md_path = os.path.join(proj, "追踪", "伏笔.md")
    md = ""
    try:
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
    except OSError:
        pass
    data = {"version": 1, "rows": parse_foreshadow_md(md)}
    _write_json(path, data)
    return data


def apply_foreshadow_upserts(proj: str, upserts: list) -> list:
    """伏笔按名称键 upsert（同名以本章最后一次写入生效）。返回变更名列表"""
    data = load_foreshadow(proj)
    rows = data.setdefault("rows", [])
    index = {r.get("伏笔"): r for r in rows}
    changed = []
    for u in upserts or []:
        name = str(u.get("伏笔") or "").strip()
        if not name:
            continue
        row = {k: str(u.get(k) or "") for k in _FORESHADOW_COLS}
        row["伏笔"] = name
        if name in index:
            index[name].update({k: v for k, v in row.items() if v})
        else:
            rows.append(row)
            index[name] = row
        if name not in changed:
            changed.append(name)
    _write_json(_sidecar_path(proj, "伏笔表"), data)
    return changed


def render_foreshadow_md(proj: str) -> str:
    data = load_foreshadow(proj)
    out = ["# 伏笔追踪", "",
           "> 状态：未埋 / 已埋 / 已回收 / 已失效（显式废弃，理由写入备注列）", "",
           "| " + " | ".join(_FORESHADOW_COLS) + " |",
           "|------|------|----------|------|----------|------|"]
    for r in data["rows"]:
        out.append("| " + " | ".join(r.get(k, "") for k in _FORESHADOW_COLS) + " |")
    return "\n".join(out) + "\n"


# ---------------- 伏笔到期引擎（卡2/T3：纯本地派生，不落盘） ----------------
# 「计划回收」列约定填章号或章号区间；解析不出（「第N单元」「待定」等）视为无窗口。
# 派生字段（urgency/超期章数）全部程序计算，不写回 sidecar——状态枚举扩「已失效」
# 作为僵尸伏笔的显式终态，超出两态（已回收/已失效）的行都按活跃参与排序。

_NUM_RE = re.compile(r"\d+")


def parse_recovery_window(cell: str) -> tuple:
    """「计划回收」列 → (min_ch, max_ch)；解析不出 → (None, None)。

    支持：40 / 第40章 / 第40-45章 / 第40~45章 / 第40—45章（区间取 [min,max]，
    P2 原型坑①——区间不取首数字）；「第N单元」「待定」「无」等 → (None, None)。
    """
    t = str(cell or "").strip()
    if not t or "单元" in t:
        return (None, None)
    nums = [int(x) for x in _NUM_RE.findall(t)]
    if not nums:
        return (None, None)
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (min(nums), max(nums))


# urgency 分组序：超期(0) > 临期(1) > 无窗口(2) > 远期(3)；组内各自排序
_OVERDUE, _DUE_SOON, _NO_WINDOW, _LATER = 0, 1, 2, 3
_DUE_SOON_CHAPTERS = 5          # 剩余 ≤5 章即入「临期」（webnovel-writer 同款判据）


def _urgency_bucket(row: dict, cur_num: int) -> tuple:
    """单行 → (组序, 组内排序键, 展示标签)。标签同时供注入前缀与 L0 消费。"""
    if cur_num is None or cur_num < 0:
        lo, _hi = parse_recovery_window(row.get("计划回收"))
        return (_NO_WINDOW, 0, "无窗口") if lo is None else (_LATER, 0, "")
    lo, hi = parse_recovery_window(row.get("计划回收"))
    if lo is None:
        return (_NO_WINDOW, 0, "无窗口")
    if cur_num > hi:
        return (_OVERDUE, -(cur_num - hi), "超期%d章" % (cur_num - hi))
    if cur_num >= lo:
        return (_DUE_SOON, hi - cur_num, "剩%d章" % max(hi - cur_num, 0))
    remain = lo - cur_num
    if remain <= _DUE_SOON_CHAPTERS:
        return (_DUE_SOON, remain, "剩%d章" % remain)
    return (_LATER, lo, "")


def foreshadow_urgency(data, cur_num: int) -> list:
    """逐行派生 urgency（程序计算不落盘）：超期N章 > 剩≤N章 > 无窗口 > 远期。

    data: load_foreshadow() 的 dict（{"rows": [...]}）或 rows 列表；
    排除 状态∈(已回收,已失效)；返回 [(row, tag)]，tag ∈ {"超期N章", "剩N章",
    "无窗口", ""}。排序：超期优先（超期章数降序）→ 临期（剩余章数升序）→
    无窗口 → 远期（计划章升序）。解析/数据异常逐行跳过（fail-open）。
    """
    rows = data.get("rows") if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        status = str(r.get("状态") or "").strip()
        if status in ("已回收", "回收", "已失效"):
            continue
        try:
            bucket, key, tag = _urgency_bucket(r, cur_num)
        except (TypeError, ValueError):
            continue
        out.append((bucket, key, r, tag))
    out.sort(key=lambda t: (t[0], t[1]))
    return [(r, tag) for _b, _k, r, tag in out]
