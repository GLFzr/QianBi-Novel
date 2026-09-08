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

def load_foreshadow(proj: str) -> dict:
    path = _sidecar_path(proj, "伏笔表")
    data = _read_json(path)
    if data and isinstance(data.get("rows"), list):
        return data
    md_path = os.path.join(proj, "追踪", "伏笔.md")
    rows, order = [], []
    try:
        with open(md_path, encoding="utf-8") as f:
            for line in f:
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
    except OSError:
        pass
    data = {"version": 1, "rows": rows}
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
           "> 状态：未埋 / 已埋 / 已回收", "",
           "| " + " | ".join(_FORESHADOW_COLS) + " |",
           "|------|------|----------|------|----------|------|"]
    for r in data["rows"]:
        out.append("| " + " | ".join(r.get(k, "") for k in _FORESHADOW_COLS) + " |")
    return "\n".join(out) + "\n"
