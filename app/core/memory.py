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
