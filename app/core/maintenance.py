# -*- coding: utf-8 -*-
"""P3 写后维护四查（卡9：goink internal/mcp_tools/rw_tools.go:425-443 章末维护
强制注入的流水线化翻译，原型 _scratch/superiter/proto/p3_post_write_check.py 移植）

机制一句话：新章定稿不是终点，而是触发 角色/伏笔/弧线/读者认知 四域维护检查
的事件；检查全确定性零 LLM，产物既给人看，也作为 system-reminder 式 checklist
供下一轮 prompt 组装注入。

产物纪律（卡9 原文裁决）：
- **不自动写库**——新实体/需决断/逾期全部进「待确认卡片」（cards 字段），
  作者在环确认后才登记（确定性轨召回好精度中，GUI 待确认卡是结构优势）；
- **不占 state['cw']['report'] 单槽**（state.py 校验区已被 supervisor 报告/
  世界书通知/clearCwReport 三共抢）——独立 sidecar `追踪/维护四查_第NNN章.json`
  （与 设定清算_第NNN章.json 同通道惯例），本模块不读写 pipeline_state。
- 域2 伏笔吃卡2 的 tracking_store sidecar（角色/伏笔结构化真源），不重复解析
  markdown；「计划回收」窗口复用 parse_recovery_window（区间取 [min,max]）。

任何异常由调用方 fail-open；run_checks 自身兜 try 返回 {}。
"""
from __future__ import annotations

import datetime
import json
import os
import re

from .. import project
from . import tracking_store

# 新实体候选排除表（原型 _STOP 的修正版：原型把词表写成了一个无空格长串导致
# 集合退化为单元素——移植时拆成真词表）
_STOP = frozenset(
    "可能 已经 走向 人群 门口 小时 分钟 非常 突然 最后 开始 直接 自己 他们 知道 "
    "觉得 看着 起来 出来 去了 说过 时候 现在 什么 没有 这个 那个 因此 但是 然后 "
    "于是 只是 这么 那么".split())

# 候选词内出现即弃的功能字（虚词/语素不可能是实体名）
_STOP_CHARS = "的了在着很都也又被把和与或之中上后里去来"

# 未再提及的「需决断」阈值（原型口径：距上次提及 ≥3 章）
_STALE_CHAPTERS = 3


def _sentences(text: str) -> list:
    body = re.sub(r"^#.*$", "", text or "", flags=re.M)
    body = re.sub(r"\s+", "", body)
    return [s for s in re.split(r"(?<=[。！？…])", body) if s]


def _outline_field(doc: str, key: str) -> str:
    m = re.search(rf"{key}[：:]\s*(.+)", doc or "")
    return m.group(1).strip() if m else ""


def _outline_clauses(outline_doc: str, fallback_doc: str = "", num: int = 0) -> list:
    """本章契约子句：细纲 核心事件/必演/章末钩子 优先；细纲缺失回退大纲中含
    第N章的列表条目（原型 outline_clauses 移植）。返回 ≥6 字的子句列表。"""
    text = ""
    for key in ("核心事件", "必演", "章末钩子"):
        m = _outline_field(outline_doc, key)
        if m:
            text += m + "；"
    if not text and fallback_doc:
        for ln in fallback_doc.splitlines():
            s = ln.strip()
            if s.startswith(("-", "*")) and re.search(rf"第\s*{num}\s*章", s):
                text += re.sub(r"^[-*]\s*|\t", "", s) + "；"
    return [c for c in re.split(r"[；;。]", text) if len(c) >= 6]


def _last_mention(text: str, chapters: list, planted: str = "") -> tuple:
    """条目在正文中的最近提及 → (章号, 证据句, 关键词)。

    登记语言≠正文语言：关键词从 10 字逐级缩到 4 字取最长命中（原型
    last_mention 移植）；全部未命中且登记了埋设章 → 返回 (埋设章, '', key)
    以便报「埋设后未再提及」。chapters: [(num, text)] 升序。
    """
    key = re.sub(r"[（(].*?[)）]", "", text or "")
    key = re.sub(r"[「」“”‘’]", "", key)[:10]
    key = key.split("，")[0].split("：")[0]
    if len(key) < 4:
        key = (text or "")[:6]
    for size in range(len(key), 3, -1):
        k = key[:size]
        for num, t in reversed(chapters):
            for s in _sentences(t):
                if k in s:
                    return num, s, k
    m = re.search(r"第?\s*(\d+)", planted or "")
    return (int(m.group(1)) if m else None), "", key


