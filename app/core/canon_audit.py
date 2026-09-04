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

from .. import mustscan
from .. import project
from . import state as st

logger = logging.getLogger("qianbi.canon")

AUDIT_PROMPT = """你是网文世界观的合规审校。下面是一部小说的【设定底册条目名】与【第 {num} 章正文】。
找出正文中的世界观问题，每条独立说明，禁止复用同一句评语：
1. violations：与底册冲突的陈述，或底册无依据的自创体系/机构/货币/职业/丹药名。
   - quote：正文原句（≤40 字）；why：针对该句的具体说明（每条都不同）；
   - canon_ref：底册条目名（给不出写「底册无此条」）；severity：硬伤/软伤。
2. adoptions：正文新出现、与底册不冲突、值得收编进世界书的自创专名。
   - name/cat/desc（desc ≤80 字）。
没有问题就返回空数组。只输出 JSON：
{{"violations": [{{"quote":"","why":"","canon_ref":"","severity":""}}],
  "adoptions": [{{"name":"","cat":"","desc":""}}]}}

【底册条目名】
{names}

【第 {num} 章正文】
{prose}
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
    from .config import SLOT_REVIEW
    from .llm.client import LLMClient
    conn = project_slot_connection(cfg, SLOT_REVIEW)
    if strict:
        pro = next((c for c in cfg.get("connections", [])
                    if c.get("model", "").endswith("pro")), None)
        if pro:
            conn = pro
    from .llm.client import LLMClient as LC
    return LC.from_connection(conn or {}, max_retries=1, slot="review")


def project_slot_connection(cfg: dict, slot: str) -> dict:
    from . import config as cfg_mod
    return cfg_mod.slot_connection(cfg, slot)


def audit_chapter(proj: str, num: int, prose: str, cfg: dict, router=None) -> dict:
    """本章设定清算。产物：追踪/设定清算_第NNN.json；返回同构 dict（含 pattern_hits）。"""
    ledger_path = os.path.join(proj, "追踪", "拆解清单.json")
    ledger_entries = []
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, encoding="utf-8") as f:
                ledger_entries = json.load(f).get("entries", [])
        except Exception:  # noqa: BLE001
            ledger_entries = []
    names = "、".join(str(e.get("name", "")) for e in ledger_entries if e.get("name"))
    prompt = AUDIT_PROMPT.format(num=num, names=names or "（无）", prose=prose[:6000])

    from .llm.client import LLMClient
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
    if not isinstance(data, dict):
        data = {"violations": [], "adoptions": [],
                "error": f"清算解析失败：{last_err or '重复退化'}（原始输出需人工查看）"}

    violations = data.get("violations") or []
    ledger_all = names + " " + json.dumps(ledger_entries, ensure_ascii=False)
    for v in violations:
        ref = str(v.get("canon_ref", ""))
        probe = ref if ref and ref != "底册无此条" else str(v.get("why", ""))[:12]
        v["in_ledger"] = bool(probe) and probe in ledger_all

    pattern_hits = [{"rule": r.get("rule", ""), "findings": f}
                    for r in _must_rules_with_patterns(proj)
                    for f in [_pattern_check(proj, num, prose, r)] if f]
    report = {"num": num, "chars": len(prose),
              "violations": violations,
              "adoptions": data.get("adoptions") or [],
              "pattern_hits": pattern_hits,
              "error": data.get("error", "")}
    out = os.path.join(proj, "追踪", "设定清算_第%03d.json" % num)
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("设定清算落盘失败：%s", e)
    return report


def _strict_conn(cfg: dict) -> dict:
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


def _pattern_check(proj: str, num: int, prose: str, rule: dict) -> dict:
    """带 pattern 的 must 规则做确定性判定（forbid=命中即违规 / require=缺失即违规）"""
    import re as _re
    pattern = str(rule.get("pattern", "")).strip()
    mode = str(rule.get("mode", "forbid")).strip() or "forbid"
    try:
        hit = bool(_re.search(pattern, prose))
    except _re.error:
        return {}
    if mode == "forbid" and hit:
        return {"rule": rule.get("rule", ""), "result": "违规", "detail": "禁则 pattern 命中"}
    if mode == "require" and not hit:
        return {"rule": rule.get("rule", ""), "result": "违规", "detail": "必需要素缺失"}
    return {}
