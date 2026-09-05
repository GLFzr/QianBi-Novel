# -*- coding: utf-8 -*-
"""共享前缀架构（体验轮 A1'）：项目级逐字节稳定头部，全调用族缓存命中的主力

DeepSeek 缓存三定律（api-docs.deepseek.com/guides/kv_cache + deepseek-harness 实证）：
  ① 前缀按位置逐字节匹配，一个字节不同，从该字节起全部作废；
  ② 静态前置、动态殿后；
  ③ append-only。
本模块产出所有大调用的公共头部 H——命中率 = ΣH/(ΣH+ΣT)，H 做大是省钱不是浪费
（命中部分只收约 1/10 价）。

头部组成（固定顺序、固定截断，**禁止**加入章号/日期/任何随章变化的内容）：
  01 题材预设块（phase 无关口径）
  02 核心设定节选（固定截断）
  03 金手指约束条款 + 全局红线 + 授权自创清单（constraints_block）
  04 正则契约全文（must 规则——H 的主力）
  05 世界书·常驻条目（wb.constant_entries，按名称排序）
  06 全局写作纪律（co_writing.STYLE_DISCIPLINE）

缓存：按源文件 mtime 指纹做进程内 LRU——文件一变即失效，进程内两次构造逐字节一致。
"""
import functools
import os
import re

from .. import project

# 源文件集合：任一变化即头部失效（mtime 指纹）
_SOURCES = ("设定/题材定位.md", "设定/正则.md", "设定/世界书.md")


def constraints_block(proj: str, budget: int = 1500) -> str:
    """核心设定约束注入块（自 canon_audit 迁入：shared_prefix 与清算共用同一字节源）。
    金手指约束条款/全局红线/授权自创清单——审校漏报的根源是这三节不在扫描范围。"""
    core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))
    blocks = []
    for head in ("金手指约束条款", "全局红线", "授权自创清单"):
        m = re.search(r"###?\s*%s(.*?)(?=\n###?\s|\Z)" % re.escape(head), core, re.S)
        if m and m.group(1).strip():
            blocks.append("【%s】%s" % (head, m.group(1).strip()[:600]))
    out = "\n\n".join(blocks)
    return out[:budget] if out else ""


def _fingerprint(proj: str) -> str:
    parts = []
    for rel in _SOURCES:
        p = os.path.join(proj, *rel.split("/"))
        try:
            parts.append("%s:%r" % (rel, os.path.getmtime(p)))
        except OSError:
            parts.append(rel + ":-")
    return "|".join(parts)


def project_header(proj: str) -> str:
    return _header_cached(proj, _fingerprint(proj))


def chapter_header(proj: str, num: int) -> str:
    """章级共享段（体验轮终态）：同章所有调用间逐字节一致的内容。

    组成：本章细纲（含冻结表）+ 角色状态 + 时间线 + 待回收伏笔 + 上一章结尾与文风样本。
    这些内容在章循环开头组装一次、章内不变——把「同章恒定」从动态尾提升到
    紧跟项目头的第二层前缀，同章 10+ 次调用全部命中第二层。
    指纹含正文草稿路径（草稿定稿后内容更新，下一阶段调用看到的是新基准）。
    """
    parts = [f"【第 {num} 章共享上下文（同章所有步骤使用同一份，前后引用以此为准）】"]
    outline = project.read_file(project.get_outline_path(proj, num))
    if outline.strip():
        parts.append("## 本章细纲" + chr(10) + outline.strip())
    for rel, head in (("角色状态", "角色状态"), ("时间线", "时间线"), ("伏笔", "待回收伏笔")):
        body = project.read_file(project.get_tracking_path(proj, rel))[:1500]
        if body.strip():
            parts.append("## " + head + chr(10) + body.strip())
    from . import memory
    recent = memory.read_recent_summaries(proj, num, n=2)
    if recent:
        parts.append("## 近章摘要" + chr(10) + recent.strip())
    return "\n\n".join(parts) + "\n"


def _chapter_fingerprint(proj: str, num: int) -> str:
    import hashlib
    h = hashlib.sha1()
    for p in (project.get_outline_path(proj, num),
              project.get_tracking_path(proj, "角色状态"),
              project.get_tracking_path(proj, "时间线"),
              project.get_tracking_path(proj, "伏笔")):
        try:
            h.update(str(os.path.getmtime(p)).encode())
        except OSError:
            pass
    return h.hexdigest()[:12]



@functools.lru_cache(maxsize=8)
def _header_cached(proj: str, fp: str) -> str:
    from .. import wb
    from ..presets import genre_block_for
    from . import state as st

    try:
        pid = st.load_state(proj).get("genre_preset", "")
        genre = genre_block_for(pid, "prose") if pid else ""
    except Exception:  # noqa: BLE001
        genre = ""
    core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]
    must_full = project.read_file(os.path.join(proj, project.REGEX_PATH)).strip()
    try:
        constant = wb.constant_entries(proj, budget=3000)
    except Exception:  # noqa: BLE001
        constant = ""
    constraints = constraints_block(proj, budget=1500)

    blocks = ["【项目设定基准（全书共享 · 以下内容逐字节稳定，任何一条都不得违反）】"]
    if genre.strip():
        blocks.append("## 题材预设\n" + genre.strip())
    if core.strip():
        blocks.append("## 核心设定节选\n" + core.strip())
    if constraints.strip():
        blocks.append(constraints.strip())
    if must_full:
        blocks.append("## 正则契约（must 全文 · 违反即硬伤）\n" + must_full)
    if constant.strip():
        blocks.append("## 世界书·常驻条目\n" + constant.strip())
    from ..prompts.co_writing import STYLE_DISCIPLINE
    blocks.append("## 全局写作纪律（所有调用共享）\n" + STYLE_DISCIPLINE.strip())
    return "\n\n".join(blocks) + "\n"