def _chapter_text(chapters: list, n: int) -> str:
    return next((t for c, t in chapters if c == n), "") or (
        chapters[-1][1] if chapters else "")


# ---------------- 域1 角色 ----------------

def check_characters(chapters: list, n: int, names: list, roster_text: str = "",
                     outline_text: str = "") -> dict:
    """注册角色 × 本章出场（正文证据句）/ 近3章零出场 → 待更新名单；
    细纲提及但角色状态册未登记、本章高频首次出现的名字 → 新实体待确认卡。"""
    ch_n = _chapter_text(chapters, n)
    all_text = "".join(t for _c, t in chapters)
    names = [x for x in (names or []) if x and (x in all_text or x in roster_text)]
    reg, stale = [], []
    tail3 = "".join(t for k, t in chapters if n - _STALE_CHAPTERS < k <= n)
    for name in names:
        ev = next((s for s in _sentences(ch_n) if name in s), "")
        if ev:
            reg.append([name, ev[:60]])
        elif name not in tail3:
            stale.append(name)
    prev_all = "".join(t for k, t in chapters if k < n)
    cands = set()
    for cand in set(re.findall(r"[\u4e00-\u9fff]{2,4}", outline_text or "")):
        if (cand not in names and cand not in _STOP and cand in ch_n
                and ch_n.count(cand) >= 3 and cand not in prev_all
                and not any(ch in _STOP_CHARS for ch in cand)):
            cands.add(cand)
    # 子串去重：'步声' ⊂ '脚步声' 时丢短者；计数同分按字典序——全序保证确定性
    missing_reg = [c for c in cands if not any(c != o and c in o for o in cands)]
    return {"domain": "角色", "本章出场": reg, "近3章零出场": stale,
            "疑似未登记新实体": sorted(missing_reg, key=lambda x: (-ch_n.count(x), x))[:5]}


# ---------------- 域2 伏笔 ----------------

def check_foreshadows(chapters: list, n: int, rows: list) -> dict:
    """伏笔册逐条：最近提及章+证据句；本章提及状态未推进→待登记；距上次提及
    ≥3 章→需决断；计划回收逾期/临近→提醒（窗口解析复用卡2
    tracking_store.parse_recovery_window，区间取 [min,max]）。"""
    out = []
    for f in rows or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("状态") or "").strip() in ("已回收", "回收", "已失效"):
            continue
        name = str(f.get("伏笔") or "").strip()
        if not name:
            continue
        last_num, ev, key = _last_mention(name, chapters, str(f.get("埋设章节") or ""))
        lo, hi = tracking_store.parse_recovery_window(f.get("计划回收"))
        plant_num = next((int(x) for x in re.findall(r"\d+", str(f.get("埋设章节") or ""))), None)
        item = {"伏笔": name[:36], "最近提及章": last_num, "关键词": key}
        if last_num == n:
            item["动作"] = "本章提及→状态待登记(推进/回收)，登记后 evidence 引文见检查报告"
        elif last_num is None and plant_num == n:
            item["动作"] = "本章新埋→登记为「已埋」并填计划回收章"
        elif last_num is not None and n - last_num >= _STALE_CHAPTERS:
            item["动作"] = f"已{n - last_num}章未提及→需决断：本章推进或登记回收"
        elif last_num is None and plant_num is not None and n - plant_num >= _STALE_CHAPTERS:
            item["动作"] = f"第{plant_num}章埋设后正文未再呼应→需决断"
        if lo is not None:
            if n > hi:
                item["计划"] = f"计划回收{str(f.get('计划回收') or '').strip()}已逾期"
            elif n >= hi - 2:
                item["计划"] = f"计划回收{str(f.get('计划回收') or '').strip()}临近"
        if "动作" in item or "计划" in item:
            item["证据句"] = ev[:50]
            out.append(item)
    return {"domain": "伏笔", "条目": out}


# ---------------- 域3 弧线 ----------------

