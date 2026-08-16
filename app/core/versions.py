# -*- coding: utf-8 -*-
"""保存驱动版本体系（M1 · 关键语义）

版本只跟随显式「保存」动作：
- 编辑器中的一切修改（手动编辑 / 局部改写应用 / 重写结果）= 工作副本，不算版本
- 只有点「保存」才提交为新版本：旧内容归档为 vN，新内容写正文
- 取消 / 切换章节 / 关闭 / 意外退出：绝不产生新版本
- 流水线定稿落库 = 唯一例外：AI 完成整章落盘时归档 source=定稿（每章首个版本）

草稿暂存（防丢稿，不产生版本）：
- 编辑器修改后 5s 防抖写 正文/.drafts/第X章.draft.md
- 启动时检测到比正文新的草稿 → 提示「恢复草稿 / 丢弃」，恢复仍是工作副本
"""
import datetime
import difflib
import json
import os
import re
import tempfile

MAX_VERSIONS = 30  # 每章版本上限，超出滚动清理最旧版

SOURCE_FINALIZE = "定稿"
SOURCE_MANUAL = "手动保存"
SOURCE_REWRITE = "局部改写"
SOURCE_REREWRITE = "整章重写"


# ---------- 路径 ----------

def chapter_versions_dir(proj: str, num: int) -> str:
    return os.path.join(proj, "正文", ".versions", f"第{num}章")


def index_path(proj: str, num: int) -> str:
    return os.path.join(chapter_versions_dir(proj, num), "index.json")


def draft_dir(proj: str) -> str:
    return os.path.join(proj, "正文", ".drafts")


def draft_path(proj: str, num: int) -> str:
    return os.path.join(draft_dir(proj), f"第{num}章.draft.md")


# ---------- 版本 ----------

def _read_index(proj: str, num: int) -> list:
    p = index_path(proj, num)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _write_index(proj: str, num: int, entries: list):
    p = index_path(proj, num)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(p))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_versions(proj: str, num: int) -> list:
    """返回 [{v, ts, source, words}]，按 v 升序"""
    return sorted(_read_index(proj, num), key=lambda e: e.get("v", 0))


def version_file(proj: str, num: int, v: int) -> str:
    return os.path.join(chapter_versions_dir(proj, num), f"v{v:03d}.md")


def read_version(proj: str, num: int, v: int) -> str:
    p = version_file(proj, num, v)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def snapshot(proj: str, num: int, old_content: str, source: str) -> int:
    """归档旧内容为新版本（保存驱动：保存前把磁盘旧内容存为 vN）。

    返回新版本号；old_content 为空或与最新版本相同则跳过（返回 0）。
    """
    old_content = old_content or ""
    if not old_content.strip():
        return 0
    entries = _read_index(proj, num)
    if entries and entries[-1].get("words") == len(old_content):
        latest = read_version(proj, num, entries[-1]["v"])
        if latest == old_content:
            return 0  # 内容无变化，不产生版本
    v = (entries[-1]["v"] + 1) if entries else 1
    path = version_file(proj, num, v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(old_content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    entries.append({
        "v": v,
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "words": len(old_content),
    })
    # 滚动清理超上限的最旧版本
    if len(entries) > MAX_VERSIONS:
        drop = entries[: len(entries) - MAX_VERSIONS]
        entries = entries[len(entries) - MAX_VERSIONS:]
        for e in drop:
            p = version_file(proj, num, e["v"])
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    _write_index(proj, num, entries)
    return v


def diff_texts(a: str, b: str) -> list:
    """行级 diff：返回 [{op: same|del|add, text}]（a→b 的变化）"""
    sm = difflib.SequenceMatcher(None, a.splitlines(True), b.splitlines(True))
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in a.splitlines(True)[i1:i2]:
                out.append({"op": "same", "text": line})
        elif tag == "delete":
            for line in a.splitlines(True)[i1:i2]:
                out.append({"op": "del", "text": line})
        elif tag == "insert":
            for line in b.splitlines(True)[j1:j2]:
                out.append({"op": "add", "text": line})
        else:  # replace
            for line in a.splitlines(True)[i1:i2]:
                out.append({"op": "del", "text": line})
            for line in b.splitlines(True)[j1:j2]:
                out.append({"op": "add", "text": line})
    return out


def diff_versions(proj: str, num: int, v1: int, v2: int) -> list:
    """两版本对比（v1 → v2 的变化）"""
    return diff_texts(read_version(proj, num, v1), read_version(proj, num, v2))


# ---------- 草稿暂存（不产生版本，防丢稿）----------

def save_draft(proj: str, num: int, content: str):
    """写入草稿暂存区（仅编辑器有未保存修改时调用）"""
    if not content:
        return
    p = draft_path(proj, num)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(p))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_draft(proj: str, num: int):
    """读取草稿；返回 (content, mtime) 或 None"""
    p = draft_path(proj, num)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        return content, os.path.getmtime(p)
    except Exception:
        return None


def discard_draft(proj: str, num: int):
    p = draft_path(proj, num)
    if os.path.exists(p):
        try:
            os.unlink(p)
        except OSError:
            pass


def discard_all_drafts(proj: str):
    d = draft_dir(proj)
    if os.path.isdir(d):
        for name in os.listdir(d):
            try:
                os.unlink(os.path.join(d, name))
            except OSError:
                pass


def list_drafts(proj: str) -> list:
    """列出有草稿的章节 [(num, mtime)]，按 mtime 升序"""
    result = []
    d = draft_dir(proj)
    if os.path.isdir(d):
        for name in os.listdir(d):
            m = re.match(r"第(\d+)章\.draft\.md$", name)
            if m:
                p = os.path.join(d, name)
                result.append((int(m.group(1)), os.path.getmtime(p)))
    return sorted(result, key=lambda x: x[1])


def newest_draft(proj: str):
    """返回最新草稿 (num, content, mtime) 或 None"""
    drafts = list_drafts(proj)
    if not drafts:
        return None
    num, mtime = drafts[-1]
    loaded = load_draft(proj, num)
    if loaded is None:
        return None
    return num, loaded[0], mtime
