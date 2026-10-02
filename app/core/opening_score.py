# -*- coding: utf-8 -*-
"""开篇本地评分器（0.24.0 Q4-e）：best-of-N 章首择优的零成本打分。

维度（方法论「冲突前置/禁忌开场/句式节奏/禁复述上章」的机器化）：
冲突悬念词前置 + / 禁忌天气开场 − / 句长变异系数 / 章首复述上章 − / 有对话 +。
量纲 0-10，纯本地。
"""
import re

FORBIDDEN_OPENERS = ["天气", "阳光", "细雨", "夜幕", "清晨", "夕阳", "天空飘", "雨点敲"]
HOOK_WORDS = ["突然", "却发现", "竟是", "危机", "倒计时", "血", "死", "秘密", "真相",
              "失踪", "陷阱", "追", "杀", "警报", "颤抖", "不许动", "滚出去", "谁"]


def _sents(text: str) -> list:
    """子句切分（含逗号——中文子句边界；单句长句的 cv 惩罚需要逗号级切分）。"""
    parts = [p.strip() for p in re.split(r"[。！？!?，,；;]", text or "") if p.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def _bigrams(text: str) -> set:
    t = re.sub(r"[\s\W]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set()


def score(text: str, prev_tail: str = "") -> float:
    """开篇质量本地分（0-10，两位小数）。prev_tail 空则复述惩罚跳过。"""
    t = text or ""
    if not t.strip():
        return 0.0
    head = t[:100]
    s = 0.0
    hits = sum(1 for w in HOOK_WORDS if w in head)
    s += min(4.5, hits * 1.5)                      # (a) 冲突前置
    first_para = t.split("\n")[0] if "\n" in t else t[:120]
    s -= 1.5 * sum(1 for w in FORBIDDEN_OPENERS if w in first_para)   # (b) 禁忌开场
    lens = [len(x) for x in _sents(t[:400])]
    if lens:
        mean = sum(lens) / len(lens)
        cv = (sum((x - mean) ** 2 for x in lens) / len(lens)) ** 0.5 / max(mean, 1)
        s += 1.5 if cv > 0.3 else (-1.5 if cv < 0.15 else 0.0)        # (c) 节奏
    if prev_tail and _bigrams(prev_tail):
        ov = len(_bigrams(t[:200]) & _bigrams(prev_tail)) / len(_bigrams(prev_tail))
        if ov >= 0.35:
            s -= 2.0                                                 # (d) 复述
    if any(q in t[:200] for q in ("「", "」", "“", "”")):
        s += 0.5                                                     # (e) 对话
    return round(max(0.0, min(10.0, s)), 2)


def best_of(candidates: list, prev_tail: str = "") -> int:
    """得分最高候选下标；平分取先者；空列表 -1。"""
    if not candidates:
        return -1
    scores = [score(c, prev_tail) for c in candidates]
    return scores.index(max(scores))