def check_arc(chapters: list, n: int, names: list, clauses: list) -> dict:
    """细纲契约子句对正文做「逐字命中 ∪ 实体共现」落点核验（oh-story 情节点
    落点核验思想）；未落点子句列出，转人工复核（不自动判偏离）。"""
    ch_n = _chapter_text(chapters, n)
    ch_sents = _sentences(ch_n)
    covered, missed = [], []
    for clause in clauses or []:
        if clause in ch_n:
            covered.append([clause[:40], "逐字命中"])
            continue
        ents = [x for x in (names or []) if x in clause]
        hit = False
        if ents:
            for s in ch_sents:
                if all(e in s for e in ents):
                    covered.append([clause[:40], f"实体共现({'、'.join(ents)})"])
                    hit = True
                    break
        if not hit:
            missed.append(clause[:40])
    return {"domain": "弧线", "落点命中": covered, "未落点子句(需人工复核)": missed}


# ---------------- 域4 读者认知 ----------------

def check_reader(chapters: list, n: int, names: list, prev_hook: str = "") -> dict:
    """上一章章末钩子关键字是否在本章开头回应；本章首次出现的新名词（引用号
    词，前文未出现且复现≥2）→ 需登记「读者已知」；读者误知确定性轨不可判，
    留 LLM 轨。"""
    ch_n = _chapter_text(chapters, n)
    head = re.sub(r"\s+", "", ch_n)[:600]
    res = {"domain": "读者认知"}
    if prev_hook:
        ents = [x for x in (names or []) if x in prev_hook] + \
               re.findall(r"“(.{2,10})”", prev_hook)
        if ents:
            ev = [e for e in ents if e in head]
            res["上章钩子回应"] = (
                f"钩子「{prev_hook[:36]}…」要素命中 {len(ev)}/{len(ents)}"
                + (f"：{ev}" if ev else "，开头 600 字未见承接要素→需检查衔接"))
        else:
            res["上章钩子回应"] = f"钩子「{prev_hook[:36]}…」无可确定字关键词，留 LLM 轨复核"
    prev_all = "".join(t for k, t in chapters if k < n)
    fresh = []
    for term in set(re.findall(r"“([^“”]{2,5})”", ch_n)):
        if (term not in prev_all and not re.search(r"[，。！？、\s]", term)
                and ch_n.count(term) >= 2):
            fresh.append(term)
    res["本章新名词(需登记读者已知)"] = sorted(fresh, key=lambda x: -ch_n.count(x))[:8]
    res["读者误知"] = "确定性轨不可判——留 LLM 轨：列出本章与读者既有认知可能冲突的断言"
    return res


# ---------------- 待确认卡片（不自动写库的唯一出口） ----------------

def build_cards(report: dict) -> list:
    """四查结果 → 待确认卡片列表。卡片只是「请人拍板」的凭据，本模块不据其
    写任何追踪文件——登记动作永远发生在人工确认之后（后续 GUI 卡流程）。"""
    n = int(report.get("num") or 0)
    d = {x["domain"]: x for x in report.get("domains") or []}
    cards = []
    for term in (d.get("角色", {}).get("疑似未登记新实体") or []):
        cards.append({"id": f"ch{n}:new_entity:{term}", "kind": "新实体待登记",
                      "domain": "角色", "ch": n,
                      "text": f"「{term}」疑似未登记新实体——确认后登记到 追踪/角色状态",
                      "action": "待确认（勾选登记 / 忽略）"})
    for name in (d.get("角色", {}).get("近3章零出场") or []):
        cards.append({"id": f"ch{n}:char_stale:{name}", "kind": "角色零出场",
                      "domain": "角色", "ch": n,
                      "text": f"「{name}」近3章零出场——安排交代或标记退场",
                      "action": "待确认（安排 / 忽略）"})
    for it in (d.get("伏笔", {}).get("条目") or []):
        action = str(it.get("动作") or "")
        plan = str(it.get("计划") or "")
        if "需决断" in action:
            kind = "伏笔需决断"
        elif "待登记" in action or "新埋" in action:
            kind = "伏笔待登记"
        elif plan:
            kind = "伏笔计划提醒"
        else:
            continue
        cards.append({"id": f"ch{n}:foreshadow:{it.get('伏笔', '')}", "kind": kind,
                      "domain": "伏笔", "ch": n,
                      "text": f"伏笔「{it.get('伏笔', '')}」{action or plan}".strip(),
                      "action": "待确认（登记推进 / 登记回收 / 改期 / 忽略）"})
    for clause in (d.get("弧线", {}).get("未落点子句(需人工复核)") or []):
        cards.append({"id": f"ch{n}:arc_miss:{clause}", "kind": "弧线未落点",
                      "domain": "弧线", "ch": n,
                      "text": f"契约子句「{clause}」未落点——人工复核是否改写偏离",
                      "action": "待确认（接受偏离 / 标记补写）"})
    hook = str(d.get("读者认知", {}).get("上章钩子回应") or "")
    if "未见承接要素" in hook:
        cards.append({"id": f"ch{n}:hook_gap", "kind": "读者认知",
                      "domain": "读者认知", "ch": n, "text": hook,
                      "action": "待确认（补衔接 / 忽略）"})
    return cards


