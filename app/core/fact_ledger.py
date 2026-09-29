# -*- coding: utf-8 -*-
"""P1 事实账本（卡9：引文锚定入库的确定性底座，源自 AI-Novel-Writer
electron/repositories/summary-repository.ts:216 的入库闸门）

机制一句话：每条抽取出的连续性事实必须携带一条能在**该章定稿正文**中定位的
evidence 引文（精确→归一化两级），锚定失败的事实**逐条拒收**不入账——记忆
抽取幻觉在入库前被结构性拦截。原型 _scratch/superiter/proto/p1_quote_anchor.py
在三真实项目实测：真实抽取 strict 逐字锚定 92% → normalized（NFKC+去空白+
统一引号）100%；三类幻觉对照（改写/跨章错绑/录入噪声）36/36 按预期拦截；
整笔拒绝会连坐丢 124 条真事实，故采用逐条拒收。

本卡边界：只做「给定抽取结果 → 解析 → 两级锚定 → 逐条拒收 → append 入账」
的确定性底座 + 挂点占位。LLM 抽取调用本身属后续抽取闸门卡：finalize 侧读
ctx.fact_extraction（暂无生产者，缺省跳过）、反哺侧只做账本 freshness 对账
（对接 CW-G6 backflow_is_fresh 的「锁定⇒账本行必须存在」前置）——均 fail-open。

产物：`追踪/事实账本.jsonl`（append-only，每行一条 {chapter, claim, evidence,
anchored, ts, source}，中文直存；按「章号+归一化 claim+归一化 evidence」去重）。
D3 源身份钉死（0.23.0，对位 AINW 五重钉死的落地增量）：新条目一律携带 source
三件套——{prose_sha256（入账所锚定正文的全文 sha256 短 12 位）, gen_watermark
（代际/版本号，调用方传入，未知如实留空）, confirmed_by（来源标注）}；入账时自动
计算填写。读取侧向后兼容：无 source 的旧条目容忍读取（source_of 返回 None）；
新条目必须带齐三键——调用方显式给了残缺 source 的条目逐条拒收并告警。
账本**绝不进 state['cw']**（worker 线程 load→save 已是丢失更新窗口，账本进
state 会放大——卡9 原文裁决）；本模块自身零 LLM、零网络、fail-open。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import unicodedata

# S6a：原 from .. import project 上探边拆除（C42-1 引入的 core->app-top 违规）——
# ledger_is_fresh 所需的本章正文路径改由调用方解析传入（参数注入）。

# 未来抽取闸门的 LLM 输出 schema 约定（本卡只消费该形态，不负责产生它）
FACTS_SCHEMA_HINT = (
    '输出 JSON：{"facts": [{"claim": "一句话事实断言", "evidence": "能在本章正文'
    '逐字定位的原句引文"}]}；evidence 必须逐字摘自本章正文，不许改写。'
)

# 事实账本文件名（追踪/ 内，与 爽点账本.json 同区不同名——jsonl 逐行追加语义）
LEDGER_FILENAME = "事实账本.jsonl"

# 单条 evidence 长度上限（防御超长垃圾引文；正常整句远小于此）
_EVIDENCE_MAX = 500

# 引号/破折号类符号剥离表：中英弯引号、直引号、方头引号、省略号、各类破折号、
# 间隔号（原型 p1_quote_anchor._QUOTE_TRANS 逐字搬运——92%→100% 的关键）
_QUOTE_TRANS = str.maketrans("", "", "“”‘’「」『』…—·–\"'")

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# D3 源身份三件套键（新条目 source 字段必须带齐；旧条目无此字段容忍读取）
SOURCE_KEYS = ("prose_sha256", "gen_watermark", "confirmed_by")

logger = logging.getLogger("qianbi.fact_ledger")


def _now_str() -> str:
    return datetime.datetime.now().strftime(_TS_FORMAT)


def _parse_ts(text: str):
    try:
        return datetime.datetime.strptime(text, _TS_FORMAT)
    except (TypeError, ValueError):
        return None


def normalize(s: str) -> str:
    """归一化：NFKC + 去全部空白 + 剥引号/破折号类符号。

    锚定第二级的比较口径（原型 anchor_norm 直接搬运）。三态语义：
    strict（原文逐字 includes）→ norm（归一化后 includes）→ 拒收。
    录入噪声（全半角引号互换、多余空差）在本级被救回；改写/跨章幻觉仍被拦。
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", "", s)
    return s.translate(_QUOTE_TRANS)


def anchor_level(evidence: str, chapter_text: str, norm_text: str = None):
    """两级锚定闸门。返回 "strict" / "norm" / None（锚定失败）。

    strict = evidence 在原文章节正文逐字出现（AI-Novel-Writer 原版口径）；
    norm   = 归一化后出现（qianbi 落地口径，救回引号/空差录入噪声）。
    norm_text 可传入预算好的 normalize(chapter_text) 复用（批量锚定省一次计算）。
    """
    evidence = (evidence or "").strip()
    if not evidence or not chapter_text:
        return None
    if evidence in chapter_text:
        return "strict"
    if norm_text is None:
        norm_text = normalize(chapter_text)
    if normalize(evidence) in norm_text:
        return "norm"
    return None


