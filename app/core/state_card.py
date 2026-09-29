# -*- coding: utf-8 -*-
"""续写状态卡（卡9-P2，移植 _scratch/superiter/proto/p2_state_card.py）

下一章 prompt 不靠对话记忆，只注入一张 ≤12288 字节的七栏状态卡：
当前位置 / 下一章承诺 / 活跃伏笔(作者真相) / 核心角色状态 / 长期约束(正则must) /
近三章速记(读者已知) / 连贯性风险。

输入全是现有追踪文件与 project 现成接口，纯本地零 LLM。超限裁剪两级：
先结构性上限（角色 6 / 伏笔 8 / 近章 3），仍超预算再按优先级逐项丢弃——
P0（当前位置/下一章承诺）永不丢，整项取舍不截半句，逐项留审计日志
（logging.getLogger("qianbi.state_card") + build_state_card_detail 返回值）。

三条原型修正随移植（w2_proto 坑①②③）：
① 「计划回收」区间取 [min,max]（第5-10章落在窗口内不算逾期）；
② 角色只认结构化 sidecar 登记名（子字段噪声在 tracking_store 层已被排除），
   按近 3 章出场频次排序；
③ 容忍「（暂无）」类脏数据占位（空串/占位一律按缺失处理）。
"""
import logging
import os
import re

from .. import project
from . import memory as _memory
from . import tracking_store

log = logging.getLogger("qianbi.state_card")

BYTE_BUDGET = 12 * 1024          # oh-story 硬上限
CAP_ROLES, CAP_FORESHADOW, CAP_RECENT = 6, 8, 3
_RISK_CAP = 10
_OUTLINE_FIELDS = ("核心事件", "主线推进")       # 字段名跨项目容忍
_HOOK_FIELDS = ("章末钩子", "章尾钩子", "结尾设定")
_PLACEHOLDER_RE = re.compile(r"^（?暂无）?$|^（?无）?$")
_NEAR_RE = re.compile(r"^剩(\d+)章$")


def _rd(proj: str, *parts: str) -> str:
    try:
        return project.read_file(os.path.join(proj, *parts))
    except Exception:  # noqa: BLE001
        return ""


def _clean(s: str) -> str:
    """剥标题标记与「（暂无）」占位，压平空白（坑③）"""
    t = re.sub(r"[#*>]", "", s or "")
    t = re.sub(r"\s+", " ", t).strip()
    return "" if _PLACEHOLDER_RE.match(t) else t


def _chapters_upto(proj: str, num: int, cap: int = CAP_RECENT) -> list:
    """小于 num 的最近 cap 章 [(n, text)]（升序）"""
    out = []
    try:
        for n, _name, path in project.list_chapters(proj):
            if n < num:
                out.append((n, project.read_file(path) or ""))
    except Exception:  # noqa: BLE001
        return []
    return out[-cap:]


def _outline_doc(proj: str, num: int) -> str:
    return _rd(proj, "大纲", "细纲_第%03d章.md" % num) or \
        _rd(proj, "大纲", "细纲_第%d章.md" % num)


# ---------------- 七栏数据域（全部 fail-open） ----------------

def _sec_position(proj: str, num: int) -> list:
    n_last = 0
    try:
        n_last = max((c[0] for c in project.list_chapters(proj)), default=0)
    except Exception:  # noqa: BLE001
        pass
    if n_last and num <= n_last:
        pos = "已定稿至第%d章；当前焦点第%d章（重写/补写）。" % (n_last, num)
    else:
        pos = "已定稿至第%d章；下一章第%d章。" % (n_last, num)
    brief = _clean(_rd(proj, "追踪", "上下文.md"))[:100]
    if brief:
        pos += "进度速记：%s" % brief
    return [pos]