def checklist(report: dict) -> str:
    """goink 式注入文本：四查汇总成维护 checklist，供下一轮 LLM 调用作
    system-reminder 附加（确定性拼接，零 LLM）。"""
    n = int(report.get("num") or 0)
    d = {x["domain"]: x for x in report.get("domains") or []}
    r = d.get("角色", {})
    stale = r.get("近3章零出场") or []
    f2 = d.get("伏笔", {})
    items = f2.get("条目") or []
    a = d.get("弧线", {})
    missed = a.get("未落点子句(需人工复核)") or []
    rd4 = d.get("读者认知", {})
    lines = [
        f"[system-reminder] 第{n}章已定稿，执行写后维护（逐项完成后汇报摘要）：",
        "1.角色：本章出场 %d 人已核对；需更新状态 %s；零出场待交代 %s；疑似未登记 %s。"
        % (len(r.get("本章出场") or []),
           sorted({nm for nm, _ev in (r.get("本章出场") or [])}) or "无",
           stale or "无", r.get("疑似未登记新实体") or "无"),
        "2.伏笔：待登记推进/回收 %d 条；长期未动需决断 %d 条；回收逾期/临近 %d 条。"
        % (sum(1 for i in items if "待登记" in str(i.get("动作", "")) or "新埋" in str(i.get("动作", ""))),
           sum(1 for i in items if "需决断" in str(i.get("动作", ""))),
           sum(1 for i in items if i.get("计划"))),
        "3.弧线：本章契约子句落点 %d 命中 / %d 未命中（未命中者人工复核是否改写偏离）。"
        % (len(a.get("落点命中") or []), len(missed)),
        "4.读者认知：%s；新名词登记 %s。"
        % (rd4.get("上章钩子回应", "无钩子记录"),
           rd4.get("本章新名词(需登记读者已知)") or "无"),
    ]
    return "\n".join(lines)


def sidecar_path(proj: str, num: int) -> str:
    return os.path.join(proj, "追踪", "维护四查_第%03d章.json" % int(num))


def run_checks(proj: str, num: int) -> dict:
    """四查编排入口（finalize 挂点调用）：读项目 → 四域检查 → 待确认卡片 →
    checklist → 落 sidecar 追踪/维护四查_第NNN章.json。返回完整报告 dict。

    - 章节缺失/异常 → {}（调用方跳过，fail-open，绝不阻断定稿）；
    - **不读写 pipeline_state**（不碰 cw["report"] 单槽——三共抢教训）；
    - 追踪/角色状态.json、伏笔表.json 由 tracking_store 惰性播种（既有一惯例）。
    """
    try:
        num = int(num)
        chapters = [(int(c), project.read_file(p))
                    for c, _name, p in project.list_chapters(proj)]
        chapters = sorted([(c, t) for c, t in chapters if t])
        if not chapters or not any(c == num for c, _t in chapters):
            return {}
        names = list((tracking_store.load_characters(proj) or {}).get("order") or [])
        roster_text = project.read_file(os.path.join(proj, "设定", "题材定位.md"))
        rows = (tracking_store.load_foreshadow(proj) or {}).get("rows") or []
        outline_doc = project.read_file(project.get_outline_path(proj, num))
        prev_outline_doc = project.read_file(project.get_outline_path(proj, num - 1))
        fallback_doc = "" if outline_doc.strip() else project.read_file(
            os.path.join(proj, "大纲", "大纲.md"))
        clauses = _outline_clauses(outline_doc, fallback_doc, num)
        report = {
            "version": 1,
            "num": num,
            "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "domains": [
                check_characters(chapters, num, names, roster_text, outline_doc),
                check_foreshadows(chapters, num, rows),
                check_arc(chapters, num, names, clauses),
                check_reader(chapters, num, names,
                             _outline_field(prev_outline_doc, "章末钩子")),
            ],
        }
        report["cards"] = build_cards(report)
        report["checklist"] = checklist(report)
        path = sidecar_path(proj, num)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        return report
    except Exception:  # noqa: BLE001
        return {}
