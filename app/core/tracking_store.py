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
           "> 状态：未埋 / 已埋 / 推进中 / 已回收 / 已失效（显式废弃，理由写入备注列；"
           "推进中=有推进事件未回收，B4/WA4 中间态）", "",
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


# ---------------- 伏笔补链（B4/WA4：advance 中间态+plant 前置校验+重写回补） ----------------
# 状态机：未埋/新设 → 已埋 → 推进中（本章有推进事件但未回收）→ 已回收；
# 已失效（显式废弃）可从任意非终态进入。卡2 引擎（parse_recovery_window/
# foreshadow_urgency）零推翻——「推进中」不在排除集内，照常按活跃参与排序。
# 推进事件落 sidecar `追踪/伏笔表.json` 的 advances 追加日志（{name, ch, from,
# to}），供章重写后回滚（rollback_foreshadow_advances）——回滚只恢复「本章造成
# 的状态迁移」，后续章节已推进的状态不动。

_ADVANCED = "推进中"
_TERMINAL = ("已回收", "回收", "已失效")


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip("《》「」『』“”\"'")


def _row_index(rows: list) -> dict:
    return {r.get("伏笔"): r for r in rows
            if isinstance(r, dict) and str(r.get("伏笔") or "").strip()}


def _match_row(index: dict, name: str):
    """精确 → 归一化 → 唯一包含（与 memory.apply_foreshadow_diff 同口径）；
    歧义多命中视为查无此行（不臆造）。"""
    name = str(name or "").strip()
    if not name:
        return None
    if name in index:
        return index[name]
    key = _norm_name(name)
    for n, r in index.items():
        if _norm_name(n) == key:
            return r
    hits = [r for n, r in index.items()
            if key and n and (key in _norm_name(n) or _norm_name(n) in key)]
    return hits[0] if len(hits) == 1 else None


def validate_plant_window(cell: str, planted_ch: int | None = None) -> tuple:
    """plant 前置校验（纯函数）：回收窗口字段合法性 → (ok, reason)。

    - 空/待定/「第N单元」→ (True, "无窗口")——合法缺省，引擎按无窗口参与排序；
    - 数字窗口 max < 埋设章 → (False, "计划回收第N章早于埋设第M章")——唯一非法态；
    - 其余（含解析不出的自由文本）→ (True, "")。校验只警示不阻断（fail-open）。
    """
    t = str(cell or "").strip()
    if not t or "待定" in t or "单元" in t:
        return (True, "无窗口")
    lo, hi = parse_recovery_window(t)
    if lo is None:
        return (True, "")
    if planted_ch is not None and hi < planted_ch:
        return (False, "计划回收第%d章早于埋设第%d章" % (hi, planted_ch))
    return (True, "")


def plant_foreshadow(proj: str, num: int, upserts: list) -> dict:
    """新伏笔登记（带前置校验的 plant 通道）：只对新增行校验回收窗口合法性，
    警示不阻断（fail-open）——非法窗口原样落表（作者可见原话），warnings 供
    待确认卡/日志消费；更新既有行不校验（改期/回收任意合法）。
    Returns: {"changed": [...], "warnings": [{"伏笔", "reason"}]}
    """
    data = load_foreshadow(proj)
    index = _row_index(data.get("rows") or [])
    norm_known = {_norm_name(n) for n in index}
    warnings = []
    for u in upserts or []:
        if not isinstance(u, dict):
            continue
        name = str(u.get("伏笔") or "").strip()
        if not name or name in index or _norm_name(name) in norm_known:
            continue                      # 既有行更新不校验
        planted = u.get("埋设章节")
        nums = _NUM_RE.findall(str(planted or ""))
        planted_ch = int(nums[0]) if nums else int(num)
        ok, reason = validate_plant_window(u.get("计划回收"), planted_ch)
        if not ok:
            warnings.append({"伏笔": name, "reason": reason})
    changed = apply_foreshadow_upserts(proj, upserts)
    return {"changed": changed, "warnings": warnings}


def advance_foreshadow(proj: str, num: int, names: list) -> dict:
    """伏笔推进（中间态登记）：本章有推进事件但未回收 → 状态=推进中。

    - 终态（已回收/已失效）不推进；同章同名去重（重写重登记幂等）；
    - 每次迁移落 advances 日志 {name, ch, from, to}（重写回补的依据）；
    - 名称匹配失败跳过不臆造。Returns: {"advanced": [...], "skipped": [(名, 原因)]}
    """
    data = load_foreshadow(proj)
    rows = data.setdefault("rows", [])
    log = data.setdefault("advances", [])
    done = {(e.get("name"), e.get("ch")) for e in log if isinstance(e, dict)}
    index = _row_index(rows)
    advanced, skipped = [], []
    for name in names or []:
        name = str(name or "").strip()
        if not name:
            continue
        row = _match_row(index, name)
        if row is None:
            skipped.append((name, "未登记"))
            continue
        row_name = str(row.get("伏笔"))
        status = str(row.get("状态") or "").strip() or "未埋"
        if status in _TERMINAL:
            skipped.append((name, status))
            continue
        if (row_name, int(num)) in done:
            skipped.append((name, "本章已登记推进"))
            continue
        log.append({"name": row_name, "ch": int(num), "from": status, "to": _ADVANCED})
        row["状态"] = _ADVANCED
        advanced.append(row_name)
    if advanced:
        _write_json(_sidecar_path(proj, "伏笔表"), data)
    return {"advanced": advanced, "skipped": skipped}


