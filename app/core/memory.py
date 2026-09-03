# -*- coding: utf-8 -*-
"""记忆层 L1：章节摘要链 + 全局摘要（结构化追踪文件的读写辅助）"""
import os
import re

from .. import project


def chapter_summaries_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "章节摘要.md")


def global_summary_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "全局摘要.md")


def read_global_summary(proj: str) -> str:
    text = project.read_file(global_summary_path(proj))
    # 剥掉模板头
    text = re.sub(r"^# 全局摘要.*?\n\n", "", text, flags=re.S).strip()
    text = re.sub(r"^>.*?\n\n", "", text, flags=re.S).strip()
    if text in ("", "（尚未开始）"):
        return ""
    return text


def write_global_summary(proj: str, summary: str):
    project.write_file(global_summary_path(proj),
                       f"# 全局摘要\n\n> 每章定稿后滚动更新，是全书记忆的锚点。\n\n{summary.strip()}\n")


def append_chapter_summary(proj: str, num: int, title: str, summary: str):
    """按章号 upsert 一句话摘要，保持链有序"""
    path = chapter_summaries_path(proj)
    lines = project.read_file(path).splitlines()
    entries = {}   # num -> line
    header = []
    for line in lines:
        m = re.match(r"^-\s*第(\d+)章", line.strip())
        if m:
            entries[int(m.group(1))] = None  # 占位，后面重建
        elif not entries and line.strip():
            header.append(line)
    # 重新读已有条目
    for line in lines:
        m = re.match(r"^-\s*第(\d+)章[《\s](.*?)》(?:：|:)\s*(.+)$", line.strip())
        if m:
            entries[int(m.group(1))] = (m.group(2).strip(), m.group(3).strip())
    entries[num] = (title, summary.strip())
    if not header:
        header = ["# 章节摘要链", "", "> 每章一句话摘要，按章号追加。", ""]
    body = []
    for n, v in sorted(entries.items()):
        if isinstance(v, tuple) and (v[0] or v[1]):
            body.append(f"- 第{n}章《{v[0]}》：{v[1]}")
    project.write_file(path, "\n".join(header + body) + "\n")


def read_recent_summaries(proj: str, before_num: int, n: int = 3) -> str:
    """读 before_num 之前最近 n 章的摘要，拼成上下文文本"""
    path = chapter_summaries_path(proj)
    entries = []
    for line in project.read_file(path).splitlines():
        m = re.match(r"^-\s*第(\d+)章[《\s](.*?)》(?:：|:)\s*(.+)$", line.strip())
        if m:
            entries.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    recent = [e for e in entries if e[0] < before_num][-n:]
    if not recent:
        return ""
    return "\n".join(f"第{n_}章《{t}》：{s}" for n_, t, s in recent)


def unfished_foreshadows(proj: str, limit: int = 2000) -> str:
    """未回收伏笔节选（过滤已回收条目）

    伏笔表格式：| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |
    """
    text = project.read_file(project.get_tracking_path(proj, "伏笔"))
    if not text.strip():
        return ""
    kept = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and "---" not in s:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 4 and cells[0] != "伏笔" and (
                    "已回收" in cells[3] or cells[3] == "回收"):
                continue
        kept.append(line)
    out = "\n".join(kept).strip()
    return out[:limit] if out else ""


# ---------- 剧情反哺写回层（共写/补章的新实体·新规则·伏笔变动 → 世界书/伏笔表） ----------

_SECTION_RE = re.compile(r"^===\s*(.+?)\s*===\s*$")
_NO_CONTENT = {"无", "- 无", "（无）", "(无)", "（暂无）", "暂无", "无变动"}
_BACKFLOW_NOTE = "> 本分区由千笔自动维护（剧情反哺登记）；可人工修订条目，请勿删除本标题。"