def _sec_promise(proj: str, num: int) -> list:
    """细纲 核心事件/主线推进 + 章末钩子 + 字数目标；缺失回退大纲.md 第N章条目"""
    doc = _outline_doc(proj, num)
    promise, hook, target = "", "", ""
    if doc.strip():
        for key in _OUTLINE_FIELDS:
            m = re.search(rf"^\s*-\s*{key}[：:]\s*(.+)$", doc, re.M)
            if m and _clean(m.group(1)):
                promise = _clean(m.group(1))
                break
        for key in _HOOK_FIELDS:
            m = re.search(rf"^\s*-\s*{key}[：:]\s*(.+)$", doc, re.M)
            if m and _clean(m.group(1)):
                hook = _clean(m.group(1))
                break
        m = re.search(r"字数目标\s*[：:]\s*(\d+)", doc)
        if m:
            target = m.group(1)
    if not promise:
        for ln in _rd(proj, "大纲", "大纲.md").splitlines():
            s = ln.strip()
            if re.search(r"第%d章" % num, s) and s.startswith(("-", "*")):
                promise = _clean(re.sub(r"^[-*]\s*", "", s))
                break
    if not promise:
        return []
    item = promise[:300]
    if hook:
        item += "｜本章需承接钩子：%s" % hook[:80]
    if target:
        item += "｜字数目标%s" % target
    return [item]


def _sec_foreshadow(ranked: list, stress: bool = False) -> list:
    out = []
    for r, _tag in (ranked if stress else ranked[:CAP_FORESHADOW]):
        text = _clean(str(r.get("伏笔") or ""))[:48]
        if not text:
            continue
        item = "「%s」" % text
        planted = _clean(str(r.get("埋设章节") or ""))
        plan = _clean(str(r.get("计划回收") or ""))
        status = _clean(str(r.get("状态") or ""))
        if planted:
            item += "埋于%s" % planted
        if plan:
            item += "，计划%s" % plan
        if status:
            item += "，状态:%s" % status
        out.append(item)
    return out


def _sec_roles(proj: str, num: int, stress: bool = False) -> tuple:
    """(items, zero_mention_names)——角色按近 3 章出场频次排序（坑②：只认 sidecar 登记名）

    stress=True 解除结构性上限（模拟 200 章长篇追踪涨满，卡片的真实对手）。
    """
    try:
        data = tracking_store.load_characters(proj)
    except Exception:  # noqa: BLE001
        return [], []
    chars = data.get("characters") or {}
    order = data.get("order") or list(chars)
    recent = _chapters_upto(proj, num)
    recent_text = "".join(t for _n, t in recent)
    scored = []
    for name in order:
        c = chars.get(name)
        if not isinstance(c, dict) or not _clean(str(name)):
            continue
        mentions = recent_text.count(str(name)) if recent_text else 0
        desc = "；".join(_clean(str(c.get(k) or "")) for k in
                         ("当前身份", "当前能力", "关键关系", "公众形象"))
        if not stress:
            desc = desc[:90]
        scored.append((str(name), mentions, desc))
    scored.sort(key=lambda t: -t[1])
    items = ["%s（近3章出场%d次）：%s" % (n, m, d or "（登记待补）")
             for n, m, d in (scored if stress else scored[:CAP_ROLES])]
    zero = [n for n, m, _d in scored if m == 0][:3]
    return items, zero


def _sec_must(proj: str) -> list:
    try:
        block = project.regex_block(proj, "logic", 1500, levels=("must",))
    except Exception:  # noqa: BLE001
        return []
    if not block or block.startswith("（本书"):
        return []
    return [ln.strip() for ln in block.splitlines() if ln.strip()]


def _sec_recent(proj: str, num: int, stress: bool = False) -> list:
    try:
        if stress:
            # 压力模式：全部摘要入卡（200 章书的追踪涨满形态）
            lines = []
            for line in _rd(proj, "追踪", "章节摘要.md").splitlines():
                if re.match(r"^\s*-\s*第\d+章", line):
                    lines.append(line.strip())
            return lines
        text = _memory.read_recent_summaries(proj, num, n=CAP_RECENT)
    except Exception:  # noqa: BLE001
        return []
    return [ln for ln in text.splitlines() if ln.strip()] if text else []