def rollback_foreshadow_advances(proj: str, num: int) -> list:
    """重写回补：第 num 章重写后，撤销该章按旧版登记的伏笔推进（回到重写前状态）。

    逐条倒序处理该章 advances 日志：当前状态仍是该章迁入态且**无后续章接续推进**
    → 恢复迁出态；已被后续章推进/回收的不动状态（后续章事件在场即视为接续）。
    该章日志条目一律移除——重写后本章事件清零，重定稿时重新登记。
    返回回补了状态的伏笔名列表。
    """
    data = load_foreshadow(proj)
    rows = data.setdefault("rows", [])
    log = data.get("advances")
    if not isinstance(log, list):
        return []
    index = _row_index(rows)
    num = int(num)
    later = {e.get("name") for e in log
             if isinstance(e, dict) and isinstance(e.get("ch"), int) and e["ch"] > num}
    keep, rolled = [], []
    for e in reversed(log):
        if not isinstance(e, dict):
            keep.append(e)
            continue
        try:
            ch = int(e.get("ch"))
        except (TypeError, ValueError):
            keep.append(e)
            continue
        if ch != num:
            keep.append(e)
            continue
        row = index.get(e.get("name"))
        if (row is not None and e.get("name") not in later
                and str(row.get("状态") or "").strip() == str(e.get("to") or "")):
            row["状态"] = str(e.get("from") or "未埋")
            rolled.append(str(row.get("伏笔")))
    rolled_log = list(reversed(keep))
    if rolled or len(rolled_log) != len(log):
        data["advances"] = rolled_log
        _write_json(_sidecar_path(proj, "伏笔表"), data)
    return rolled


# ---------------- 章节计划（B7：goink chapter_plans 三槽位 next/near/far，0.23.0） ----------------
# 「当前规划状态」而非「历史记录」（goink 固定 3 行 UPSERT 同思想）：sidecar
# `追踪/章节计划.json` —— {version:1, next:{content,source_ch},
# near:[{content,target_ch}], far:[{content}], consumed:[已流转章号]}。
# - next  下一章必写（细纲装配的硬约束槽）；source_ch=登记/升格发生章；
# - near  近 3-5 章计划（参考）；target_ch 只排不滤——goink 纪律：LLM 估算的
#         章号永远进排序不进过滤，逾期与否由 review 语义复核校准；
# - far   远期弧线（方向性，无章号）。
# 流转（plan_consume，章定稿时调用）：next 清空出册、near[0] 升格为 next、
# 其余前移——批量写作「写完一章立即维护再写下一章」的规划面；consumed 日志保
# 同章重写重定稿幂等（不二次升格）。
# 纯本地零 LLM；IO 全 fail-open（缺失/损坏按空计划处理，读路径零副作用——
# setting_ledger 同款纪律）；三槽位全空 → render_for_outline 返回空串（证据在
# 场才注入，不读配置）。
# TODO(接线批)：render_for_outline 挂进 planning/stages 细纲装配、plan_consume
# 挂章定稿归档分支——本卡只交付账本+查询/渲染函数，不碰 stages/prompts。

PLAN_SIDECAR = "章节计划"
_NEAR_RENDER_CAP = 5          # 细纲注入时 near 最多展示条数（存储不截，注入有界）
_FAR_RENDER_CAP = 5


def _empty_plan() -> dict:
    return {"version": 1, "next": None, "near": [], "far": [], "consumed": []}


def _plan_path(proj: str) -> str:
    return _sidecar_path(proj, PLAN_SIDECAR)


def load_chapter_plan(proj: str) -> dict:
    """章节计划 sidecar（缺失/损坏 → 空计划；读路径零副作用，不回写）。

    顺带做形态归一（fail-open）：next 非字典/空内容 → None；near/far 条目非
    字典或空内容 → 丢弃；target_ch/consumed 章号非 int → 丢弃；同文条目去重。
    """
    data = _read_json(_plan_path(proj))
    if not isinstance(data, dict):
        return _empty_plan()
    out = _empty_plan()
    nxt = data.get("next")
    if isinstance(nxt, dict) and str(nxt.get("content") or "").strip():
        out["next"] = {"content": str(nxt["content"]).strip(),
                       "source_ch": nxt.get("source_ch")
                       if isinstance(nxt.get("source_ch"), int) else None}
    for key in ("near", "far"):
        items = out[key]
        for e in data.get(key) or []:
            if not isinstance(e, dict):
                continue
            content = str(e.get("content") or "").strip()
            if not content or any(x["content"] == content for x in items):
                continue
            row = {"content": content}
            if key == "near":
                row["target_ch"] = e.get("target_ch") \
                    if isinstance(e.get("target_ch"), int) else None
            items.append(row)
    cons = data.get("consumed")
    if isinstance(cons, list):
        out["consumed"] = sorted({c for c in cons if isinstance(c, int)})
    return out


