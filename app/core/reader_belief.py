# -*- coding: utf-8 -*-
"""读者认知三段式册（B3/WA3-b，移植 goink reader_perspective 三段式，0.20.3）

站在读者心智视角的账本（区别于事实账本的「世界里发生了什么」）：
- known          读者已知事实（kind=setting 设定型常驻 / event 事件型近章截断，
                 last_mention_ch 记最近提及章——修 goink「第 1 章立的设定先被截掉」弱点）
- suspense       活跃悬念（读者知道有缺口）：content+truth（作者心里应有数）+
                 due_ch（计划揭示窗口，与卡2 recovery_window 同口径）
- misconceptions 读者误知（读者填了错答案）：{name, belief, truth,
                 payoff_planned_ch, created_ch, resolved_ch}——反转=resolve 的那一刻
                 必须有对应 active 误知存在才成立；payoff 到期未兑现=fail 候选

合并 schema（t6 §6.2）文件化收敛：不建表，落 sidecar `追踪/读者认知.json`
（qianbi 惯例）；LLM 不得直接写此文件——写路径走「待确认卡→人工确认→登记」。

纯本地零 LLM；IO 全 fail-open（缺失/损坏按空册处理，读路径零副作用）。
状态卡第 6 栏升级：three_part_items() 三段压缩版（已知常驻 ≤5 / 悬念 ≤5 /
误知 ≤3，段预算 ≤1.2KB≈12KB 预算 10%），sidecar 缺失时恒空——第 6 栏输出
与 0.22 逐字一致；近三章速记语义保留（事件型 known 即近三章摘要）。
"""
from __future__ import annotations

import json
import os
import re

SIDECAR_VERSION = 1
KIND_SETTING, KIND_EVENT = "setting", "event"

CAP_SETTING_KNOWN = 5         # 设定型 known 常驻上限（条）
CAP_SUSPENSE = 5              # 活跃悬念上限（条，goink 截 60 改分层截断）
CAP_MISCONCEPTION = 3         # 读者误知上限（条）
_NOTE_W = {"known": 20, "suspense": 30, "mis": 40}     # 各段单条正文字数上限
SEGMENT_BUDGET = 1200         # 三段合计字节上限（≈12KB 状态卡预算的 10%）

_NUM_RE = re.compile(r"\d+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip("《》「」『』“”\"'")


def _sidecar_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "读者认知.json")


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
    """读者认知册全量（缺失/损坏 → 空册，读路径零副作用）"""
    data = _read_json(_sidecar_path(proj))
    if data and isinstance(data, dict):
        out = {"version": SIDECAR_VERSION,
               "known": data.get("known") if isinstance(data.get("known"), list) else [],
               "suspense": data.get("suspense") if isinstance(data.get("suspense"), list) else [],
               "misconceptions": data.get("misconceptions")
               if isinstance(data.get("misconceptions"), list) else []}
        return out
    return {"version": SIDECAR_VERSION, "known": [], "suspense": [], "misconceptions": []}


def _save(proj: str, data: dict) -> None:
    data["version"] = SIDECAR_VERSION
    _write_json(_sidecar_path(proj), data)


# ---------------- known（读者已知事实） ----------------

def record_mention(proj: str, num: int, content: str, kind: str = KIND_EVENT) -> dict:
    """登记/提及刷新：同文重复登记只推进 last_mention_ch（取最大章）。

    kind（setting|event）首登记生效，后续提及不降级改类；返回该 known 条目。
    """
    content = str(content or "").strip()
    data = load(proj)
    known = data.setdefault("known", [])
    key = _norm(content)
    for e in known:
        if isinstance(e, dict) and _norm(e.get("content")) == key:
            old = e.get("last_mention_ch")
            e["last_mention_ch"] = max(int(old), int(num)) if isinstance(old, int) else int(num)
            _save(proj, data)
            return e
    entry = {"content": content, "kind": kind if kind in (KIND_SETTING, KIND_EVENT) else KIND_EVENT,
             "created_ch": int(num), "last_mention_ch": int(num)}
    known.append(entry)
    _save(proj, data)
    return entry


# ---------------- suspense（活跃悬念） ----------------

