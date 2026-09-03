# -*- coding: utf-8 -*-
"""L0 确定性预检 + 引证验真（共享层：双端逐字节镜像，禁引 Qt/app 依赖）

零 LLM 成本：
- verify_quote：审校【原文引证】代码验真（规范化子串 + 锚点窗口模糊比）
- scan_chapter：五项确定性检查 → [L0-*] findings，可注入审校 prompt、可进修复环
  1 专名错写（角色表名在正文中被写成差一字的名字）
  2 跨章 5-gram 复读（纯汉字 5 字串与上一章重复过多）
  3 数值账（余额/剩余类语境词+数字，与台账文本比对，上下文窗口法非裸集合差）
  4 章末钩子形态（弱钩：心理宣言/计划陈述收尾）
  5 题材禁词（预设硬性禁词命中）

设计纪律：宁缺勿滥——无法确证的疑点标 advisory 交给 LLM 审校裁决，
只有可指认的确定性错误才标 blocking。
"""
import difflib
import re

_CJK = "\u4e00-\u9fff"
# 通用题材禁词（非修仙/玄幻类书籍出现即违规；移植 TUI evals/l0_scan）
GENERIC_FORBIDDEN = ["修仙", "一炷香", "十息", "半炷香", "金丹", "筑基", "练气期"]
_NUM_CTX_RE = re.compile(
    r"(余额|剩余|当前|现存|已消耗|已用|还有|仅剩|共|总)\s*[为是：:至]?\s*(\d+(?:\.\d+)?)")

# 弱钩收尾模式（对应写作硬约束 6：禁止心理宣言/计划陈述/纯过渡收尾）
_WEAK_HOOK_RE = re.compile(
    r"(心中暗想|暗暗发誓|发誓|一定要|明日再|明天再|握紧了?拳|望向?着?远方|长舒一?口气|"
    r"故事.{0,4}(才|刚)(刚开始|开始)|一切.{0,4}(才|刚)开始)")


def _norm(s: str) -> str:
    """规范化：仅保留汉字/字母/数字（去空白、标点、引号，验真两侧同规则）"""
    return "".join(ch for ch in (s or "") if ch.isalnum())


