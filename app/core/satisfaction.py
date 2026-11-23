# -*- coding: utf-8 -*-
"""B1 爽点引擎（0.20.0 L5-B1，质量线唯一 P0；台账 §6.2）

33 章实测无一次完整「压抑→反转→结算」闭环：既有 `- 爽点：` 字段只是一句承诺
（payoff_findings 只能抓推迟语式），没有可逐拍追责的结构化字段。本模块给细纲
加「本章爽点节拍」三拍字段（压抑对象/反转触发/结算兑现），并把它作为必须兑现
的写作指令注入正文轮——生成侧立约、写作侧履约、L0 侧确定性对账（l0_checks.

开关：`writing.satisfaction_engine`（缺省 False，变量隔离纪律）——关闭时本模块
全部产出为空串，装配字节与 0.19.x 逐字节一致；节拍行不存在时 l0_checks 的节拍
检查恒空（证据在场才检查，不读配置）。

设计边界（登记册 B1 原文）：
- 允许「本章无节拍」显式空档——低压章不每章强塞，但空档必须写明，不许缺失本行；
- 「无节拍」不得连续超过 2 章、每 3-5 章至少 1 次完整三拍闭环（连排规则进指令）；
- 判据：盲评 D2（爽点闭环）由 +0.02 → ≥ +0.5。

C33/T1 爽点节奏账本（0.20.2）：跨章部分——sidecar `追踪/爽点账本.json`（每章
{num, beats_declared[], beats_delivered[], 类型, 强度}）+ 三条确定性节奏规则
（连排/空头支票/类型轮换，l0_checks.ledger_findings 消费）。账本是「记录+核对」
通道：不改写任何装配路径，与 satisfaction_engine（改写装配、受字节隔离纪律约束）
解耦，开关 `writing.satisfaction_ledger_enabled` 缺省 on；off 时账本读写与检查
全惰性，输出与现状逐字一致。
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from math import log2

# 节拍字段行（细纲内的唯一事实源；解析与检查共用本正则）
_BEAT_LINE_RE = re.compile(r"^-\s*本章爽点节拍[：:]\s*(.+)$", re.M)

# 显式空档标记（与 l0_checks.payoff_findings 的「无显性爽点」同纪律：不评不判）
_NO_BEAT_MARKERS = ("无节拍", "无爽点节拍", "本章无")

# 三拍结构标记（节拍行缺段 = 结构不完整，供 L0 出「核对」级证据）
_BEAT_SEGMENTS = ("压抑", "反转", "结算")

# 压抑拍与反转拍的边界标记之外的第四拍不许有（防模型把结算写成空头支票）——
# 只查三拍齐全，不约束写法。

_OUTLINE_DIRECTIVE = """

## 本章爽点节拍字段（爽点引擎·每章必须填写，缺行即不合格）
在每章细纲的「- 爽点：」行之后**必须**新增一行，格式三选一：
- 本章爽点节拍：压抑（谁/什么被压制，压力可指认）→ 反转（触发事件与主角动作）→ 结算（兑现与收益，当场落袋）
- 本章爽点节拍：本章无节拍（理由：……）——低压/铺垫章的显式空档
- 承接章（上一章已立压抑拍）：本章爽点节拍：压抑（延续上章）→ 反转（……）→ 结算（……）
纪律：三拍必须落在**本章**可演出的场景上（不许写"下一章才结算"）；「本章无节拍」
连续不得超过 2 章；本批细纲每 3-5 章至少 1 章是完整三拍闭环（结算收益当场到手：
灵石/地位/信息/伤敌，不能白忙）。"""


def _engine_on(cfg: dict) -> bool:
    return bool(((cfg or {}).get("writing", {}) or {}).get("satisfaction_engine", False))


def outline_directive(cfg: dict) -> str:
    """细纲模板尾部的节拍字段指令块；引擎关闭返回空串（装配字节不变）。"""
    return _OUTLINE_DIRECTIVE if _engine_on(cfg) else ""


def beat_of_outline(outline: str) -> str:
    """细纲「本章爽点节拍」行原文（单一事实源；无行返回空串）。"""
    m = _BEAT_LINE_RE.search(outline or "")
    return m.group(1).strip() if m else ""


def beat_declared(beat: str) -> bool:
    """该章是否声明了真实节拍（False = 无行 / 显式空档——两者都不评不判）。"""
    beat = (beat or "").strip()
    if not beat:
        return False
    return not any(m in beat for m in _NO_BEAT_MARKERS[:2]) and not beat.startswith("本章无")


_PROSE_BLOCK_TMPL = """