def register_suspense(proj: str, num: int, content: str, truth: str = "",
                      due_ch: int | None = None) -> dict | None:
    """种下悬念（content 必填；truth=作者心里应有数的答案；due_ch=计划揭示章）。

    同文活跃悬念重复登记 → 原位更新（补 truth/due），已回收的同文可再种。
    """
    content = str(content or "").strip()
    if not content:
        return None
    data = load(proj)
    susp = data.setdefault("suspense", [])
    key = _norm(content)
    for e in susp:
        if isinstance(e, dict) and e.get("resolved_ch") is None and _norm(e.get("content")) == key:
            if str(truth or "").strip():
                e["truth"] = str(truth).strip()
            if due_ch:
                e["due_ch"] = int(due_ch)
            e["last_mention_ch"] = int(num)
            _save(proj, data)
            return e
    entry = {"content": content, "truth": str(truth or "").strip(), "planted_ch": int(num),
             "due_ch": int(due_ch) if due_ch else None,
             "resolved_ch": None, "last_mention_ch": int(num)}
    susp.append(entry)
    _save(proj, data)
    return entry


def resolve_suspense(proj: str, content: str, num: int) -> bool:
    """悬念回收（revealed）：首个活跃同文条目 resolved_ch=num；无活跃命中 False"""
    data = load(proj)
    key = _norm(content)
    for e in data.get("suspense") or []:
        if isinstance(e, dict) and e.get("resolved_ch") is None and _norm(e.get("content")) == key:
            e["resolved_ch"] = int(num)
            _save(proj, data)
            return True
    return False


# ---------------- misconceptions（读者误知） ----------------

def register_misconception(proj: str, num: int, name: str, belief: str, truth: str,
                           payoff_planned_ch: int | None = None) -> tuple:
    """种下读者误知（goink 预校验同款：belief 与 truth 必填，缺即拒绝不落盘）。

    同名活跃误知重复登记 → 原位更新（belief/truth/payoff），created_ch 不变；
    已回收同名可再种（新一轮误知）。Returns: (entry|None, err)——err 非空=拒绝原因。
    """
    name = str(name or "").strip()
    belief = str(belief or "").strip()
    truth = str(truth or "").strip()
    if not name or not belief or not truth:
        return (None, "误知登记须 name/belief/truth 三字段齐备（反转=误知+真相对账面）")
    data = load(proj)
    mis = data.setdefault("misconceptions", [])
    key = _norm(name)
    for e in mis:
        if isinstance(e, dict) and e.get("resolved_ch") is None and _norm(e.get("name")) == key:
            e["belief"] = belief
            e["truth"] = truth
            e["payoff_planned_ch"] = int(payoff_planned_ch) if payoff_planned_ch else None
            _save(proj, data)
            return (e, "")
    entry = {"name": name, "belief": belief, "truth": truth,
             "payoff_planned_ch": int(payoff_planned_ch) if payoff_planned_ch else None,
             "created_ch": int(num), "resolved_ch": None}
    mis.append(entry)
    _save(proj, data)
    return (entry, "")


def resolve_misconception(proj: str, name: str, num: int) -> bool:
    """误知揭穿（反转兑现）：首个活跃同名条目 resolved_ch=num；无活跃命中 False"""
    data = load(proj)
    key = _norm(name)
    for e in data.get("misconceptions") or []:
        if isinstance(e, dict) and e.get("resolved_ch") is None and _norm(e.get("name")) == key:
            e["resolved_ch"] = int(num)
            _save(proj, data)
            return True
    return False


def due_query(proj: str, cur_num: int) -> list:
    """到期未兑现 → fail 候选清单（确定性对账，供 L0/维护四查消费）。

    活跃误知 payoff_planned_ch < cur_num（计划章已过仍未揭穿）+ 活跃悬念
    due_ch < cur_num；按超期章数降序。每条 {kind, name, claim, truth, due_ch,
    overdue_by}。
    """
    out = []
    data = load(proj)
    for e in data.get("misconceptions") or []:
        if not isinstance(e, dict) or e.get("resolved_ch") is not None:
            continue
        due = e.get("payoff_planned_ch")
        if isinstance(due, int) and cur_num > due:
            out.append({"kind": "misconception", "name": str(e.get("name") or ""),
                        "claim": str(e.get("belief") or ""), "truth": str(e.get("truth") or ""),
                        "due_ch": due, "overdue_by": cur_num - due})
    for e in data.get("suspense") or []:
        if not isinstance(e, dict) or e.get("resolved_ch") is not None:
            continue
        due = e.get("due_ch")
        if isinstance(due, int) and cur_num > due:
            out.append({"kind": "suspense", "name": str(e.get("content") or ""),
                        "claim": str(e.get("content") or ""), "truth": str(e.get("truth") or ""),
                        "due_ch": due, "overdue_by": cur_num - due})
    out.sort(key=lambda x: -x["overdue_by"])
    return out