def verify_quote(prose: str, quote: str, min_len: int = 6, fuzz: float = 0.8) -> tuple:
    """验真【原文引证】是否真实存在于正文 → (是否通过, 说明)

    先规范化精确包含；不中再以引证首/尾/中段 4 字为锚点在正文开窗模糊比，
    取与引证等长、且包含锚点的窗口逐一比较，最高相似度 ≥fuzz 视为通过
    （容忍记错一两个字）。引证过短直接不通过。
    """
    q = _norm(quote)
    if len(q) < min_len:
        return (False, "引证过短或为空")
    p = _norm(prose or "")
    if q in p:
        return (True, "")
    best = 0.0
    L = len(q)
    seeds = {q[:4], q[-4:], q[L // 2:L // 2 + 4]}
    for seed in seeds:
        if len(seed) < 3:
            continue
        start = 0
        while True:
            i = p.find(seed, start)
            if i < 0:
                break
            # 与引证等长的窗口，锚点须落在窗内：窗口起点 ∈ [i-(L-len(seed)), i]
            lo0 = max(0, i - (L - len(seed)))
            hi0 = min(i, max(0, len(p) - L))
            s0 = lo0
            while s0 <= hi0:
                win = p[s0:s0 + L]
                r = difflib.SequenceMatcher(None, q, win).ratio()
                if r > best:
                    best = r
                if best >= fuzz:
                    return (True, "")
                s0 += 1
            start = i + 1
    return (False, f"引证未在正文中找到（相似度 {best:.2f}）")


def _find_name_typos(prose: str, roster: list) -> list:
    """专名错写：角色表名未出现、但正文存在差一字的同长名字（排除名单内互撞）"""
    findings = []
    roster_set = set(roster)
    for name in roster:
        if len(name) < 2 or name in prose:
            continue
        seen = set()
        for i in range(len(prose) - len(name) + 1):
            win = prose[i:i + len(name)]
            if not re.fullmatch(rf"[{_CJK}]{{{len(name)}}}", win):
                continue
            if win in roster_set or win in seen:
                continue
            diff = sum(1 for a, b in zip(name, win) if a != b)
            if diff == 1:
                seen.add(win)
                ctx = prose[max(0, i - 12):i + len(name) + 12]
                findings.append({
                    "code": "L0-NAME", "level": "blocking",
                    "text": f"疑似角色名错写：角色表为「{name}」，正文写作「{win}」",
                    "quote": ctx})
        if len(seen) >= 2:
            break
    return findings


def _count_shared_5grams(curr: str, prev: str) -> tuple:
    """纯汉字 5-gram 跨章重复：返回 (重复个数, 示例列表)"""
    if not curr or not prev:
        return (0, [])
    pat = re.compile(rf"[{_CJK}]{{5}}")
    c5 = set(m.group(0) for m in pat.finditer(curr))
    p5 = set(m.group(0) for m in pat.finditer(prev))
    shared = sorted(c5 & p5)
    return (len(shared), shared[:3])


_NUM_MISMATCH_MAX = 5


def _check_ledger_numbers(prose: str, ledger_text: str) -> list:
    """数值账：台账中「余额/剩余…」语境数字与正文同语境词数字不一致 → advisory

    上下文窗口法（非裸集合差）：只比较同一语境词旁的数字。
    账目允许章内合法变动，仅存疑标记，交 LLM 终裁。
    """
    if not ledger_text:
        return []
    ledger_hits = {}
    for word, num in _NUM_CTX_RE.findall(ledger_text):
        ledger_hits.setdefault(word, set()).add(num)
    findings = []
    seen = set()
    for word, num in _NUM_CTX_RE.findall(prose or ""):
        for lnum in ledger_hits.get(word, ()):
            if num == lnum or (word, num, lnum) in seen:
                continue
            seen.add((word, num, lnum))
            m = re.search(rf"{word}\s*[为是：:至]?\s*{re.escape(num)}[^。\n]*。?", prose)
            ctx = m.group(0) if m else f"{word}…{num}"
            findings.append({
                "code": "L0-NUM", "level": "advisory",
                "text": f"数值账存疑：台账「{word}」为 {lnum}，正文写作 {num}（允许章内合法变动，请核对）",
                "quote": ctx[:60]})
    return findings[:_NUM_MISMATCH_MAX]


def classify_hook(text: str) -> str:
    """章末钩子 5 分类（末 200 字关键词匹配，移植 TUI evals/l0_scan）"""
    t = text[-200:] if len(text) > 200 else text
    if re.search(r"(电话|短信|铃响|消息|微信|手机|呼叫)", t):
        return "remote_msg"
    if re.search(r"(\".*\".*问|缓缓.*转|从背后|轻轻.*靠|从口袋|遗物|玉佩|包裹)", t):
        return "object_motion"
    if re.search(r"(身后|门外|窗边|从不远处|脚步声|门被)", t):
        return "other_action"
    if re.search(r"(还不是|谁会|为什么|他为什么|这件事|这个人|如果|只是开始|心里知道|他心里|这背后)", t):
        return "info_gap"
    if re.search(r"(锁定|面对|指向|出口|出手|面带|一下子)", t):
        return "confrontation"
    return "unknown"


def scan_chapter(prose: str, prev_prose: str = "", roster: list = None,
                 ledger_text: str = "", forbidden_words: list = None) -> dict:
    """单章 L0 确定性扫描 → {"findings": [...], "hook_type": str}

    findings 项：{code, level: blocking/advisory, text, quote}
    """
    prose = prose or ""
    findings = []
    # 1 专名错写
    if roster:
        findings.extend(_find_name_typos(prose, roster))
    # 2 跨章复读
    n_shared, samples = _count_shared_5grams(prose, prev_prose or "")
    if n_shared >= 15:
        findings.append({
            "code": "L0-REPEAT", "level": "blocking",
            "text": f"与上一章存在 {n_shared} 处 5 字连续复读（示例：{'、'.join(samples)}），疑似复制段落",
            "quote": samples[0] if samples else ""})
    elif n_shared >= 6:
        findings.append({
            "code": "L0-REPEAT", "level": "advisory",
            "text": f"与上一章存在 {n_shared} 处 5 字连续重复（示例：{'、'.join(samples)}）",
            "quote": samples[0] if samples else ""})
    # 3 数值账
    findings.extend(_check_ledger_numbers(prose, ledger_text))
    # 4 章末弱钩
    tail = prose[-120:]
    if tail and _WEAK_HOOK_RE.search(tail):
        findings.append({
            "code": "L0-HOOK", "level": "blocking",
            "text": "章末疑似心理宣言/计划陈述式弱钩收尾（违反章末钩子铁律）",
            "quote": tail[-40:]})
    # 5 题材禁词
    for w in (forbidden_words or []):
        if w and w in prose:
            findings.append({
                "code": "L0-TERM", "level": "blocking",
                "text": f"题材禁词命中：「{w}」", "quote": ""})
            break
    return {"findings": findings, "hook_type": classify_hook(prose)}


def format_scan_block(report: dict, max_chars: int = 600) -> str:
    """L0 结果 → 审校 prompt 注入块（空结果回退占位）"""
    fs = (report or {}).get("findings") or []
    if not fs:
        return "（本地确定性预检未发现问题）"
    lines = []
    total = 0
    for f in fs:
        q = f"｜原文：{f['quote']}" if f.get("quote") else ""
        line = f"- [{f['level'].upper()}][{f['code']}] {f['text']}{q}"
        if total + len(line) > max_chars:
            lines.append("…（预检项截断）")
            break
        lines.append(line)
        total += len(line)
    return ("以下为本地确定性预检（零 LLM）发现，请逐条裁决：属实保留为对应级别，"
            "确属误报可附一句理由降级为建议项，但不得无理由豁免。\n" + "\n".join(lines))
