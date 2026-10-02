# -*- coding: utf-8 -*-
"""钩子承接检测 + 开篇本地评分（0.24.0 W4：Q4-c 成品对偶检测 / Q4-e 择优器）。

三测实证：上一章钩子被本章应答率 1/6（6 对里 2 false 3 partial）、开篇抓力
盲评 3.7-4.2（10 维最弱）。本模块给两条零 LLM 回路：对偶检测（章首 vs 上章
钩子的 2-gram 重合）与开篇 best-of-N 评分（冲突前置/禁忌开场/句式节奏/复述
惩罚）。纯本地，fail-open。
"""
import os
import re

from .. import project
from .history_compaction import _read_hook_rows

_SIDE = "追踪/钩子应答.json"


def _bigrams(text: str) -> set:
    t = re.sub(r"[\s\W]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set()


def detect(opening_text: str, prev_hook_text: str) -> str:
    """章首 vs 上章钩子 → true/partial/false/unknown（2-gram 重合率分档）。"""
    if not (opening_text or "").strip() or not (prev_hook_text or "").strip():
        return "unknown"
    h, o = _bigrams(prev_hook_text), _bigrams(opening_text)
    if not h:
        return "unknown"
    ov = len(h & o) / len(h)
    # 分档校准：中文章首改写后与钩子的 2-gram 重合实测 true≈0.19、false≈0.00
    return "true" if ov >= 0.15 else ("partial" if ov >= 0.06 else "false")


def _prev_hook_text(proj: str, prev_num: int) -> str:
    for r in _read_hook_rows(proj):
        if isinstance(r, dict):
            try:
                if int(r.get("num") or 0) == prev_num \
                        and r.get("position", "章尾") == "章尾":
                    s = str(r.get("summary") or r.get("hook") or "").strip()
                    if s:
                        return s
            except (TypeError, ValueError):
                continue
    prev = project.nearest_chapter_before(proj, prev_num + 1) or None
    for n, _t, p in project.list_chapters(proj):
        if n == prev_num:
            return (project.read_file(p) or "")[-300:]
    return ""


def check_chapter_pair(proj: str, num: int) -> str:
    """第 num 章开头 500 字 vs 第 num-1 章钩子 → 应答判定。"""
    if num <= 1:
        return "unknown"
    opening = ""
    for n, _t, p in project.list_chapters(proj):
        if n == num:
            opening = (project.read_file(p) or "")[:500]
            break
    return detect(opening, _prev_hook_text(proj, num - 1))


def record_answer(proj: str, num: int, verdict: str) -> bool:
    """应答判定落 sidecar（幂等：同章覆盖）。"""
    path = os.path.join(proj, _SIDE)
    data = {}
    if os.path.exists(path):
        try:
            import json
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    rows = data.setdefault("rows", {})
    rows[str(int(num))] = str(verdict)
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return True


def answered_verdicts(proj: str) -> dict:
    import json
    path = os.path.join(proj, _SIDE)
    try:
        return json.load(open(path, encoding="utf-8")).get("rows", {})
    except (OSError, ValueError):
        return {}
