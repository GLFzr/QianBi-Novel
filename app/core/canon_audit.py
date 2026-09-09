# -*- coding: utf-8 -*-
"""设定清算（方案 D1/D4/F1）：本章正文 vs 世界观底册的三分类对账

验证①的教训产品化：底册没有的设定，作者（模型）会自己发明——
「执事堂」这类自创制度若不在定稿当时点名，就会在后续章节被当成正典继续引用，
返工成本按章节复利增长。本模块每章定稿后跑一次：
  violations —— 与底册冲突或底册无依据的自创（三分类：硬伤/软伤 + in_ledger 判定）
  adocations —— 可收编入世界书的自创条目（人工裁决后写「追加登记」）
  pattern_hits —— must 规则中带字面 pattern 的确定性命中（复用 mustscan，零 LLM）

审校模型纪律（F1）：严格判定不许 flash 单飞——JSON 解析失败或「why 字段复读」
（模板退化，验证①实测）自动升 pro 重试一次；再失败则落盘原始输出交人工。
"""
import json
import logging
import os
import re

from .. import config as cfg_mod
from .. import mustscan, project
from ..llm.client import LLMClient
from . import state as st
from .shared_prefix import constraints_block, project_header

logger = logging.getLogger("qianbi.canon")

AUDIT_PROMPT = """{project_header}

你是网文世界观的合规审校。下面是一部小说的【设定底册条目名】【全书连续性台账】
【核心设定约束条款】与【第 {num} 章正文】。
找出正文中的世界观问题，每条独立说明，禁止复用同一句评语：
1. violations：与底册冲突的陈述，或底册无依据的自创体系/机构/货币/职业/丹药名；
   或违反【核心设定约束条款】的行为（如金手指越过限制/消耗/触发条款）；
   或章内自相矛盾（同一物象/事实在章内前后两处描述不一致——逐处对表自查）；
   或**数值对账**：金额/斤两/数量/次数在章内前后或与邻章不一致（逐个数字对表）。
   定级纪律：判「硬伤」前必须确认所引邻章/底册原文**真实存在且未被断章**（不得拼接引文）；
   无法确证的只记软伤。数字/次数类矛盾若正文内有解释性语句则降软伤。
   - quote：正文原句（≤40 字）；why：针对该句的具体说明 ≤40 字（每条都不同，禁止复读正文）；
   - canon_ref：底册条目名或约束条款名（给不出写「底册无此条」）；severity：硬伤/软伤。
2. adoptions：正文新出现、与底册不冲突、值得收编进世界书的自创专名。
   - name/cat/desc（desc ≤50 字）。
   **收录下限**：本章全部新出场人物、新物证/关键道具、新地点/机构必须逐条收录，不许遗漏。
3. ledger_updates：本章为全书连续性台账新增/变更的事实——
   人物（出场者及其本章末状态）、物件（新物证/关键道具及其位置与状态）、
   制度（本章援引或新立的规矩）、时间（本章故事内日期/时段；若正文出现「三日后」「初五」等历法表述，必须原样写进时间字段）。
没有问题就返回空数组。只输出紧凑 JSON（结论即全部内容，不要输出推理过程——推理放在思考通道）：
{{"violations": [{{"quote":"","why":"","canon_ref":"","severity":""}}],
  "adoptions": [{{"name":"","cat":"","desc":""}}],
  "ledger_updates": {{"人物": [{{"name":"","state":""}}], "物件": [{{"name":"","state":""}}],
                      "制度": [{{"name":"","state":""}}], "时间": ""}},
  "beat_check": {{"total": <细纲情节点总数>, "verified": [<已落地的情节点编号>], "missing": [<未落地的情节点编号>]}}}}

【核心设定约束条款】（金手指限制/消耗/反噬/触发条件与全局红线——违反即 violations）
{constraints_block}

【授权自创清单】（核心设定明文授权的自创专名——下列条目为合法设定，
不得记为违反；正文新出场的人物/机构/地点在 adoptions 中必须收录，不许遗漏）
{authorized}

【全书连续性台账】（跨章事实基准：本章与之冲突即 violations；同时按本章事实更新台账）
{ledger_block}

【上一章结尾】（前情衔接基准）
{prev_ending}

【下一章开头】（后文衔接基准）
{next_opening}

【本章细纲】（拍点契约：正文的每个情节点/冻结表条目/命名拍必须在此有对应——
缺失、漂移、自造都记入 violations，quote 填正文原句，canon_ref 填「细纲情节点N」）
{outline_brief}

【第 {num} 章正文】
{prose}

除 violations/adoptions/ledger_updates 外，追加第四段 cross_issues：本章正文与上一章结尾、
下一章开头之间的**硬矛盾**（物证位置/藏物方式/时间线/人物在场/门锁门闩等不可并存的细节）。
每条：{{"quote":"本章原句", "against":"邻章原句", "why":"矛盾说明"}}。没有就返回空数组。
"""