def _split_sections(text: str) -> dict:
    """按 ===段名=== 切分模型输出 → {段名: 段正文}（段名去空格）"""
    sections, cur, buf = {}, None, []
    for line in (text or "").splitlines():
        m = _SECTION_RE.match(line.strip())
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).replace(" ", ""), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections


def _clean_lines(body: str) -> list:
    """段正文 → 去项目符号的有效行（跳过空行与「无」占位）"""
    out = []
    for line in (body or "").splitlines():
        s = line.strip().lstrip("-•*·").strip()
        if not s or s in _NO_CONTENT:
            continue
        out.append(s)
    return out


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip("《》「」“”\"'")


def _parse_entity_lines(body: str) -> list:
    """新实体段 → [(名称, 类别, 描述)]；名称｜类别｜描述，缺描述的纯垃圾行丢弃"""
    out = []
    for s in _clean_lines(body):
        parts = [p.strip() for p in re.split(r"[｜|]", s)]
        if len(parts) >= 3 and parts[0] and parts[2]:
            out.append((parts[0], parts[1] or "未分类", parts[2]))
        elif len(parts) == 2 and parts[0] and parts[1]:
            out.append((parts[0], "未分类", parts[1]))
    return out


def _parse_rule_lines(body: str) -> list:
    """新规则段 → [(名称, 描述)]；允许整行即规则（无名以全行为名）"""
    out = []
    for s in _clean_lines(body):
        parts = [p.strip() for p in re.split(r"[｜|]", s, maxsplit=1)]
        if parts[0]:
            out.append((parts[0], parts[1].strip() if len(parts) > 1 else ""))
    return out


def _parse_evolution_lines(body: str) -> list:
    """实体演进段 → [(名称, 字段, 旧值→新值)]；名称｜字段｜变化，缺名称的行丢弃"""
    out = []
    for s in _clean_lines(body):
        parts = [p.strip() for p in re.split(r"[｜|]", s)]
        if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
            out.append((parts[0], parts[1], "→".join(p for p in parts[2:] if p)))
        elif len(parts) == 2 and parts[0] and parts[1]:
            out.append((parts[0], "状态", parts[1]))
    return out


def parse_backflow(text: str) -> dict:
    """解析 MEMORY_BACKFLOW_PROMPT 输出（七段），缺段→空值，永不抛异常。

    Returns:
        {"entities": [(名, 类别, 描述)], "rules": [(名, 描述)],
         "evolutions": [(名, 字段, 旧值→新值)], "revelations": [(名, 描述)],
         "foreshadow_adds": [(伏笔, 类别, 计划回收)], "foreshadow_payoffs": [文本],
         "deviations": [文本], "summary": 首行文本}
    """
    empty = {"entities": [], "rules": [], "evolutions": [], "revelations": [],
             "foreshadow_adds": [], "foreshadow_payoffs": [],
             "deviations": [], "summary": ""}
    try:
        secs = _split_sections(text)
        adds, payoffs = [], []
        for s in _clean_lines(secs.get("伏笔变动", "")):
            parts = [p.strip() for p in re.split(r"[｜|]", s)]
            head = parts[0].strip("[]【】:： ").strip()
            if head.startswith("新增") or head.startswith("埋设"):
                if len(parts) >= 2 and parts[1]:
                    adds.append((parts[1],
                                 parts[2] if len(parts) > 2 and parts[2] else "未分类",
                                 parts[3] if len(parts) > 3 and parts[3] else "待定"))
            elif head.startswith("回收"):
                rest = "｜".join(p for p in parts[1:] if p)
                if rest:
                    payoffs.append(rest)
        summary = ""
        for s in _clean_lines(secs.get("一句话摘要", "")):
            summary = s
            break
        return {"entities": _parse_entity_lines(secs.get("新实体", "")),
                "rules": _parse_rule_lines(secs.get("新规则", "")),
                "evolutions": _parse_evolution_lines(secs.get("实体演进", "")),
                "revelations": _parse_rule_lines(secs.get("世界观揭示", "")),
                "foreshadow_adds": adds,
                "foreshadow_payoffs": payoffs,
                "deviations": _clean_lines(secs.get("偏离点", "")),
                "summary": summary}
    except Exception:  # noqa: BLE001
        return empty


