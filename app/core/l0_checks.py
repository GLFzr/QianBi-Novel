# -*- coding: utf-8 -*-
"""V5 · L0 账本对照（近零 API 成本的确定性预检，深度研究 §5）

三个探测器 + 一份审校证据块。定位（CRITIC 式外部反馈，Huang 2024：内在自校正退化）：
**证据定位器，不是独立裁决者**——产出违例与证据句注入审校 prompt，由审校终裁。

1. payoff_findings   爽点兑现：细纲 `- 爽点：` 承诺行 → 正文推迟语词典 + 关键词覆盖
                     （T4a 召回 0/2 的直接补位；defects.json 金标本就是这句）
2. clock_findings    钟点复现：细纲明写的钟点（含中文数字）必须在正文可复现
                     （T5 评委点名的"14:07 页痕被当 16:17"类穿帮的确定性前哨）
3. taboo_findings    禁止提前释放：细纲 `本章禁止提前释放` 引号关键词 → 正文确定性 grep
4. state_checklist   状态在场清单（证据供给，不判 fail）：角色状态里的未愈伤情/持续状态
                     → 提示审校逐条核对（"踝伤却写胳膊不方便"类漂移的对照材料）

全部纯正则/词典，CPU <0.5s/章，零网络零模型。任何解析失败返回空 finding（fail-open）。
"""
from __future__ import annotations

import re

# 推迟/搁置语式（封闭模板词典；T4a 的 B01 注入原句「算了吧……这笔账改日再算也不迟」全覆盖）
_DEFER_PHRASES = (
    "改日再说", "改日再算", "改天再说", "改天再算", "算了吧", "算了，", "先不",
    "回头再", "下次再", "且待", "来日再", "日后再", "以后再", "暂且不", "暂时不",
    "不急这一", "留到", "押后", "搁置",
)

# 状态在场关键词（未愈/持续性状态）
_OPEN_STATE_RE = re.compile(
    r"- \*\*[^*]*\*\*：.*?(?:伤|未愈|未消|白翳|瘸|盲|折|裂|肿|淤|残)"
    r"[^。；\n]*（第\d+章[^）]*）")
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_digits(text: str) -> str:
    """中文数字时刻 → 数字形（两点十七分 → 2点17分），用于钟点跨写法比对"""
    def conv(m: re.Match) -> str:
        s = m.group(0)
        h = re.match(r"[零一二两三四五六七八九十]+(?=点)", s)
        minute = re.search(r"点([零一二三四五六七八九十]+)分?", s)
        if not h:
            return s
        hs = h.group(0)
        total = 0
        if "十" in hs:
            parts = hs.split("十")
            tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
            ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
            total = tens * 10 + ones
        else:
            total = _CN_NUM.get(hs, -1)
        if total < 0:
            return s
        out = "%d点" % total
        if minute:
            ms = minute.group(1)
            m_total = 0
            if "十" in ms:
                parts = ms.split("十")
                tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
                ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
                m_total = tens * 10 + ones
            else:
                m_total = _CN_NUM.get(ms, 0)
            out += "%02d分" % m_total
        return out
    return re.sub(r"[零一二两三四五六七八九十]+点[零一二三四五六七八九十]*分?", conv, text)


def _outline_field(outline: str, field: str) -> str:
    m = re.search(r"^-\s*%s[：:]\s*(.+)$" % field, outline or "", re.M)
    return m.group(1).strip() if m else ""


def payoff_findings(outline: str, prose: str) -> list:
    """爽点兑现检查：唯一确定性信号是**推迟语式**（B01 金标）；转述式兑现的覆盖
    率启发式已证实误报（"拍在桌上/态度反转"对不上承诺原文），不作裁决信号——
    承诺行由 build_v5_block 作为上下文供给审校。"""
    promise = _outline_field(outline, "爽点")
    if not promise or "无显性爽点" in promise or "无爽点" in promise:
        return []
    findings = []
    for p in _DEFER_PHRASES:
        pos = prose.find(p)
        if pos >= 0:
            findings.append({
                "level": "fail候选", "check": "爽点兑现",
                "text": "细纲承诺爽点「%s…」，正文检出推迟语式「%s」。"
                        "按雷集金标（承诺爽点被推迟→必 fail）请裁决。"
                        % (promise[:40], p),
                "quote": prose[max(0, pos - 20):pos + len(p) + 20],
            })
            break
    return findings