EXPECTED_CATEGORIES = ("体系规则", "地理", "势力", "人物", "物品", "异火", "丹药", "斗技", "历史", "经济")

# 条目级早停指令（v0.20 成本战役 E3.3，stage_params.canon_audit.early_stop: true 启用）。
# 依据：Certaindex/Dynasor（arXiv:2412.20993）答案稳定即早停 -50% 计算量精度不掉、
# answer convergence（arXiv:2506.02536）60% 步骤后结论收敛——prompt 层模拟：先逐条
# 分诊（clean 不再复查），只对 suspect/unsure 展开。
# W-7：分诊**只留在思考通道**，不再要求输出 triage 字段——全仓无读方（report["triage"]
# 只写不读），却按章付输出价并把它永久留在栈里（带复利）。
EARLY_STOP_DIRECTIVE = """
## 对账纪律（条目级早停——先分诊后展开，节省思考量）
在思考通道先做一轮**快速分诊**：对【本章细纲】逐拍点、对正文逐段给出
clean（明显无问题）/ suspect（疑似有问题）/ unsure（拿不准）的初步结论；
结论已稳定为 clean 的条目**不再复查**，只对 suspect 与 unsure 条目展开完整分析。
分诊过程只留在思考通道，**不要输出分诊清单**：输出仍只有 violations / cross_issues /
adoptions 等既有字段。
violations 与 cross_issues 只收录 suspect、unsure 条目展开后成立的结论。
"""


def _phase_flags(cfg: dict, proj: str, phase: str = "canon_audit",
                 builtin: dict = None) -> dict:
    """本相位的合并参数档（genre 显式配置压过内置机械相位表——与 stages.preset_param_layers
    同语义；canon_audit 本模块不 import stages（避免环），内置表只含本相位所需子集）
    builtin 传入时用它作默认档——终审判要的是 high，不是预扫那档 low。"""
    merged = dict(builtin) if builtin else {
        "thinking": "enabled", "reasoning_effort": "low", "max_tokens": 8192}
    try:
        from .. import presets as genre_presets
        from . import state as st
        pid = ""
        try:
            pid = st.load_state(proj).get("genre_preset", "") or ""
        except Exception:  # noqa: BLE001
            pass
        sp = genre_presets.stage_params(pid)
        for k, v in (sp.get(phase) or {}).items():
            merged[k] = v
    except Exception:  # noqa: BLE001
        pass
    return merged