def parse_entity_rules(text: str) -> tuple:
    """从任意 ===段=== 输出中提取新实体/新规则（自动档⑤复用，零新增 LLM）"""
    try:
        secs = _split_sections(text)
        return (_parse_entity_lines(secs.get("新实体", "")),
                _parse_rule_lines(secs.get("新规则", "")))
    except Exception:  # noqa: BLE001
        return [], []


def parse_evolution_reveals(text: str) -> tuple:
    """从任意 ===段=== 输出中提取实体演进/世界观揭示（自动档复用，零新增 LLM）"""
    try:
        secs = _split_sections(text)
        return (_parse_evolution_lines(secs.get("实体演进", "")),
                _parse_rule_lines(secs.get("世界观揭示", "")))
    except Exception:  # noqa: BLE001
        return [], []


def _split_worldbook_section(doc: str) -> tuple:
    """世界书全文 → (分区前文本, 追加分区文本|None, 分区后文本)。分区到下一个二级标题或文末。"""
    heading = project.WORLDBOOK_BACKFLOW_HEADING
    lines = doc.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            start = i
            break
    if start is None:
        return doc, None, ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^##\s+[^#]", lines[j]):
            end = j
            break
    return "\n".join(lines[:start]), "\n".join(lines[start:end]), "\n".join(lines[end:])


_ENTRY_RE = re.compile(r"^-\s*\*\*(.+?)\*\*（(.*?)）[：:]\s*(.*)$")
_FIRST_SEEN_RE = re.compile(r"｜\s*首见第(\d+)章")
PROPOSAL_PATH = "设定/世界书_修正提案.md"
_PROPOSAL_HEADER = ("# 世界书修正提案\n\n"
                    "> 由千笔自动登记（疑似世界书条目过时/登记错误）。本文件**不会自动并入世界书**，请人工核对后处理。\n")


def _decompose_entry(line: str):
    """追加分区条目行 → (名称, 类别, 描述, 首见章号|None)；非条目行 None"""
    m = _ENTRY_RE.match(line.strip())
    if not m:
        return None
    rest = m.group(3)
    fs = _FIRST_SEEN_RE.search(rest)
    desc = _FIRST_SEEN_RE.sub("", rest).rstrip(" ｜|").strip()
    return m.group(1).strip(), m.group(2).strip(), desc, (fs.group(1) if fs else None)


def _append_worldbook_proposals(proj: str, num: int, lines: list):
    """修正提案追加落盘（只写提案文件，不动世界书本体）"""
    path = os.path.join(proj, PROPOSAL_PATH)
    doc = project.read_file(path)
    if not doc.strip():
        doc = _PROPOSAL_HEADER
    block = f"\n## 第{num}章\n" + "\n".join(lines) + "\n"
    project.write_file(path, doc.rstrip("\n") + "\n" + block)


_CORRECTION_MARK_RE = re.compile(r"[【\[]\s*世界书修正\s*[】\]]")


def propose_worldbook_corrections(proj: str, num: int, items: list) -> int:
    """审校双轨裁决登记：带【世界书修正】标记的条目 = 正文自洽而世界书条目疑过时

    只追加 设定/世界书_修正提案.md（人工核对后手动并入），不改世界书本体、
    不改变该条目在审校中的 marginal 定性。返回登记条数。
    """
    lines = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        text = (it.get("text") or "").strip()
        if text and _CORRECTION_MARK_RE.search(text):
            lines.append(f"- [审校修正] {text}")
    if lines:
        _append_worldbook_proposals(proj, num, lines)
    return len(lines)