# ---------------- 状态卡第 6 栏三段压缩版 ----------------

def three_part_items(proj: str, cur_num: int, *, budget: int | None = None) -> list:
    """「近三章速记(读者已知)」栏三段压缩版条目（display 序=已知→悬念→误知）。

    - 〔已知〕设定型 known 常驻 ≤5（事件型 known 不在此列——近三章摘要即其语义）
    - 〔悬念〕活跃悬念 ≤5（临期在前）
    - 〔误知〕活跃误知 ≤3（belief→实为 truth）
    段预算 ≤SEGMENT_BUDGET 字节，超限按 设定型known→误知→悬念 逐条丢
    （悬念保到最後——与伏笔栏同级的 P1.5 语义）。sidecar 缺失/空 → []，
    第 6 栏输出与 0.22 逐字一致。
    """
    budget = SEGMENT_BUDGET if budget is None else budget
    data = load(proj)
    w = _NOTE_W

    known = []
    settings = [e for e in (data.get("known") or [])
                if isinstance(e, dict) and e.get("kind") == KIND_SETTING]
    settings.sort(key=lambda e: -(e.get("last_mention_ch") if isinstance(
        e.get("last_mention_ch"), int) else 0))
    for e in settings[:CAP_SETTING_KNOWN]:
        content = str(e.get("content") or "").strip()[:w["known"]]
        if not content:
            continue
        ch = e.get("created_ch") if isinstance(e.get("created_ch"), int) else None
        known.append("〔已知〕%s（第%d章起）" % (content, ch) if ch else "〔已知〕%s" % content)

    susp_active = [e for e in (data.get("suspense") or [])
                   if isinstance(e, dict) and e.get("resolved_ch") is None]
    susp_active.sort(key=lambda e: (not isinstance(e.get("due_ch"), int),
                                    e.get("due_ch") if isinstance(e.get("due_ch"), int) else 0))
    susp = []
    for e in susp_active[:CAP_SUSPENSE]:
        content = str(e.get("content") or "").strip()[:w["suspense"]]
        if not content:
            continue
        due = e.get("due_ch") if isinstance(e.get("due_ch"), int) else None
        tail = "计划第%d章前揭示" % due if due else "揭示窗口未定"
        susp.append("〔悬念〕%s（%s）" % (content, tail))

    mis_active = [e for e in (data.get("misconceptions") or [])
                  if isinstance(e, dict) and e.get("resolved_ch") is None]
    mis_active.sort(key=lambda e: (not isinstance(e.get("payoff_planned_ch"), int),
                                   e.get("payoff_planned_ch") if isinstance(
                                       e.get("payoff_planned_ch"), int) else 0))
    mis = []
    for e in mis_active[:CAP_MISCONCEPTION]:
        belief = str(e.get("belief") or "").strip()[:w["mis"]]
        truth = str(e.get("truth") or "").strip()[:20]
        if not belief:
            continue
        payoff = e.get("payoff_planned_ch") if isinstance(e.get("payoff_planned_ch"), int) else None
        tail = "计划第%d章揭穿" % payoff if payoff else "揭穿窗口未定"
        mis.append("〔误知〕%s→实为：%s（%s）" % (belief, truth, tail))

    groups = [known, mis, susp]        # 超限丢弃序：设定型 known → 误知 → 悬念
    def _total():
        return sum(len(x.encode("utf-8")) for g in groups for x in g)
    while _total() > budget and any(groups):
        for g in groups:
            if g:
                g.pop()
                break
    return known + susp + mis