def extract_facts(num: int, raw):
    """LLM 抽取结果解析 + schema 校验（纯确定性；抽取调用本身属后续闸门卡）。

    接受三种形态（宽容解析，均失败则返回空）：
      1. JSON 对象 {"facts": [...]}；2. 裸数组 [...]；3. 含 ```json 围栏的混合文本。
    schema：每条 {"claim", "evidence"}——evidence 缺失/空（无引文）或非字符串、
    evidence 超长（>_EVIDENCE_MAX）的条目剔除并记入 parse_rejected（附原因）。
    返回 (facts, parse_rejected)：facts 元素 {chapter:int, claim:str, evidence:str}。
    """
    num = int(num)
    facts, parse_rejected = [], []
    items, err = _extract_items(raw)
    if err:
        return [], [{"claim": "", "reason": err}]
    for it in items or []:
        if not isinstance(it, dict):
            parse_rejected.append({"claim": "", "reason": "条目非对象"})
            continue
        claim = it.get("claim")
        evidence = it.get("evidence")
        claim = claim.strip() if isinstance(claim, str) else ""
        if not isinstance(evidence, str) or not evidence.strip():
            parse_rejected.append({"claim": claim[:60], "reason": "缺 evidence 引文（无引文不入账）"})
            continue
        evidence = evidence.strip()
        if len(evidence) > _EVIDENCE_MAX:
            parse_rejected.append({"claim": claim[:60], "reason": "evidence 超长（>%d）" % _EVIDENCE_MAX})
            continue
        facts.append({"chapter": num, "claim": claim, "evidence": evidence})
    return facts, parse_rejected


def _extract_items(raw):
    """从原始抽取输出里取出条目列表。返回 (items, 错误说明)；失败 items=[]。"""
    if raw is None:
        return [], "抽取结果为空"
    if isinstance(raw, list):
        return raw, ""
    if isinstance(raw, dict):
        items = raw.get("facts")
        return (items if isinstance(items, list) else []), "" if isinstance(items, list) else "缺少 facts 数组"
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return [], "抽取结果为空"
        candidates = [text]
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if m:
            candidates.insert(0, m.group(1).strip())
        # 首个 {/[ 到最后一个 }/] 的切片（模型爱在 JSON 前后加说明文字）
        for opener, closer in (("{", "}"), ("[", "]")):
            i, j = text.find(opener), text.rfind(closer)
            if 0 <= i < j:
                candidates.append(text[i:j + 1])
        for cand in candidates:
            try:
                data = json.loads(cand)
            except ValueError:
                continue
            if isinstance(data, list):
                return data, ""
            if isinstance(data, dict) and isinstance(data.get("facts"), list):
                return data["facts"], ""
    return [], "抽取结果解析失败（非 JSON / 缺 facts 数组）"


def ledger_path(proj: str) -> str:
    return os.path.join(proj, "追踪", LEDGER_FILENAME)


# ---------------- D3 源身份钉死（0.23.0）----------------

def build_source(chapter_text: str, gen_watermark: str = "",
                 confirmed_by: str = "") -> dict:
    """入账条目的源身份三件套（ingest_facts 自动计算填写）：
      - prose_sha256：入账所锚定的本章正文全文 sha256 短 12 位——正文手改一个字
        即可对出「这条账不是对这份正文记的」（AINW 内容哈希钉死的对位物）；
      - gen_watermark：代际/版本号（章节定稿版本号或抽取代际；调用方传入，
        未知如实留空——不猜）；
      - confirmed_by：来源标注（谁入的账：抽取相位名/人工通道名；空时落
        "extraction"=抽取闸门缺省通道）。
    """
    return {"prose_sha256": hashlib.sha256((chapter_text or "").encode("utf-8")).hexdigest()[:12],
            "gen_watermark": str(gen_watermark or ""),
            "confirmed_by": str(confirmed_by or "").strip() or "extraction"}


def _source_complete(src) -> bool:
    """调用方显式提供的 source 是否三键齐全且类型合法（新条目入账硬门槛）"""
    return (isinstance(src, dict)
            and all(str(src.get(k) or "").strip() for k in SOURCE_KEYS))


def source_of(row: dict):
    """读条目 source 字段：无 source（或非 dict）的**旧条目**返回 None——向后兼容
    容忍读取，消费方据此走 legacy 路径；新条目一律三键齐全。"""
    src = (row or {}).get("source")
    return src if isinstance(src, dict) else None