def payoff_promise(outline: str) -> str:
    """细纲爽点承诺行（供给审校做上下文；无承诺返回空）"""
    p = _outline_field(outline, "爽点")
    if not p or "无显性爽点" in p or "无爽点" in p:
        return ""
    return p


def clock_findings(outline: str, prose: str) -> list:
    """钟点复现：细纲明写的数字/中文钟点必须能在正文（跨写法归一后）找到"""
    findings = []
    o = _cn_to_digits(outline or "")
    p_norm = _cn_to_digits(prose or "")
    stamps = set(re.findall(r"[01]?\d点[0-5]\d分|[01]?\d点[0-5]?\d?分?|"
                            r"[01]?\d[：:][0-5]\d", o))
    for stamp in sorted(stamps):
        if len(stamp) < 3:
            continue
        if stamp not in p_norm and stamp.replace("点", ":") not in p_norm:
            findings.append({
                "level": "核对", "check": "钟点复现",
                "text": "细纲明写钟点「%s」未在正文复现（含中文数字归一后）——"
                        "若正文改了时间，请确认与前文时间线不冲突。" % stamp,
                "quote": "",
            })
    return findings


def taboo_findings(outline: str, prose: str) -> list:
    """禁止提前释放：细纲引号关键词在正文出现 = 确定性违例"""
    line = _outline_field(outline, "本章禁止提前释放")
    if not line:
        return []
    taboos = re.findall(r"[「“']([^」”']{2,12})[」”']", line)
    findings = []
    for t in taboos:
        pos = (prose or "").find(t)
        if pos >= 0:
            findings.append({
                "level": "fail候选", "check": "禁止提前释放",
                "text": "细纲明令禁止提前释放的关键词「%s」出现在正文（确定性命中）。" % t,
                "quote": prose[max(0, pos - 20):pos + len(t) + 20],
            })
    return findings


def state_checklist(states_text: str) -> list:
    """状态在场清单（证据供给）：未愈伤情/持续状态 → 审校对照清单（不判 fail）"""
    items = []
    cur_name = ""
    for line in (states_text or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            cur_name = m.group(1).strip()
        for fm in _OPEN_STATE_RE.finditer(line):
            items.append("%s：%s" % (cur_name or "（未具名）", fm.group(0).lstrip("- ")))
    return items


def build_v5_block(proj, num: int, prose: str,
                   read_outline=None, read_states=None) -> str:
    """组装 V5 账本对照块（注入 review_l0_block 的尾部；≤1.2k chars 预算）"""
    try:
        outline = (read_outline or (lambda: ""))()
        states = (read_states or (lambda: ""))()
        findings = (payoff_findings(outline, prose) + clock_findings(outline, prose)
                    + taboo_findings(outline, prose))
        checklist = state_checklist(states)
        promise = payoff_promise(outline)
        if not findings and not checklist and not promise:
            return ""
        out = ["【V5 账本对照·第%d章（程序确定性预检，逐条裁决，不得无视）】" % num]
        if promise:
            out.append("- [细纲爽点承诺] %s" % promise[:120])
        for f in findings[:6]:
            out.append("- [%s|%s] %s%s" % (f["level"], f["check"], f["text"],
                                           ("（原文：%s…）" % f["quote"][:40]) if f["quote"] else ""))
        if checklist:
            out.append("- [在场状态清单] 本章涉及以下角色行动时逐条核对（漂移即判 D_PLOT）：")
            out.extend("  · %s" % c[:90] for c in checklist[:6])
        return "\n".join(out)[:1200]
    except Exception:  # noqa: BLE001
        return ""   # fail-open：预检绝不阻断流水线