AUDIT_REVIEW_PROMPT = """{project_header}

你是网文世界观合规审校的**终审**。flash 预扫为本章标出了以下候选问题，请逐条裁决：
- confirmed：核实成立（引文真实、对照底册/邻章确实矛盾）
- rejected：误报（引文断章、底册实际有据、正文内有解释性语句）
- downgraded：问题存在但够不上硬伤（降软伤）

裁决纪律：判 confirmed 前必须确认引文在片段中真实存在且未被断章；拿不准 → downgraded。

## 预扫候选项
{flagged_list}

## 本章正文相关片段（按候选引文定位）
{fragments}

## 上一章结尾（跨章核对基准）
{prev_ending}

## 本章细纲（拍点契约）
{outline_brief}

## 核心设定约束条款
{constraints_block}

复核中若发现**候选清单之外的硬伤**（只有对照上下文才能发现的），写入 new_items（每条 quote ≤40 字、why ≤40 字）；没有就输出空数组。除裁决外不要输出任何推理过程，直接输出 JSON：
{{"verdicts": [{{"index": 1, "verdict": "confirmed|rejected|downgraded", "note": "≤30字"}}],
  "new_items": []}}
"""


def _extract_fragments(prose: str, quotes: list, window: int = 400, max_len: int = 6000) -> str:
    """按候选引文定位原文片段（±window 字，相邻合并），供 pro 复核缩量输入"""
    spans = []
    for q in quotes:
        q = str(q or "").strip()
        if not q:
            continue
        i = prose.find(q[:20])
        if i < 0:
            i = prose.find(q[:10])
        if i >= 0:
            spans.append((max(0, i - window), min(len(prose), i + len(q) + window)))
    if not spans:
        return prose[:max_len]
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    parts, used = [], 0
    for a, b in merged:
        seg = prose[a:b]
        if used + len(seg) > max_len:
            seg = seg[:max(0, max_len - used)]
            parts.append(seg)
            break
        parts.append(seg)
        used += len(seg)
    return ("\n\n……\n\n").join(parts)


def _pro_review_flagged(cfg: dict, proj: str, num: int, prose: str, prescan_prompt: str,
                        prescan: dict, outline_doc: str, prev_ending: str) -> dict | None:
    """级联第二级：pro 只复核 flagged 项 + 允许补漏。返回合并后的 data；失败返回 None（上层采信预扫）。

    pro 输入从全文缩到「flagged 清单+定位片段」，输出从 16k 全量缩到紧凑裁决——
    pro 单价是 flash 的 3 倍，缩水是级联收益的主要来源。
    """
    flagged = [v for v in (prescan.get("violations") or []) if v.get("severity") == "硬伤"]
    for c in (prescan.get("cross_issues") or []):
        flagged.append({"quote": c.get("quote", ""), "why": c.get("why", ""),
                        "canon_ref": "跨章矛盾", "severity": "硬伤"})
    if not flagged:
        return None
    fl = chr(10).join("%d. [%s] 引文：%s | 疑点：%s | 依据：%s"
                    % (i + 1, v.get("severity"), str(v.get("quote", ""))[:40],
                       str(v.get("why", ""))[:60], v.get("canon_ref", ""))
                    for i, v in enumerate(flagged))
    conn = _strict_conn(cfg)
    if not conn:
        return None
    # W-7：终审判档位改为**可配**（默认仍 pro+high——它是误报进台账的唯一闸门）。
    # 实测该相位 out 116,646 / reasoning 113,541＝97.3% 思考，而裁决文本合计仅 1,473 tok；
    # 关不关交给预设显式声明（stage_params.canon_audit_review），判据＝雷章召回不降。
    review_tier = _phase_flags(cfg, proj, "canon_audit_review",
                               builtin={"thinking": "enabled", "reasoning_effort": "high"})
    client = LLMClient.from_connection(conn, max_retries=1, slot="review",
                                       stage_params={"canon_audit_review": review_tier})
    prompt = AUDIT_REVIEW_PROMPT.format(
        project_header=prescan_prompt.split("【核心设定约束条款】")[0].split("你是网文")[0],
        flagged_list=fl,
        fragments=_extract_fragments(prose, [v.get("quote") for v in flagged]),
        prev_ending=prev_ending,
        outline_brief=(outline_doc or "")[:1500],
        constraints_block=constraints_block(proj))
    parts = []
    client.chat_stream(prompt, temperature=0.2, phase="canon_audit_review",
                       on_chunk=parts.append)
    out = "".join(parts)
    m = re.search(r"\{.*\}", out, re.S)
    review = json.loads(m.group(0) if m else out)
    verdicts = {int(v.get("index", 0) or 0): str(v.get("verdict", "")) for v in (review.get("verdicts") or [])}
    kept, dropped = [], []
    for i, v in enumerate(flagged, 1):
        vd = verdicts.get(i, "")
        if vd == "rejected":
            v["note"] = "pro 终审判误报"
            dropped.append(v)
        elif vd == "downgraded":
            v["severity"] = "软伤"
            v["note"] = "pro 终审降级"
            kept.append(v)
        else:   # confirmed / 未明确裁决 → 保守保留
            v["note"] = (v.get("note") or "") + "pro 终审确认"
            kept.append(v)
    new_items = review.get("new_items") or []
    for nv in new_items:
        nv.setdefault("severity", "硬伤")
        nv["note"] = "pro 终审新增"
        kept.append(nv)
    prescan["violations"] = [v for v in (prescan.get("violations") or []) if v.get("severity") != "硬伤"] + kept
    prescan["review_dropped"] = dropped
    return prescan