def _save_plan(proj: str, data: dict) -> None:
    data["version"] = 1
    _write_json(_plan_path(proj), data)


def plan_set_next(proj: str, content: str, source_ch: int | None = None) -> dict | None:
    """UPSERT next 槽（下一章必写）。content 空白 → 清空（返回 None）"""
    data = load_chapter_plan(proj)
    content = str(content or "").strip()
    if not content:
        data["next"] = None
    else:
        data["next"] = {"content": content,
                        "source_ch": int(source_ch) if isinstance(source_ch, int) else None}
    _save_plan(proj, data)
    return data["next"]


def plan_add_near(proj: str, content: str, target_ch: int | None = None) -> dict | None:
    """近章计划追加（同文幂等：既有同文条目仅更新 target_ch，不重复追加）"""
    content = str(content or "").strip()
    if not content:
        return None
    data = load_chapter_plan(proj)
    hit = next((e for e in data["near"] if e["content"] == content), None)
    if hit is None:
        hit = {"content": content, "target_ch": None}
        data["near"].append(hit)
    hit["target_ch"] = int(target_ch) if isinstance(target_ch, int) else None
    _save_plan(proj, data)
    return hit


def plan_add_far(proj: str, content: str) -> dict | None:
    """远期弧线追加（同文幂等）。返回该条目；空白内容忽略"""
    content = str(content or "").strip()
    if not content:
        return None
    data = load_chapter_plan(proj)
    hit = next((e for e in data["far"] if e["content"] == content), None)
    if hit is None:
        hit = {"content": content}
        data["far"].append(hit)
        _save_plan(proj, data)
    return hit


def plan_consume(proj: str, num: int) -> dict:
    """章定稿流转：next 清空出册、near[0] 升格为 next（source_ch=本章）、其余
    前移；far 不动。consumed 日志保幂等——同章重写重定稿不二次升格。

    Returns: {"cleared": 被清空的原 next 内容或 None,
              "promoted": 升格为 next 的原 near[0] 内容或 None,
              "skipped": 本章已流转过/章号非法 → True（no-op）}
    """
    try:
        num = int(num)
    except (TypeError, ValueError):
        return {"cleared": None, "promoted": None, "skipped": True}
    data = load_chapter_plan(proj)
    if num in data["consumed"]:
        return {"cleared": None, "promoted": None, "skipped": True}
    old = data.get("next") or {}
    cleared = str(old.get("content") or "").strip() or None
    promoted = None
    if data["near"]:
        head = data["near"].pop(0)
        promoted = head["content"]
        data["next"] = {"content": head["content"], "source_ch": num}
    else:
        data["next"] = None
    data["consumed"].append(num)
    _save_plan(proj, data)
    return {"cleared": cleared, "promoted": promoted, "skipped": False}


def plan_query(proj: str) -> dict:
    """细纲装配查询：next 必写 / near 参考 / far 远景（fail-open 恒有全键）"""
    data = load_chapter_plan(proj)
    nxt = data.get("next") or {}
    return {"next": str(nxt.get("content") or "").strip() or None,
            "next_source_ch": nxt.get("source_ch"),
            "near": [dict(e) for e in data.get("near") or []],
            "far": [dict(e) for e in data.get("far") or []]}


def render_for_outline(proj: str, max_chars: int = 1200) -> str:
    """细纲 prompt 的章节计划块（账本注入风格；三槽位全空 → ""，调用方零注入）。

    头行标注三槽位语义（next=必写 / near=参考 / far=远景）+ 每槽一行；near 取
    前 _NEAR_RENDER_CAP 条（target_ch 仅作「约第N章」展示注，只排不滤）、far 取
    前 _FAR_RENDER_CAP 条；累计超 max_chars 停止追加（character_brief_table
    同款预算法）。next 注明登记章（溯源）。
    """
    q = plan_query(proj)
    lines = []
    if q["next"]:
        src = "（第%d章登记）" % q["next_source_ch"] if q["next_source_ch"] else ""
        lines.append("- 必写（next）：%s%s" % (q["next"], src))
    if q["near"]:
        parts = ["约第%d章 %s" % (e["target_ch"], e["content"]) if e["target_ch"]
                 else e["content"] for e in q["near"][:_NEAR_RENDER_CAP]]
        lines.append("- 近期（near）：" + "；".join(parts))
    if q["far"]:
        parts = [e["content"] for e in q["far"][:_FAR_RENDER_CAP]]
        lines.append("- 远景（far）：" + "；".join(parts))
    if not lines:
        return ""
    out = ["【章节计划】（next=下一章必写；near=近期参考；far=远景方向）"]
    used = len(out[0])          # 头行计入预算
    for ln in lines:
        if used + len(ln) > max_chars:
            break
        out.append(ln)
        used += len(ln)
    return "\n".join(out)
