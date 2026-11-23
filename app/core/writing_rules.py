# -*- coding: utf-8 -*-
"""写作规约反馈沉淀（D4，0.20.3；模式源 easy-writing writingRules，t5_ainw_easy §2.3/§3-H）

用户在共写审校/对话里给出的修改反馈（拒绝原因、风格要求）沉淀为持久「写作规约」，
之后每章生成时由状态卡以最高优先级注入——让「改过的错」不再犯（easy-writing 的
「反馈→writingRules→每章材料最高优先键注入」闭环重写落地）。

- 存储：sidecar `追踪/写作规约.json`——{version:1, rules:[{id, content, source_ch,
  created_ts, hits, enabled}], archived:[…], next_id:int}；一行一条纪律由
  MAX_RULE_LEN 入库截断保障（用户可读可手改，手改超长条目读入不截）。
- add_rule 去重：内容归一化（fact_ledger.normalize 思路：NFKC+去全部空白+剥
  引号/破折号类符号）精确相等，或与既有条目唯一互相包含（tracking_store.
  _match_row 同口径：歧义多命中视为查无此行，不臆造合并）→ 更新既有条目而非新增。
- 上限 MAX_RULES=100：新增超额时按 hits 升序（并列取创建更早者）淘汰最久未命中
  者进 archived——归档不删除（可审计可捞回）；archived 再按 MAX_ARCHIVED 截尾。
- 注入：state_card「写作规约(最高优先级)」段（P0 之后，prio=0 永不裁——预算不够
  先裁设定不裁规约的「优先级最高」语义）；enabled 规则按入库序全文注入，注入计数
  回写 hits（mark_hits）。off 开关 writing.writing_rules_enabled（缺省 on，
  satisfaction_ledger_enabled 同款口径）→ 段恒空，卡片输出与无规约逐字一致。
- 纯本地零 LLM；IO 全 fail-open（缺失/损坏按空规约处理，读路径零副作用——
  setting_ledger 同款纪律；写失败不抛，由调用方 toast 兜底）。
TODO(接线批)：bridge.addWritingRule 槽与 CwDialogueDock 报告区按钮本卡已接；
prompts/ 装配点不碰（动态文本不进基线防漂移体系）；流水线档（stages 轨道）注入
为后续接线，本卡只覆盖共写轨道状态卡消费路径。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import unicodedata

RULES_SIDECAR = "写作规约"
MAX_RULES = 100              # 活跃规约上限（easy-writing 纯追加不做上限会吃预算，这里硬顶）
MAX_RULE_LEN = 200           # 单条入库截断（一行一条纪律；状态卡按整条注入）
ARCHIVE_CAP = 2 * MAX_RULES  # 归档截尾（防 add/evict 循环无限膨胀）
CARD_RULE_CAP = 20           # 单张状态卡最多注入条数（防规约涨满吃穿 12KB 卡）
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# 归一化剥离集：引号/书名号/破折号/省略号/句读标点/空白后的标点噪声
# （fact_ledger.normalize 思路 + 反馈句特有的句读差异救回：句号逗号全半角互换）
_NOISE_CHARS = ("“”‘’\"'《》「」『』()（）【】…—–-＿_~·"
                "。，、；：！？,.;:!?")


def _now_str() -> str:
    return datetime.datetime.now().strftime(_TS_FORMAT)


def normalize(s: str) -> str:
    """归一化：NFKC + 去全部空白 + 剥引号/书名号/破折号/句读标点。

    去重比较口径（fact_ledger.normalize 同思路）：全半角引号互换、多余空差、
    句读标点差异在本级被救回；真正的改写（字面不同）仍视为新规约。
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", "", s)
    return s.translate({ord(c): None for c in _NOISE_CHARS})


def _rules_path(proj: str) -> str:
    return os.path.join(proj, "追踪", "%s.json" % RULES_SIDECAR)


def _norm_entry(e) -> dict | None:
    """单条形态归一（fail-open）：坏条目丢弃，不炸整册"""
    if not isinstance(e, dict):
        return None
    content = str(e.get("content") or "").strip()
    if not content:
        return None
    hits = e.get("hits")
    src = e.get("source_ch")
    return {"id": str(e.get("id") or "").strip(),
            "content": content,
            "source_ch": int(src) if isinstance(src, int) else None,
            "created_ts": str(e.get("created_ts") or "").strip(),
            "hits": hits if isinstance(hits, int) and hits >= 0 else 0,
            "enabled": bool(e.get("enabled", True))}