def _sec_risks(ranked: list, zero_roles: list, num: int, has_outline: bool) -> list:
    """连贯性风险（确定性计算）：伏笔逾期/临近、注册角色近3章零出场、细纲缺失"""
    risks = []
    n_last = num - 1
    for r, tag in ranked:
        name = _clean(str(r.get("伏笔") or ""))[:24]
        if not name:
            continue
        plan = _clean(str(r.get("计划回收") or "")) or "窗口未登记"
        if tag.startswith("超期"):
            risks.append("伏笔「%s」计划%s，已%s（当前第%d章）" % (name, plan, tag, n_last))
        else:
            m_near = _NEAR_RE.match(tag)
            if m_near and int(m_near.group(1)) <= 2:
                risks.append("伏笔「%s」计划%s，%s回收在即（当前第%d章）"
                             % (name, plan, tag, n_last))
        if len(risks) >= 6:
            break
    for name in zero_roles:
        risks.append("注册角色「%s」近%d章零出场，再登场需交代行踪" % (name, CAP_RECENT))
    if not has_outline:
        risks.append("第%d章细纲未生成（承诺栏为大纲回退，开写前宜先补细纲）" % num)
    return risks[:_RISK_CAP]


# ---------------- 组装与预算裁剪 ----------------

def _build_sections(proj: str, num: int, stress: bool = False) -> list:
    """→ [(标题, 优先级, items)]；数字大者先丢，P0 永不丢"""
    ranked = []
    try:
        rows = (tracking_store.load_foreshadow(proj) or {}).get("rows") or []
        ranked = tracking_store.foreshadow_urgency({"rows": rows}, num - 1)
    except Exception:  # noqa: BLE001
        ranked = []
    roles, zero_roles = _sec_roles(proj, num, stress)
    outline = _outline_doc(proj, num)
    return [
        ("当前位置", 0, _sec_position(proj, num)),
        ("下一章承诺", 0, _sec_promise(proj, num)),
        ("活跃伏笔(作者真相)", 1, _sec_foreshadow(ranked, stress)),
        ("连贯性风险", 3, _sec_risks(ranked, zero_roles, num, bool(outline.strip()))),
        ("核心角色状态", 2, roles),
        ("长期约束(正则must)", 4, _sec_must(proj)),
        ("近三章速记(读者已知)", 5, _sec_recent(proj, num, stress)),
    ]


def _render(sections: list, num: int) -> str:
    out = ["# 续写状态卡（第%d章）" % num]
    for title, _prio, items in sections:
        if not items:
            continue
        out.append("")
        out.append("## %s" % title)
        out.extend("- %s" % it for it in items)
    return "\n".join(out) + "\n"


def _trim_to_budget(sections: list, budget: int, num: int) -> tuple:
    """两级裁剪的后半级：按优先级逐项丢（从各栏尾部=最旧/最低价值起），整项取舍不截半句"""
    card = _render(sections, num)
    audit = []
    if len(card.encode("utf-8")) <= budget:
        return card, audit
    for prio in (5, 4, 3, 2, 1):
        for si in range(len(sections) - 1, -1, -1):
            title, p, items = sections[si]
            if p != prio:
                continue
            while items and len(card.encode("utf-8")) > budget:
                dropped = items.pop()
                audit.append("裁剪 [%s] 整项丢弃: %s…" % (title, dropped[:40]))
                log.info("第%d章状态卡%s", num, audit[-1])
                card = _render(sections, num)
                if len(card.encode("utf-8")) <= budget:
                    return card, audit
    return card, audit


def build_state_card_detail(proj: str, num: int, *, budget: int = BYTE_BUDGET,
                            stress: bool = False) -> tuple:
    """(card, audit)——audit 为逐项裁剪记录（常规书为空，压力样本才非空）

    stress=True 解除结构性上限（角色 6/伏笔 8/近章 3），移植原型的压力形态：
    200 章长篇追踪涨满后由 12KB 硬上限与优先级裁剪器兜底。
    """
    n = int(num or 0)
    sections = _build_sections(proj, n, stress)
    return _trim_to_budget(sections, int(budget), n)


def build_state_card(proj: str, num: int, *, budget: int = BYTE_BUDGET,
                     stress: bool = False) -> str:
    """七栏续写状态卡（≤budget 字节，超限按 P5→P1 优先级整项裁剪+审计日志）"""
    card, _audit = build_state_card_detail(proj, num, budget=budget, stress=stress)
    return card