## 本章爽点节拍（细纲契约：三拍必须逐拍演成场景，不得推迟或一笔带过）
- 细纲节拍：{beat}
执行纪律：压抑拍先给可指认的压力铺垫；反转拍本章当场触发（主角有动作，不是等来的）；
结算拍收益当场落袋并写出在场反应——禁止「算了吧/改日再算」式推迟（L0 预检按推迟
语式确定性抓，检出即进审校裁决）。"""


def prose_beat_block(outline: str) -> str:
    """正文 PROSE 轮的节拍兑现指令块。

    仅当本章细纲声明了真实节拍时非空——「本章无节拍」章与引擎关闭时返回空串
    （空档章不强塞，装配字节与引擎关闭逐字节一致）。
    """
    beat = beat_of_outline(outline)
    if not beat_declared(beat):
        return ""
    return _PROSE_BLOCK_TMPL.format(beat=beat[:300])


# ---- C33/T1 爽点节奏账本：sidecar 读写 + 类型/强度解析 + 三条跨章节奏规则 ----

# 节拍类型受控表（关键词分类，元组顺序即优先级；细纲显式「- 节拍类型：」行优先——
# 该行由共写细纲字段提供，流水线细纲无行时按节拍行关键词确定性归类）。
_LEDGER_TYPES = (
    ("打脸", ("打脸", "反击", "羞辱", "嘲讽", "对峙", "下不来台")),
    ("复仇", ("复仇", "报仇", "清算", "血债", "雪耻")),
    ("揭露", ("揭露", "揭穿", "拆穿", "真相大白", "亮明身份", "身份曝光")),
    ("收获", ("收获", "灵石", "宝物", "奖励", "报酬", "进账", "赏金", "丹药", "功法")),
    ("突破", ("突破", "晋阶", "进阶", "晋升", "升级", "破境", "领悟")),
    ("地位", ("扬名", "认可", "册封", "声望", "地位", "震惊全场", "刮目相看")),
)

_LEDGER_TYPE_LINE_RE = re.compile(r"^-\s*节拍类型[：:]\s*(.+)$", re.M)
_LEDGER_INTENSITY_LINE_RE = re.compile(r"^-\s*节拍强度[：:]\s*([强中弱])", re.M)
_NO_VALUE_MARKERS = ("无", "（无）", "(无)")


def ledger_enabled(cfg: dict) -> bool:
    """账本开关（writing.satisfaction_ledger_enabled，缺省 on）。

    与 satisfaction_engine 解耦：引擎改写装配路径（受字节隔离纪律约束、缺省关）；
    账本只记录+核对（sidecar 落账 + L0 审校证据），不改写路径，缺省 on。
    """
    return bool(((cfg or {}).get("writing", {}) or {}).get("satisfaction_ledger_enabled", True))


def _ledger_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "爽点账本.json")


def load_ledger(proj: str) -> dict:
    """读 sidecar（fail-open：缺失/损坏 → 空账本，绝不阻断）。"""
    try:
        with open(_ledger_path(proj), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            return {"version": 1, "rows": []}
        return data
    except Exception:  # noqa: BLE001
        return {"version": 1, "rows": []}


def save_ledger(proj: str, data: dict) -> None:
    path = _ledger_path(proj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def record_chapter(proj: str, row: dict) -> None:
    """本章行落账（按 num upsert，保持章序升序；重写/续跑同章覆盖旧值）。"""
    data = load_ledger(proj)
    num = int(row.get("num") or 0)
    rows = [r for r in data.get("rows") or [] if int(r.get("num") or 0) != num]
    rows.append(dict(row))
    rows.sort(key=lambda r: int(r.get("num") or 0))
    save_ledger(proj, {"version": data.get("version") or 1, "rows": rows})


def declared_segments(beat: str) -> list:
    """节拍行 → 声明拍段列表（按箭头切分；无行/显式空档 → 空列表）。"""
    if not beat_declared(beat):
        return []
    return [seg.strip()[:80] for seg in re.split(r"→|->", beat) if seg.strip()][:4]


def classify_type(beat: str) -> str:
    """节拍行关键词 → 受控类型（无命中 → 「其他」；纯确定性词典）。"""
    text = beat or ""
    for name, kws in _LEDGER_TYPES:
        if any(k in text for k in kws):
            return name
    return "其他" if beat_declared(text) else ""


def outline_type(outline: str) -> str:
    """本章节拍类型：细纲「- 节拍类型：」行优先；否则按节拍行关键词归类。

    空档章/无节拍行 → 空串（不参与类型分布与连排统计）。
    """
    m = _LEDGER_TYPE_LINE_RE.search(outline or "")
    if m:
        v = m.group(1).strip()
        return "" if v in _NO_VALUE_MARKERS or v.startswith("无") else v[:12]
    beat = beat_of_outline(outline)
    return classify_type(beat) if beat_declared(beat) else ""


def outline_intensity(outline: str) -> str:
    """本章节拍强度（细纲「- 节拍强度：强|中|弱」行；无行 → 空串=未自报）。"""
    m = _LEDGER_INTENSITY_LINE_RE.search(outline or "")
    return m.group(1) if m else ""


def ledger_row(num: int, outline: str, cfg: dict = None) -> dict | None:
    """本章账本行（assemble 立据；账本关闭 → None，全链路惰性）。

    beats_delivered 初值 None（未审）——由审校 B_PAYOFF 维裁决回写（apply_payoff_verdict）。
    """
    if not ledger_enabled(cfg):
        return None
    return {"num": int(num), "beats_declared": declared_segments(beat_of_outline(outline)),
            "beats_delivered": None, "类型": outline_type(outline),
            "强度": outline_intensity(outline)}


def apply_payoff_verdict(row: dict, review_items) -> dict:
    """审校 B_PAYOFF 维（六维 ===B_PAYOFF===）裁决 → 回写 delivered（纯函数）。

    - B_PAYOFF 无 fail 级条目 → 兑现（delivered 拷贝 declared）；
    - 有 fail 级条目 → 未兑现（delivered=[]，计一张「空头支票」欠账）；
    - 无 B_PAYOFF 证据（未审/人工审校/字数预检拦截）→ 保持 None（不评不计欠账）。
    """
    items = [it for it in (review_items or [])
             if isinstance(it, dict) and it.get("dim") == "B_PAYOFF"]
    if items:
        row["beats_delivered"] = ([] if any(it.get("level") == "fail" for it in items)
                                  else list(row.get("beats_declared") or []))
    return row


def rhythm_findings(rows, cur_num: int, outline: str = "") -> list:
    """三条跨章节奏规则（纯确定性、零 LLM；产出交 l0_checks.ledger_findings 进审校）。

    ① 连排（节奏单一，fail候选）：同型节拍连续 ≥3 章无变化（含本章；空档章视同换型断链）；
    ② 闭环率（空头支票，fail候选）：声明节拍但章末审校判未兑现（delivered==[]）的章
       累计 ≥2——欠账持续挂账直至兑现；
    ③ 类型轮换（advisory）：全书节拍类型分布熵过低（有型章 ≥6 且香农熵 < 1.0 bit）。

    rows 为账本历史行（< cur_num）；本章类型由 outline 实时解析（审校先于落账）。
    任何异常返回空（fail-open，绝不阻断）。
    """
    try:
        cur_num = int(cur_num)
        history = sorted((r for r in (rows or []) if isinstance(r, dict) and r.get("num")
                          and int(r["num"]) < cur_num),
                         key=lambda r: int(r["num"]))
        cur_beat = beat_of_outline(outline)
        cur_type = outline_type(outline) if beat_declared(cur_beat) else ""
        findings = []

        # ① 连排：历史有型章序列 + 本章 → 只追「含本章」的尾部同型连跑（已裁决过的
        # 历史连排不重复追责；空档章视同换型断链，账本号不连续按行序连续计）
        seq = [(int(r["num"]), str(r.get("类型") or "")) for r in history]
        if cur_type:
            seq.append((cur_num, cur_type))
        run = []
        for n, t in seq:
            if t and run and run[-1][1] == t:
                run.append((n, t))
            elif t:
                run = [(n, t)]
            else:
                run = []
        if len(run) >= 3 and cur_type and run[-1][0] == cur_num:
            findings.append({
                "level": "fail候选", "check": "节奏单一",
                "text": "第%s章连续 %d 章同为「%s」型节拍、无变化——读者「又是这招」"
                        "疲劳峰值。本章请换型（收获/突破/揭露/地位任一）或显式写明空档"
                        "理由，请裁决。" % ("、".join(str(n) for n, _ in run), len(run),
                                           cur_type),
                "quote": "",
            })

        # ② 空头支票：声明节拍但章末判未兑现的欠账累计
        owed = [int(r["num"]) for r in history
                if r.get("beats_declared") and r.get("beats_delivered") == []]
        if len(owed) >= 2:
            findings.append({
                "level": "fail候选", "check": "空头支票",
                "text": "爽点账本累计 %d 章声明节拍但章末审校判未兑现（第%s章）——空头支票。"
                        "请优先安排补偿性兑现（前债收益当场落袋），未还清前持续挂账，请裁决。"
                        % (len(owed), "、".join(str(n) for n in owed[-6:])),
                "quote": "",
            })

        # ③ 类型轮换：全书分布熵过低（样本 ≥6 章才评，证据不足不判）
        types = [str(r.get("类型") or "") for r in history if r.get("类型")]
        if cur_type:
            types.append(cur_type)
        if len(types) >= 6:
            dist = Counter(types)
            total = len(types)
            entropy = -sum((c / total) * log2(c / total) for c in dist.values())
            if entropy < 1.0:
                cold = min(dist, key=dist.get)
                findings.append({
                    "level": "advisory", "check": "类型轮换",
                    "text": "全书节拍类型分布熵 %.2f bit < 1.0（%d 章：%s）——类型轮换不足，"
                            "后续细纲建议轮换冷型（当前最少：%s）。"
                            % (entropy, total,
                               "/".join("%s×%d" % (k, v) for k, v in dist.most_common()), cold),
                    "quote": "",
                })
        return findings
    except Exception:  # noqa: BLE001
        return []