def load_rules(proj: str) -> dict:
    """写作规约 sidecar（缺失/损坏 → 空册；读路径零副作用，不回写）。

    顺带形态归一：坏条目丢弃；缺失/重复 id 就地补号（保序，后到者让先到者）。
    """
    try:
        with open(_rules_path(proj), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    out = {"version": 1, "rules": [], "archived": [], "next_id": 1}
    if not isinstance(data, dict):
        return out
    for key in ("rules", "archived"):
        seen = set()
        items = []
        for e in data.get(key) or []:
            row = _norm_entry(e)
            if row is None:
                continue
            if not row["id"] or row["id"] in seen:
                row["id"] = "R%03d" % out["next_id"]
                while row["id"] in seen:
                    out["next_id"] += 1
                    row["id"] = "R%03d" % out["next_id"]
            seen.add(row["id"])
            items.append(row)
        out[key] = items
    nid = data.get("next_id")
    if isinstance(nid, int) and nid >= 1:
        out["next_id"] = nid
    # 补号/手删后自愈：next_id 至少越过现存最大数字 id（防 add_rule 撞号）
    nums = [int(r["id"][1:]) for r in out["rules"] + out["archived"]
            if r["id"].startswith("R") and r["id"][1:].isdigit()]
    if nums:
        out["next_id"] = max(out["next_id"], max(nums) + 1)
    return out


def _save_rules(proj: str, data: dict) -> None:
    data["version"] = 1
    path = _rules_path(proj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _find_similar(rules: list, key: str):
    """归一化精确相等 → 唯一互相包含（歧义多命中=None，不臆造合并）。

    key 为空（内容全是标点噪声）→ None：按新条目落库，绝不静默吞并。
    """
    if not key:
        return None
    for r in rules:
        if normalize(r["content"]) == key:
            return r
    hits = [r for r in rules
            if key and (key in normalize(r["content"])
                        or normalize(r["content"]) in key)]
    return hits[0] if len(hits) == 1 else None


def add_rule(proj: str, content: str, source_ch: int | None = None) -> dict | None:
    """沉淀一条写作规约（去重：归一化相似则更新既有条目而非新增）。

    Returns: {"rule": 落库条目, "created": 是否新建, "evicted": [被淘汰条目]}
    content 空白 → None（no-op）；入库按 MAX_RULE_LEN 截断；更新既有条目时刷新
    表述/来源章/时间并重新启用（作者重提=仍然在意）。
    """
    content = str(content or "").strip()
    if not content:
        return None
    content = content[:MAX_RULE_LEN]
    data = load_rules(proj)
    rules = data["rules"]
    similar = _find_similar(rules, normalize(content))
    evicted = []
    if similar is not None:
        similar["content"] = content
        similar["source_ch"] = int(source_ch) if isinstance(source_ch, int) else None
        similar["created_ts"] = _now_str()
        similar["enabled"] = True
        rule = similar
        created = False
    else:
        rule = {"id": "R%03d" % data["next_id"], "content": content,
                "source_ch": int(source_ch) if isinstance(source_ch, int) else None,
                "created_ts": _now_str(), "hits": 0, "enabled": True}
        data["next_id"] += 1
        rules.append(rule)
        created = True
        if len(rules) > MAX_RULES:
            victim = min(rules, key=lambda r: (r["hits"], r["created_ts"], r["id"]))
            rules.remove(victim)
            data["archived"].append(victim)
            evicted.append(victim)
            del data["archived"][:-ARCHIVE_CAP]
    _save_rules(proj, data)
    return {"rule": rule, "created": created, "evicted": evicted}


def list_rules(proj: str, include_archived: bool = False) -> list:
    """规约清单（活跃序；include_archived=True 时归档条目附在 archived 键）"""
    data = load_rules(proj)
    out = [dict(r) for r in data["rules"]]
    if include_archived:
        out = {"rules": out, "archived": [dict(r) for r in data["archived"]]}
    return out


def mark_hits(proj: str, rule_ids: list) -> int:
    """命中计数回写（状态卡注入时调用；一次批量落盘）。返回实际更新条数"""
    ids = {str(i) for i in rule_ids or []}
    if not ids:
        return 0
    data = load_rules(proj)
    n = 0
    for r in data["rules"]:
        if r["id"] in ids:
            r["hits"] += 1
            n += 1
    if n:
        _save_rules(proj, data)
    return n


def set_enabled(proj: str, rule_id: str, enabled: bool) -> dict | None:
    """停用/重新启用一条规约（停用=保留不删：不注入不回写 hits，淘汰序里
    hits 冻结——停用条目依旧按既有 hits 参与最久未命中淘汰）。

    Returns: 更新后的条目；查无此 id → None
    """
    data = load_rules(proj)
    for r in data["rules"]:
        if r["id"] == str(rule_id):
            r["enabled"] = bool(enabled)
            _save_rules(proj, data)
            return dict(r)
    return None


def rules_enabled(cfg: dict | None) -> bool:
    """规约开关（writing.writing_rules_enabled，缺省 on）。

    off 时状态卡规约段恒空（注入与 hits 回写全惰性），输出与无规约逐字一致
    （satisfaction.ledger_enabled 同款口径；cfg 缺省形态见 app/config.py
    DEFAULT_CONFIG["writing"]，接线批登记出厂键）。
    """
    return bool(((cfg or {}).get("writing", {}) or {}).get("writing_rules_enabled", True))


def card_items(proj: str, cfg: dict | None = None, mark: bool = True) -> list:
    """状态卡注入条目：enabled 规则全文（入库序，前 CARD_RULE_CAP 条）。

    off 开关 → 恒 []（零注入零回写）；命中即回写 hits（mark=False 可只读，
    供预览/测试）。IO 全 fail-open，调用方（state_card）另有 try/except 兜底。
    """
    if not rules_enabled(cfg):
        return []
    rules = [r for r in load_rules(proj)["rules"] if r["enabled"]]
    picked = rules[:CARD_RULE_CAP]
    if mark and picked:
        try:
            mark_hits(proj, [r["id"] for r in picked])
        except Exception:  # noqa: BLE001
            pass
    return [r["content"] for r in picked]