def read_ledger(proj: str) -> list:
    """全量读账本（jsonl 逐行 json，坏行跳过）。缺失/损坏 → []（fail-open）。"""
    rows = []
    try:
        with open(ledger_path(proj), encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


def _row_key(chapter: int, claim: str, evidence: str) -> tuple:
    """去重键：章号 + 归一化 claim + 归一化 evidence（同章同事实只记一笔）。"""
    return (int(chapter), normalize(claim), normalize(evidence))


def ingest_facts(proj: str, num: int, facts: list, chapter_text: str, *,
                 gen_watermark: str = "", confirmed_by: str = "") -> dict:
    """逐条锚定 + 逐条拒收 + append 入账（核心入口，纯确定性）。

    逐条拒收：锚定失败只拒该条，同批其余事实照常入账（原型结论——整笔拒绝
    在真实数据连坐丢 124 条真事实）。同章同事实（去重键相同）跳过不重复入账。
    D3 源身份：入账行自动携带 source 三件套（build_source 按本章正文全文哈希
    + gen_watermark/confirmed_by 参数构建）；调用方在事实条目上**显式**给了
    source 的，必须三键齐全——残缺即该条拒收并告警（新条目必须带，缺→拒收）。
    返回报告 {total, kept, strict, norm, rejected, duplicates, rejected_items}。
    """
    num = int(num)
    facts = facts or []
    norm_text = normalize(chapter_text or "")
    src = build_source(chapter_text, gen_watermark, confirmed_by)
    existing = {_row_key(r.get("chapter", -1), str(r.get("claim") or ""),
                         str(r.get("evidence") or ""))
                for r in read_ledger(proj)}
    kept = strict_cnt = norm_cnt = rejected = dups = 0
    rejected_items, lines = [], []
    for fct in facts:
        if not isinstance(fct, dict):
            rejected += 1
            rejected_items.append({"claim": "", "reason": "条目非对象"})
            continue
        # D3：显式给了 source 的条目必须身份齐全（缺→拒收并告警；未给的走自动填写）
        if "source" in fct and not _source_complete(fct.get("source")):
            claim_bad = str(fct.get("claim") or "").strip()
            rejected += 1
            rejected_items.append({"claim": claim_bad[:60],
                                   "reason": "缺 source 源身份字段（新条目必须带齐 "
                                             f"{'/'.join(SOURCE_KEYS)}）"})
            logger.warning("事实账本拒收缺源身份条目（第%s章）：%s", num, claim_bad[:60])
            continue
        claim = str(fct.get("claim") or "").strip()
        evidence = str(fct.get("evidence") or "").strip()
        lvl = anchor_level(evidence, chapter_text or "", norm_text)
        if lvl is None:
            rejected += 1
            rejected_items.append({"claim": claim[:60], "evidence": evidence[:60],
                                   "reason": "锚定失败（逐条拒收，不连坐）"})
            continue
        key = _row_key(num, claim, evidence)
        if key in existing:
            dups += 1
            continue
        existing.add(key)
        lines.append(json.dumps({"chapter": num, "claim": claim, "evidence": evidence,
                                 "anchored": lvl, "ts": _now_str(), "source": dict(src)},
                                ensure_ascii=False))
        kept += 1
        if lvl == "strict":
            strict_cnt += 1
        else:
            norm_cnt += 1
    if lines:
        path = ledger_path(proj)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return {"total": len(facts), "kept": kept, "strict": strict_cnt, "norm": norm_cnt,
            "rejected": rejected, "duplicates": dups, "rejected_items": rejected_items}


def ingest_from_extraction(proj: str, num: int, raw, chapter_text: str, *,
                           gen_watermark: str = "", confirmed_by: str = ""):
    """finalize/反哺挂点的串装入口：抽取结果 → 解析 → 锚定入账。

    raw 为空（None/空白串/解析零条）→ 返回 None（调用方整段跳过——fail-open，
    本卡抽取闸门未接入时的常态路径）。gen_watermark/confirmed_by 透传
    ingest_facts（D3 源身份钉死；调用方持有章节版本号/相位名时传入）。
    """
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    facts, _parse_rej = extract_facts(num, raw)
    if not facts:
        return None
    return ingest_facts(proj, num, facts, chapter_text,
                        gen_watermark=gen_watermark, confirmed_by=confirmed_by)


def ledger_is_fresh(proj: str, num: int, *, chapter_path: str) -> bool:
    """账本新鲜（对接 state.backflow_is_fresh 同口径）：「锁定⇒本章账本行必须
    存在」的对账前置。本章已有账本行，且最新落账时间不早于正文文件 mtime
    （正文未在账本落账后再被改动）。无行/无正文/时间戳解析失败 → False。

    chapter_path：本章正文文件路径（调用方以 project.list_chapters 解析传入——
    S6a 参数注入，路径类依赖不上探 app-top；空串=无正文 → False，与原查无此章
    同语义）。
    """
    try:
        num = int(num)
        rows = [r for r in read_ledger(proj) if r.get("chapter") == num]
        if not rows:
            return False
        ts = None
        for r in rows:
            p = _parse_ts(str(r.get("ts") or ""))
            if p and (ts is None or p > ts):
                ts = p
        if ts is None:
            return False
        path = chapter_path or ""
        if not path or not os.path.exists(path):
            return False
        return os.path.getmtime(path) <= ts.timestamp()
    except Exception:  # noqa: BLE001
        return False