def read_worldbook_additional(proj: str) -> str:
    """只取世界书「追加登记」分区正文（不含标题与提示行），无分区→空串"""
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    _, section, _ = _split_worldbook_section(doc)
    if not section:
        return ""
    body = "\n".join(section.splitlines()[1:]).strip()
    return re.sub(r"^>.*$", "", body, flags=re.M).strip()


def upsert_worldbook_entries(proj: str, num: int, entities: list, rules: list,
                             evolutions: list = None, revelations: list = None) -> dict:
    """新实体/新规则/演进幂等写入世界书「追加登记」分区（只动该分区，其余逐字节不动）。

    - 新实体/新规则/世界观揭示：分区内同名（归一化）→ 原位更新描述，保留「首见第N章」；
      名称在分区外世界书全文已出现 → 跳过（不算新东西）
    - 实体演进：实体已在「追加登记」→ 描述原位合并（保留旧描述与首见，追加
      「第N章 字段 旧→新」）；实体只在分区外（人工区）→ 写入修正提案文件，不强改
    - 写时重读文件，防与人工编辑竞写

    Returns: {"added": n, "updated": n, "skipped": n, "evolved": n, "proposed": n}
    """
    result = {"added": 0, "updated": 0, "skipped": 0, "evolved": 0, "proposed": 0}
    batch, seen = [], set()
    for name, cat, desc in (entities or []):
        key = _norm_name(name)
        if name and desc and key and key not in seen:
            seen.add(key)
            batch.append((name.strip(), (cat or "未分类").strip(),
                          " ".join(desc.split())))
    for name, desc in (rules or []):
        key = _norm_name(name)
        if name and key and key not in seen:
            seen.add(key)
            batch.append((name.strip(), "规则", " ".join((desc or "").split())))
    for name, desc in (revelations or []):
        key = _norm_name(name)
        if name and desc and key and key not in seen:
            seen.add(key)
            batch.append((name.strip(), "世界观", " ".join(desc.split())))
    evos, evos_seen = [], set()
    for name, field, change in (evolutions or []):
        key = _norm_name(name)
        if name and field and change and key and (key, field) not in evos_seen:
            evos_seen.add((key, field))
            evos.append((name.strip(), field.strip(), " ".join(change.split())))
    if not batch and not evos:
        return result

    path = os.path.join(proj, project.WORLDBOOK_PATH)
    doc = project.read_file(path)   # 写时重读
    prefix, section, suffix = _split_worldbook_section(doc)
    heading = project.WORLDBOOK_BACKFLOW_HEADING
    if section is None:
        sec_lines = [heading, "", _BACKFLOW_NOTE, ""]
    else:
        sec_lines = section.splitlines()
    outside_norm = _norm_name(prefix + "\n" + suffix)

    existing = {}   # name_norm -> 分区内行号
    for i, ln in enumerate(sec_lines):
        m = _ENTRY_RE.match(ln.strip())
        if m:
            existing[_norm_name(m.group(1))] = i

    for name, cat, desc in batch:
        key = _norm_name(name)
        if key in existing:
            i = existing[key]
            m = _ENTRY_RE.match(sec_lines[i].strip())
            fs = _FIRST_SEEN_RE.search(m.group(3)) if m else None
            first = f"第{fs.group(1)}章" if fs else f"第{num}章"
            sec_lines[i] = f"- **{name}**（{cat}）：{desc} ｜ 首见{first}"
            result["updated"] += 1
        elif key in outside_norm:
            result["skipped"] += 1
        else:
            sec_lines.append(f"- **{name}**（{cat}）：{desc} ｜ 首见第{num}章")
            existing[key] = len(sec_lines) - 1
            result["added"] += 1

    proposals = []
    for name, field, change in evos:
        key = _norm_name(name)
        if key in existing:
            de = _decompose_entry(sec_lines[existing[key]])
            if not de:
                result["skipped"] += 1
                continue
            old_name, cat0, desc0, first_n = de
            evo_note = f"第{num}章 {field} {change}"
            new_desc = f"{desc0}；{evo_note}" if desc0 else evo_note
            first = f"第{first_n}章" if first_n else f"第{num}章"
            sec_lines[existing[key]] = (
                f"- **{old_name}**（{cat0}）：{new_desc} ｜ 首见{first}")
            result["evolved"] += 1
        elif key in outside_norm:
            proposals.append(
                f"- [实体演进] {name}｜{field}｜{change}（正文自洽，疑似世界书原条目过时）")
        else:
            result["skipped"] += 1

    if proposals:
        _append_worldbook_proposals(proj, num, proposals)
        result["proposed"] = len(proposals)
    if result["added"] == 0 and result["updated"] == 0 and result["evolved"] == 0:
        return result
    new_doc = prefix
    if new_doc and not new_doc.endswith("\n"):
        new_doc += "\n"
    new_doc += "\n".join(sec_lines)
    if suffix:
        new_doc += "\n" + suffix
    project.write_file(path, new_doc + "\n")
    return result


