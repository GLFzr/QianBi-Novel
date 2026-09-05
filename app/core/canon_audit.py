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
   - quote：正文原句（≤40 字）；why：针对该句的具体说明（每条都不同）；
   - canon_ref：底册条目名或约束条款名（给不出写「底册无此条」）；severity：硬伤/软伤。
2. adoptions：正文新出现、与底册不冲突、值得收编进世界书的自创专名。
   - name/cat/desc（desc ≤80 字）。
   **收录下限**：本章全部新出场人物、新物证/关键道具、新地点/机构必须逐条收录，不许遗漏。
3. ledger_updates：本章为全书连续性台账新增/变更的事实——
   人物（出场者及其本章末状态）、物件（新物证/关键道具及其位置与状态）、
   制度（本章援引或新立的规矩）、时间（本章故事内日期/时段；若正文出现「三日后」「初五」等历法表述，必须原样写进时间字段）。
没有问题就返回空数组。只输出 JSON：
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


def audit_chapter(proj: str, num: int, prose: str, cfg: dict, router=None) -> dict:
    """本章设定清算。产物：追踪/设定清算_第NNN.json；返回同构 dict（含 pattern_hits）。"""
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
    prompt = AUDIT_PROMPT.format(num=num, names=names or "（无）",
                                project_header=project_header(proj),
                                authorized="、".join(authorized) or "（无）",
                                constraints_block=constraints_block(proj),
                                ledger_block=ledger_block(proj),
                                outline_brief=outline_doc[:2000] or "（无细纲）",
                                prev_ending=prev_ending,
                                next_opening=next_opening,
                                prose=prose[:6000])

    client = _client_for(cfg, router)
    data, last_err = None, ""
    for attempt, temp in enumerate((0.2, 0.35)):
        try:
            parts = []
            client.chat_stream(prompt, temperature=temp, phase="canon_audit",
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
        # 退化/解析失败 → 升 pro 再试一次（F1：严格判定不许 flash 单飞）
        try:
            client = LLMClient.from_connection(_strict_conn(cfg), max_retries=1, slot="review")
        except Exception:  # noqa: BLE001
            pass
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