def _degenerate(violations: list) -> bool:
    """字段级退化检测（F1）：多条 violations 共用同一句 why = 模板复读，判无效"""
    if len(violations) < 2:
        return False
    whys = [str(v.get("why", "")).strip() for v in violations]
    return len(set(whys)) / len(whys) < 0.5


def _client_for(cfg: dict, router=None, strict: bool = False):
    if router is not None:
        return router.client("review")
    conn = cfg_mod.slot_connection(cfg, cfg_mod.SLOT_REVIEW)
    if strict:
        pro = next((c for c in cfg.get("connections", [])
                    if str(c.get("model", "")).endswith("pro")), None)
        if pro:
            conn = pro
    return LLMClient.from_connection(conn or {}, max_retries=1, slot="review")


def authorized_inventions(proj: str) -> list:
    """读核心设定「授权自创清单」节：审校对清单内专名豁免（方案 D1 迭代②）"""
    core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))
    m = re.search(r"##\s*授权自创清单(.*?)(?=\n##\s|\Z)", core, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        s = line.strip().lstrip("-*• ").strip()
        if not s:
            continue
        name = re.split(r"[：:（(]", s)[0].strip()
        if name:
            out.append(name)
    return out




def load_ledger(proj: str) -> dict:
    """全书连续性台账（Round 4）：人物/物件/制度/时间 四表，逐章更新"""
    path = os.path.join(proj, "追踪", "连续性台账.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:  # noqa: BLE001
            pass
    return {"人物": {}, "物件": {}, "制度": {}, "时间": []}


def save_ledger(proj: str, ledger: dict):
    path = os.path.join(proj, "追踪", "连续性台账.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)


def ledger_block(proj: str, budget: int = 900) -> str:
    """台账渲染注入块"""
    ledger = load_ledger(proj)
    lines, used = [], 0
    for key in ("时间", "人物", "物件", "制度"):
        entries = ledger.get(key) or {}
        if not entries:
            continue
        if key == "时间":
            for t in entries[-6:]:
                line = "- 第%s章：%s" % (t.get("ch"), t.get("day", ""))
                if used + len(line) > budget:
                    break
                lines.append(line)
                used += len(line)
            continue
        for name, info in list(entries.items())[-15:]:
            state = info.get("state", "") if isinstance(info, dict) else str(info)
            ch = info.get("last_ch", "?") if isinstance(info, dict) else "?"
            line = "- %s：%s（第%s章）" % (name, str(state)[:80], ch)
            if used + len(line) > budget:
                break
            lines.append(line)
            used += len(line)
    return "\n".join(lines) if lines else "（台账尚空——本章事实将首次入册）"


def apply_ledger_updates(proj: str, num: int, updates: dict) -> int:
    """把本章 ledger_updates 并入台账（同名单纯覆盖为最新状态），返回变更数"""
    if not isinstance(updates, dict):
        return 0
    ledger = load_ledger(proj)
    changed = 0
    for key in ("人物", "物件", "制度"):
        table = ledger.setdefault(key, {})
        for item in (updates.get(key) or []):
            if isinstance(item, dict) and item.get("name"):
                table[str(item["name"])[:30]] = {"state": str(item.get("state", ""))[:200],
                                                 "last_ch": int(num)}
                changed += 1
    day = str(updates.get("时间") or "").strip()
    if day:
        ledger.setdefault("时间", []).append({"ch": int(num), "day": day[:60]})
        changed += 1
    save_ledger(proj, ledger)
    return changed


def audit_chapter(proj: str, num: int, prose: str, cfg: dict, router=None,
                  session=None) -> dict:
    """本章设定清算。产物：追踪/设定清算_第NNN.json；返回同构 dict（含 pattern_hits）。

    S2（in_session 旗标）：会话可用且审计客户端与栈基座同源（base_url+model 一致，
    N2 红线——异构网关入会话=整栈缓存清零）时，预扫作为**会话追加轮**执行：system
    前缀与全部历史命中，miss 只剩增量（E0.1 实测独立单发 4.7k miss/笔 → 会话内 ~3k）。
    解析失败/退化即回退独立单发路径（F1 质量上限保留），失败轮不留在会话历史里。
    """
    authorized = [a for a in authorized_inventions(proj) if a]
    ledger_path = os.path.join(proj, "追踪", "拆解清单.json")
    ledger_entries = []
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, encoding="utf-8") as f:
                ledger_entries = json.load(f).get("entries", [])
        except Exception:  # noqa: BLE001
            ledger_entries = []
    names = "、".join(str(e.get("name", "")) for e in ledger_entries if e.get("name"))
    # 邻章回归校验（迭代③）：重写一章不许砸裂前后章接口
    chapters = project.list_chapters(proj)
    by_num = {n: p for n, _nm, p in chapters}
    prev_ending = "（本章为第一章）"
    if any(n < num for n in by_num):
        prev_ending = (project.read_file(by_num[max(n for n in by_num if n < num)])[-600:]
                       or "（无）")
    next_opening = "（本章之后暂无已写章节）"
    if any(n > num for n in by_num):
        next_opening = (project.read_file(by_num[min(n for n in by_num if n > num)])[:600]
                        or "（无）")
    outline_doc = project.read_file(project.get_outline_path(proj, num))
    flags = _phase_flags(cfg, proj)
    early_stop = bool(flags.get("early_stop"))
    prompt = AUDIT_PROMPT.format(num=num, names=names or "（无）",
                                project_header=project_header(proj),
                                authorized="、".join(authorized) or "（无）",
                                constraints_block=constraints_block(proj),
                                ledger_block=ledger_block(proj),
                                outline_brief=outline_doc[:2000] or "（无细纲）",
                                prev_ending=prev_ending,
                                next_opening=next_opening,
                                prose=prose[:6000])
    if early_stop:
        prompt += EARLY_STOP_DIRECTIVE

    client = _client_for(cfg, router)

    # ---- S2：预扫入会话（追加轮）——成功则跳过独立单发循环；任何失败回退原路径 ----
    s2_in_session = False
    if session is not None and getattr(session, "enabled", False) \
            and bool(flags.get("in_session")):
        try:
            base = getattr(session, "_client", None)
            same_domain = base is not None and \
                (getattr(base, "base_url", ""), getattr(base, "model", "")) == \
                (getattr(client, "base_url", ""), getattr(client, "model", ""))
            if same_domain:
                # 会话内正文已在历史（写作轮回复）——把 6000 字正文再注入一遍是纯冗余
                # （S2 首跑实测：只剥 header 不剥 prose → 7.0k miss/笔，93.5% 原地踏步）
                prose_ref = ("【＝本会话中最近一条完整的章正文消息（历史已载），"
                             "直接对它执行对账，不要要求重复输出】")
                body_prompt = prompt.replace(prose[:6000], prose_ref, 1)
                # V1-④（T 轮报告 §9-F）：整段剥离渲染后的 project_header。旧写法
                # split("\n\n", 1) 只剥掉 36 字标题行——header 首个空行在标题行后，
                # 余下 ~3.0k 字符在会话轮里每章重复计价。会话 system 已含同一
                # header（卷会话前缀），逐字节精确剥离是安全的。W-2 把判据从
                # startswith 放宽成"整块出现"：模板版式一旦在 header 前多出前导行，
                # startswith 会静默失配 ⇒ 每章白骑一遍前缀（t3b 卷2 实测 24 章 ×6.3k 字）。
                _hdr = project_header(proj)
                if _hdr and _hdr in body_prompt:
                    body_prompt = body_prompt.replace(_hdr, "", 1).lstrip("\n")
                elif _hdr and "## 核心设定节选" in body_prompt:
                    # 剥不干净＝每章白骑一遍 system 前缀（t3b 实测 ~6.3k 字/章）——
                    # 静默多花钱比报错更糟，这里出声
                    logger.warning("清算会话轮未匹配到 project_header 整块（模板版式变了？），"
                                   "本轮将重复注入约 %d 字前缀", len(_hdr))
                body = body_prompt
                from .chapter_session import ChapterSession
                turn_text = ChapterSession.SCOPE_LINE + "\n\n" + body
                parts2 = []
                t_before = session.turn_count()
                session.ask(turn_text, client=client, phase="canon_audit",
                            on_chunk=parts2.append)
                out2 = "".join(parts2)
                m2 = re.search(r"\{.*\}", out2, re.S)
                s2data = json.loads(m2.group(0) if m2 else out2)
                s2viol = (s2data or {}).get("violations") if isinstance(s2data, dict) else None
                if s2viol is not None and not _degenerate(s2viol):
                    data = s2data
                    s2_in_session = True
                else:
                    # 解析失败/退化：废轮不留史，回退独立单发
                    session.rollback_to(t_before)
        except Exception as e:  # noqa: BLE001
            logger.warning("清算入会话失败（回退单发）：%s", str(e)[:120])
            try:
                session.rollback_to(session.turn_count())
            except Exception:  # noqa: BLE001
                pass

    if not s2_in_session:
        data, last_err = None, ""
    # 级联（v0.19，E9 实测）：flash+low 全文预扫 → 干净采信（省掉 pro 全量）；有硬伤/
    # 跨章矛盾才升 pro **只复核 flagged 项**（输入=清单+定位片段，输出=裁决，双缩水）；
    # 预扫解析失败/退化 → pro 全量兜底（保留 F1 质量上限）。thinking 模式下 temperature
    # 静默失效（官方文档），重试改用措辞扰动而非换温。
    for attempt in range(0 if s2_in_session else 2):
        try:
            parts = []
            retry_prompt = prompt if attempt == 0 else prompt + \
                "\n\n（重试：请逐项重新核对，勿沿用上一次的判断思路，直接输出结论。）"
            client.chat_stream(retry_prompt, temperature=0.2, phase="canon_audit",
                               on_chunk=parts.append)
            out = "".join(parts)
            m = re.search(r"\{.*\}", out, re.S)
            data = json.loads(m.group(0) if m else out)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            data = None
        violations = (data or {}).get("violations") if isinstance(data, dict) else None
        if violations is not None and not _degenerate(violations):
            break
        # 退化/解析失败 → 升 pro 再试一次（F1：严格判定不许 flash 单飞）；
        # 显式传思考档（from_connection 不吃 preset 档，模型默认 enabled+high 恰为严格档所需）。
        # 无 pro 连接（--no-pro / 用户未配严格档）：保持 flash 客户端做措辞扰动重试，
        # 不换成空连接把第二次尝试白白烧掉。
        try:
            strict = _strict_conn(cfg)
            if strict:
                client = LLMClient.from_connection(strict, max_retries=1, slot="review",
                                                   stage_params={"thinking": "enabled",
                                                                 "reasoning_effort": "high"})
        except Exception:  # noqa: BLE001
            pass

    cascade = {"mode": "prescan", "pro_review": False, "in_session": s2_in_session}
    if isinstance(data, dict):
        pre_hard = [v for v in (data.get("violations") or []) if v.get("severity") == "硬伤"]
        pre_cross = data.get("cross_issues") or []
        if pre_hard or pre_cross:
            # 有硬判候选 → pro 终审（只裁 flagged 项 + 允许补漏；输入输出双缩水）
            try:
                review_data = _pro_review_flagged(cfg, proj, num, prose, prompt, data,
                                                  outline_doc, prev_ending)
                if review_data is not None:
                    cascade = {"mode": "cascade", "pro_review": True}
                    data = review_data
            except Exception as e:  # noqa: BLE001
                logger.warning("pro 复核失败（采信预扫结果，不阻断）：%s", e)
                cascade["pro_error"] = str(e)[:120]
        # 干净预扫（0 硬伤 0 跨章矛盾）→ 直接采信：软伤/收编/台账是回写型产物，无闸门风险
    failed = not isinstance(data, dict)
    if failed:
        # 空结果闸门（Round 4 终审差距①）：审校崩溃不许以 violations=[] 冒充「干净」入库
        data = {"violations": [], "adoptions": [],
                "error": f"清算解析失败：{last_err or '重复退化'}（原始输出需人工查看）"}

    violations = data.get("violations") or []
    ledger_all = names + " " + json.dumps(ledger_entries, ensure_ascii=False)
    prev_seen = _prev_seen_violations(proj, num)      # 跨章台账（去重 + 固化引用升级）
    for v in violations:
        ref = str(v.get("canon_ref", ""))
        probe = ref if ref and ref != "底册无此条" else str(v.get("why", ""))[:12]
        v["in_ledger"] = bool(probe) and probe in ledger_all
        quote = str(v.get("quote", ""))
        v["authorized"] = any(a in quote or a in str(v.get("why", "")) for a in authorized)
        if v["authorized"]:
            # 授权豁免只适用于「专名被误判越界」；拍点缺失/跨产物矛盾即使提到授权专名
            # 也不豁免（R7 实测：品行笺缺失被误标豁免——名词在清单里≠拍点已兑现）
            if any(k in str(v.get("why", "")) for k in ("缺失", "未落地", "未兑现", "不一致", "矛盾")):
                v["severity"] = "软伤"
                v["note"] = "涉及授权专名，但问题性质是拍点/一致性缺陷，不予豁免"
            else:
                v["severity"] = "豁免"
                v["note"] = "核心设定授权自创清单内条目"
        prev = prev_seen.get(quote)
        if prev is not None:
            v["repeat_of_chapter"] = prev
            if v["in_ledger"] is False:
                v["note"] = "未闭环：该自创已被后续章节固化引用（先回填设定层或修改正文）"

    pattern_hits = [{"rule": r.get("rule", ""), "findings": f}
                    for r in _must_rules_with_patterns(proj)
                    for f in [_pattern_check(prose, r)] if f]
    # pattern 字面命中 ≠ 语义违规（验证②实测：单字 pattern 命中"天色/地面"属误报），
    # 一律降为「待语义复核」，不计入违反数——严格判定交由强模型/人工
    for h in pattern_hits:
        h["findings"]["result"] = "待语义复核"
    ledger_updates = data.get("ledger_updates") or {}
    try:
        apply_ledger_updates(proj, num, ledger_updates)
    except Exception as e:  # noqa: BLE001
        logger.warning("台账更新失败（不阻断）：%s", e)
    beat_check = data.get("beat_check") or {}
    # D1' 日历偏差提案：正文历法表述 vs 案发日历对表（只提案，不静默改写）
    cal_path = os.path.join(proj, "追踪", "案发日历.md")
    cal_doc = project.read_file(cal_path) if os.path.exists(cal_path) else ""
    drift = []
    if cal_doc:
        def _num(tok):
            cn = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            return cn.get(tok, tok)
        cal_days = {_num(x) for x in re.findall(r"第\s*([一二三四五六七八九十\d]+)\s*日", cal_doc)}
        for m_day in re.finditer(r"([一二三四五六七八九十\d两]{1,3})\s*日\s*(?:后|之内|以内)", prose):
            token = _num(m_day.group(1))
            if token not in cal_days:
                drift.append({"phrase": m_day.group(0), "why": "案发日历中无该历法表述的登记行"})
    if drift:
        try:
            with open(os.path.join(proj, "追踪", "日历偏差提案.json"), "w", encoding="utf-8") as f:
                json.dump({"num": num, "drifts": drift,
                           "note": "人工裁决：改日历或改正文；裁决后同步案发日历.md"},
                          f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    report = {"num": num, "chars": len(prose), "failed": failed,
              "cascade": cascade,
              "early_stop": early_stop,
              "triage": (data.get("triage") or []) if isinstance(data, dict) else [],
              "beat_check": beat_check,
              "calendar_drift": drift,
              "violations": violations,
              "adoptions": data.get("adoptions") or [],
              "pattern_hits": pattern_hits,
              "cross_issues": data.get("cross_issues") or [],
              "ledger_updates": ledger_updates,
              "error": data.get("error", "")}
    out = os.path.join(proj, "追踪", "设定清算_第%03d.json" % num)
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("设定清算落盘失败：%s", e)
    return report


def _strict_conn(cfg: dict) -> dict:
    """严格档连接：任一 model 以 pro 结尾的行（官方全家桶下即 V4 Pro）；找不到回退空"""
    pro = next((c for c in cfg.get("connections", [])
                if str(c.get("model", "")).endswith("pro")), None)
    return pro or {}


def _must_rules_with_patterns(proj: str) -> list:
    try:
        rules = project.regex_rules(proj)
    except Exception:  # noqa: BLE001
        return []
    return [r for r in rules
            if r.get("level") == "must" and str(r.get("pattern", "")).strip()]


def _pattern_check(prose: str, rule: dict) -> dict:
    """带 pattern 的 must 规则做字面判定（forbid=命中 / require=缺失）——
    字面命中不等于语义违规（单字 pattern 会命中"天色/地面"），结果一律「待语义复核」"""
    import re as _re
    pattern = str(rule.get("pattern", "")).strip()
    mode = str(rule.get("mode", "forbid")).strip() or "forbid"
    try:
        hit = bool(_re.search(pattern, prose))
    except _re.error:
        return {}
    if mode == "forbid" and hit:
        return {"rule": rule.get("rule", ""), "result": "待语义复核",
                "detail": "禁则 pattern 命中（字面命中≠语义违规，须人工/强模型复核）"}
    if mode == "require" and not hit:
        return {"rule": rule.get("rule", ""), "result": "待语义复核",
                "detail": "必需要素缺失（字面未命中，可能是同义表达）"}
    return {}


def _prev_seen_violations(proj: str, num: int) -> dict:
    """跨章台账：此前各章清算已记录的 violation quote → 章号。
    同一 quote 再次出现 = 自创被后续章节固化引用，审计中升级为「未闭环」。"""
    seen = {}
    tdir = os.path.join(proj, "追踪")
    if not os.path.isdir(tdir):
        return seen
    for fn in os.listdir(tdir):
        m = re.match(r"设定清算_第(\d+)\.json", fn)
        if not m:
            continue
        prev_num = int(m.group(1))
        if prev_num >= num:
            continue
        try:
            with open(os.path.join(tdir, fn), encoding="utf-8") as f:
                for v in json.load(f).get("violations", []):
                    q = str(v.get("quote", "")).strip()
                    if q:
                        seen[q] = prev_num
        except Exception:  # noqa: BLE001
            continue
    return seen