_FORESHADOW_HEADER = ("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                      "|------|------|----------|------|----------|------|")


def _foreshadow_match(cell_norm: str, text_norm: str) -> bool:
    return bool(cell_norm and text_norm and
                (cell_norm in text_norm or text_norm in cell_norm))


def apply_foreshadow_diff(proj: str, num: int, adds: list, payoffs: list) -> dict:
    """伏笔表增量补丁：新增去重；回收只命中既有未回收行（无命中不臆造）。

    adds: [(伏笔文本, 类别, 计划回收)]；payoffs: [回收描述文本]
    Returns: {"added": n, "payoff": n, "skipped": n}
    """
    result = {"added": 0, "payoff": 0, "skipped": 0}
    if not adds and not payoffs:
        return result
    path = project.get_tracking_path(proj, "伏笔")
    lines = project.read_file(path).splitlines()

    table_rows = []   # (行号, cells)
    header_idx, last_table_idx = None, None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        last_table_idx = i
        if "---" in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and cells[0] == "伏笔":
            header_idx = i
            continue
        if len(cells) >= 4:
            table_rows.append((i, cells))

    new_rows, added_norms = [], []
    for text, cat, planned in (adds or []):
        text = (text or "").replace("\n", " ").replace("|", "｜").strip()
        if not text:
            continue
        t_norm = _norm_name(text)
        dup = any(_foreshadow_match(_norm_name(cells[0]), t_norm)
                  for _, cells in table_rows) or any(
            _foreshadow_match(n, t_norm) for n in added_norms)
        if dup:
            result["skipped"] += 1
            continue
        new_rows.append(f"| {text} | {(cat or '未分类').strip()} | 第{num}章 | 新设 "
                        f"| {(planned or '待定').strip()} | 反哺登记 |")
        added_norms.append(t_norm)
        result["added"] += 1

    for pay in (payoffs or []):
        p_norm = _norm_name(pay)
        hit = None
        for i, cells in table_rows:
            if "已回收" in cells[3] or cells[3] == "回收":
                continue
            if _foreshadow_match(_norm_name(cells[0]), p_norm):
                hit = (i, cells)
                break
        if not hit:
            result["skipped"] += 1
            continue
        i, cells = hit
        cells[3] = "已回收"
        while len(cells) < 6:
            cells.append("")
        note = f"第{num}章回收（反哺）"
        cells[5] = (cells[5] + "；" + note) if cells[5] else note
        lines[i] = "| " + " | ".join(cells) + " |"
        result["payoff"] += 1

    if result["added"] == 0 and result["payoff"] == 0:
        return result
    if new_rows:
        if header_idx is None:
            insert = (last_table_idx + 1) if last_table_idx is not None else len(lines)
            lines[insert:insert] = _FORESHADOW_HEADER.splitlines() + new_rows
        else:
            lines[last_table_idx + 1:last_table_idx + 1] = new_rows
    project.write_file(path, "\n".join(lines) + "\n")
    return result
