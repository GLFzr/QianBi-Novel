# -*- coding: utf-8 -*-
r"""正则 must 契约的确定性检查（零 LLM）

契约目前只在「正文生成」和「终审」两个端点注入 prompt，中间三次整章重写
（扩写 / 压缩 / 去味改写）不带契约——模型为凑字数新写的句子、为压缩删掉的
段落，都可能悄悄破掉 must 规则，只能等终审概率性地抓。本模块提供确定性那一层。

诚实边界（决定了这里能判什么、不能判什么）：
- **只有 pattern 非空的规则可判**。绝大多数 must 是自然语言句子（「改命必须索回
  代价」），机器无从判定，一律留在 prompt 注入 + LLM 审校。拿 rule 文本去
  re.compile 是错的：那是整句话，不是模式。
- **极性必须由作者显式声明**。`禁止三连感叹：`!{3,}`` 与 `必须有数字：`\d+``
  对机器完全同形，靠中文措辞推断不可靠。缺省 forbid（命中即违规），因为
  forbid 不会造成假阻断；require 判不动只漏报，故其违规一律降 advisory。
- 沿用 scan.py 的纪律：无法确证一律 advisory 交 LLM，只有可指认的确定性错误
  才标 blocking。

finding 形状与 scan.py 同构：{code, level: blocking/advisory, text, quote}，
quote 为实际命中片段，可被 scan.verify_quote 验真，因此能直接进修复环。
"""
import re

_CODE = "L0-MUST"
_PROSE_WINDOW = 8000      # 只扫前 8000 字：限制最坏情况回溯成本
_PATTERN_MAX = 200        # 超长 pattern 多半是写坏了或在做灾难性回溯
_QUOTE_MAX = 40


def _finding(rule: dict, level: str, quote: str, note: str = "") -> dict:
    text = "正则 must 契约命中：%s" % (rule.get("rule") or rule.get("pattern") or "?")
    if note:
        text += "（%s）" % note
    return {"code": _CODE, "level": level, "text": text[:300],
            "quote": (quote or "")[:_QUOTE_MAX],
            "pattern": rule.get("pattern") or "", "mode": rule.get("mode") or "forbid"}


def check_patterns(prose: str, rules: list) -> list:
    """按规则的 pattern 确定性地扫正文 → findings（无 pattern 的规则直接跳过）"""
    prose = prose or ""
    if not prose:
        return []
    hay = prose[-_PROSE_WINDOW:] if len(prose) > _PROSE_WINDOW else prose
    out = []
    for r in rules or []:
        pat = (r.get("pattern") or "").strip()
        if not pat:
            continue                       # 自然语言规则：交 LLM，不在这里判
        if len(pat) > _PATTERN_MAX:
            out.append(_finding(r, "advisory", "", "模式过长，未做确定性判定"))
            continue
        try:
            rx = re.compile(pat)
        except re.error as e:
            # 规则写坏是作者的配置问题，不该变成流水线的阻断
            out.append(_finding(r, "advisory", "", "正则不可编译：%s" % (e.msg or e)))
            continue
        m = rx.search(hay)
        mode = r.get("mode") or "forbid"
        if mode == "require":
            if not m:
                out.append(_finding(r, "advisory", "", "要求出现的模式未命中"))
        elif m:
            out.append(_finding(r, "blocking", m.group(0)))
    return out


def violation_keys(findings: list) -> set:
    """违规集合指纹，用于比对「某步重写是否新引入了违规」"""
    return {(f.get("pattern"), f.get("mode"), f.get("level")) for f in findings or []}


def scan_proj(proj: str, prose: str, levels: tuple = ("must",)) -> list:
    """从本书 设定/正则.md 取规则并做确定性检查（levels 过滤在解析结果上做）"""
    from app import project
    rules = project.regex_rules(proj, "logic")
    if levels:
        rules = [r for r in rules if r.get("level") in levels]
    return check_patterns(prose, rules)


def format_must_findings(findings: list, max_chars: int = 600) -> str:
    """findings → prompt 注入块（空结果回退占位；整行取舍，不留半句）"""
    fs = findings or []
    if not fs:
        return "（本地正则契约检查未发现问题）"
    lines, total = [], 0
    for f in fs:
        q = "｜原文：%s" % f["quote"] if f.get("quote") else ""
        line = "- [%s][%s] %s%s" % (f["level"].upper(), f["code"], f["text"], q)
        if total + len(line) + 1 > max_chars:
            lines.append("- …另有 %d 条未列出" % (len(fs) - len(lines)))
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def contract_precheck(proj: str, num: int, prose: str) -> tuple:
    """锁定/审校前置的确定性契约闸门 → (items, blocking, verdict)

    与 gates.word_count_precheck 同款契约：本函数不自己拦，只合成与审校 v2
    item 同构的结果，由调用方决定短路（跳过审校 LLM / 发 lockBlocked / 强锁留痕）。
    放在本模块而非 gates.py：gates.py 与 TUI 逐字节同源，本模块 GUI-only。

    只有 blocking 参与闸门。advisory 的含义就是「判不准」，对不确定的东西亮红
    会制造假阻断，最终把人训练成无脑点强锁——那这套机制就白做了。
    """
    fs = [f for f in scan_proj(proj, prose) if f["level"] == "blocking"]
    if not fs:
        return ([], [], "")
    items = [{"dim": "D_PLOT", "level": "fail", "quote": f.get("quote") or "",
              "text": "[正则must] " + f["text"], "root_layer": "ROOT_REGEX", "line": ""}
             for f in fs]
    blocking = [it["text"] for it in items]
    return (items, blocking, "REJECT")
