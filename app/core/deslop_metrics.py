# -*- coding: utf-8 -*-
"""deslop 度量层（卡6S）：AID 特征密度 / 分规则命中表 / 节奏 / 连接度

纯 stdlib、零 token、确定性——文本进 dict 出；findings 由 deslop.scan_text 产出，
本模块只聚合不扫描。四组指标（w3_deslop §2；蓝图口径，非第三方检测器标定）：

1. aid          AI 味特征密度 = Σ(命中数×权重)/千字；权重 blocking=3 / advisory=1
                可配置。语义是「读感代理指标」，不承诺对外检测率（诚实边界——
                对外只走送检包+人工回填，绝不编数字）。
2. by_rule      分规则命中表：{rule: {count, per_kilo, level, review}}。聚合底座是
                summarize_findings（卡6S 将其从死函数复活为本表基础）；
                review = mechanical（词表/标点/长度统计等表面模式）|
                semantic（句式修辞关系判断），28 个 rule id 全登记。
3. rhythm       句长均值/方差、段长均值/方差、单句短段占比、连续短段最大游程
                （只度量不强改——D5/D8 的统计底座，不设规则）。
4. connectivity 功能词/千字、白话连接词/千字、≥30 字承接句占比
                （过碎文本在这里现形，防「改干净了也改碎了」）。

附 special（专项密度）与 guard（改写质量护栏；需要改前文本的项由
compute_guard 单独计算，卡7 的 new_must_violations 同走 guard 出口）。

S6a 下沉：本模块原在 app-top（app/deslop_metrics.py），co_dialogue/stages 两个
core 消费方各自多背一条 core->app-top 上探边；度量层本是「文本进 dict 出」的纯
函数层（text_metrics 同款），落 core 后消费边转 core→core。随迁四件与扫描共用
的纯底座（QUOTE_EMPHASIS/GAZE_MARKERS/BRAKE_MARKERS/in_dialogue/
summarize_findings，原定义在 app/deslop.py——deslop 反向自本模块导入，特征
登记处单一真源，app-top→core 合法方向），本模块对 app 零依赖。
"""
import re

AID_WEIGHTS = {"blocking": 3.0, "advisory": 1.0}

# 28 个 rule id 的 mechanical/semantic 二轴登记（M 档新增规则必须补登记）
REVIEW_AXIS = {
    # 表面模式：词表 / 标点 / 长度统计
    "cliche-word": "mechanical", "em-dash": "mechanical", "daizhe-adverb": "mechanical",
    "prompting-colon": "mechanical", "simile-marker-density": "mechanical",
    "metaphor-density": "mechanical", "telling-cognition": "mechanical",
    "micro-action-tic": "mechanical", "dunhao-list-density": "mechanical",
    "period-stutter": "mechanical", "long-paragraph": "mechanical",
    "quote-emphasis": "mechanical", "gaze-density": "mechanical",
    "brake-sentence": "mechanical", "mengdi-density": "mechanical",
    "one-line-para": "mechanical", "stamp-para": "mechanical",
    "flat-voice": "mechanical",
    # 句式修辞关系：需要读上下文才能判
    "not-is-comparison": "semantic", "reverse-not-is": "semantic",
    "negation-parade": "semantic", "voice-contrast": "semantic",
    "trailer-ending": "semantic", "trailer-summary": "semantic",
    "fate-summary": "semantic", "abstract-summary-tic": "semantic",
    "reasoning-chain": "semantic", "brake-standalone-para": "semantic",
    # ---- C16b/C1a 增量 17 条（oh-story 11 条直译 + humanizer/R1-R6 移植）二轴登记
    # （对齐 oh-story REVIEW_CLASSES；无上游分类的按同族规则归类）----
    "negation-pair-tic": "semantic",        # 「没A，也没B」否定对偶（上游 semantic）
    "stock-reaction-tic": "semantic",       # 身体反应可能承担物理后果（上游 semantic）
    "action-list-tic": "semantic",          # 功能性动作编排可保留（上游 semantic）
    "system-notice-formality-tic": "semantic",   # 系统文本本可公文腔（上游 semantic）
    "overcompressed-prose-tic": "semantic", # 短段过密可能是节奏选择（上游 semantic）
    "low-connective-density-tic": "semantic",    # 连接词补不补看读感（上游 semantic）
    "formulaic-parallelism": "semantic",    # 工整并列可能承担辩解（上游 semantic）
    "cliche-density-tic": "mechanical",     # 固定词表密度（上游 mechanical）
    "forced-triad": "semantic",             # 三连同质与否需语义判（humanizer #6）
    "sentence-opening-run": "mechanical",   # 纯统计句首复读（humanizer #7）
    "idealized-persona-simile": "mechanical",    # 拟人化喻体词表（lieflat 7.3×）
    "adjacent-sentence-isomorph": "semantic",    # 结构同款需读语境（lieflat 2.0×）
    "zero-subject-comment": "mechanical",   # 词表+回指字面可判（lieflat 4.4×）
    "vague-rider": "mechanical",            # 空转伴随状语词表（humanizer #15）
    "closer-recap-tic": "semantic",         # 点题句复述判断（humanizer #2）
    "sendoff-para": "semantic",             # 送别段/升华段（humanizer #13）
    "recap-opening": "semantic",            # 章首复述前情（humanizer #26）
}

# 节奏统计口径
_SHORT_PARA_CHARS = 15          # ≤15 可见字 = 单句短段（与 deslop.one-line-para 同口径）
_LONG_SENT_CHARS = 30           # ≥30 可见字 = 承接句

# 连接度词表（白话连接词 + 汉语功能词；计数按子串出现次数）
_CONNECTORS = ("但是", "可是", "不过", "然而", "于是", "因此", "所以", "因为",
               "虽然", "然后", "接着", "而且", "况且", "其实", "毕竟", "反正",
               "总之", "也就是说", "这意味着", "换句话说")
_FUNC_WORDS = ("的", "地", "得", "了", "着", "是", "有", "在", "和", "与",
               "或", "但", "就", "都", "也", "很", "被", "把", "让", "使",
               "对", "向", "从", "到")
_SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")
_DIALOG_TAG_RE = re.compile(r"[「“][^」”]*[」”]\s*[，,]?\s*(?:他|她|我|它|两人|两人)?"
                            r"(?:低声|轻声|沉声|冷声|笑道|问道)?(?:说|道|问|答|喊|嚷|嘀咕|开口)")
_QUOTE_SPAN_RE = re.compile(r"[「“][^」”]+[」”]")

# ---- 与 deslop 扫描共用的纯底座（原定义在 app/deslop.py，S6a 随迁单一真源）----

# 引号强调滥用（叙述里短词加引号）
QUOTE_EMPHASIS = re.compile(r'[“"][^“”"\n]{1,4}[”"]')

# ---- 引号掩码基建（C16b/C1a，oh-story check-ai-patterns.js maskQuoted 直译）----
# 成对引号（台词/系统播报/弹幕/【】面板）字符对，mask_quoted / strip_quoted /
# quoted_ranges 共用一份来源。引号片段一律不跨行（字符类里排掉 \n）：正文漏一个
# 收引号很常见（多段台词只在末段收尾、全半角引号混用都会漏），若允许跨行配对，
# 一个未闭合的开引号会把后面成百上千字全算成「引号内」，把整段叙述静默豁免掉。
_QUOTE_PAIRS = [("「", "」"), ("『", "』"), ("【", "】"), ("“", "”"),
                ("‘", "’"), ('"', '"'), ("'", "'")]


def _quote_source(open_ch: str, close_ch: str) -> str:
    def esc(t: str) -> str:
        return t.replace("\\", "\\\\")
    return "%s[^%s\\n]*%s" % (esc(open_ch), esc(close_ch), esc(close_ch))


_QUOTE_SPAN_RES = [re.compile(_quote_source(o, c)) for o, c in _QUOTE_PAIRS]


def mask_quoted(text: str) -> str:
    """成对引号片段（含引号）替换为等长「？」占位：既豁免引号内台词/播报，又保住
    原文偏移量，供逐处规则定位与截取原文摘录（strip_quoted 会移位，不适合定位）。

    占位字符用「？」而不是「。」：占位既要截断各规则的 [^。！？!?…] 否定类
    （？与句号在每条规则的否定类里等效），又不能落在任何规则的接受位——句号占位
    会替 trailer-summary 的句末 [。！] 伪造出终止符。等长替换，偏移与摘录窗口不漂移。
    """
    out = text
    for pat in _QUOTE_SPAN_RES:
        out = pat.sub(lambda m: "？" * len(m.group(0)), out)
    return out


def strip_quoted(text: str) -> str:
    """去掉成对引号内的片段（台词/系统播报），只留引号外叙述。

    密度型规则的分母与命中计数用：纯对话/弹幕成片短句是体裁正常形态（豁免），
    但「叙述 + 引号内物件/短台词」混合行的引号外叙述仍参与统计。
    """
    out = text
    for pat in _QUOTE_SPAN_RES:
        out = pat.sub("", out)
    return out


def quoted_ranges(text: str) -> list:
    """引号内片段（含引号本身）的 [start, end) 区间列表（不跨行），供逐位置豁免判定。"""
    ranges = []
    for pat in _QUOTE_SPAN_RES:
        for m in pat.finditer(text):
            ranges.append((m.start(), m.end()))
    return ranges

# 视线词族（密度型，2026-08 真机语料分析：残留 AI 味第一名——凝视循环镜头单一）
GAZE_MARKERS = re.compile(r"盯着|看向|望向|注视|目光")

# 否定刹车句族（"没有动/没有回头/没有说话"——短促否定节奏指纹）
BRAKE_MARKERS = re.compile(r"没有[动说气回头停开口接答理翻]")


def in_dialogue(text: str, pos: int) -> bool:
    """判断位置是否在对话引号内（粗略：统计前面中文引号的开合）"""
    before = text[:pos]
    opens = before.count("“") + before.count("「")
    closes = before.count("”") + before.count("」")
    return opens > closes


def summarize_findings(findings: list) -> dict:
    """按 (rule, level) 聚合统计：{(rule, level): {rule, level, count, message, fix_hint}}

    卡6S 度量层已复活：compute_metrics 以本函数为分规则命中表的聚合底座
    （B1 死函数豁免登记随复活摘除）。S6a 起真身在本模块，app/deslop 反向导入
    转发（调用面不变）。
    """
    stats = {}
    for f in findings:
        key = (f.rule, f.level)
        if key not in stats:
            stats[key] = {"rule": f.rule, "level": f.level, "count": 0,
                          "message": f.message, "fix_hint": f.fix_hint}
        stats[key]["count"] += 1
    return stats


def visible_chars(text: str) -> int:
    """可见字数（与 project.count_chars 同口径：去空白与 markdown 标记）"""
    t = re.sub(r"\s+", "", text or "")
    t = re.sub(r"[#>*`\-\[\]()]", "", t)
    return len(t)


def _mean(nums):
    return sum(nums) / len(nums) if nums else 0.0


def _pvar(nums):
    """总体方差（D8 句长/段长方差）"""
    if not nums:
        return 0.0
    m = _mean(nums)
    return sum((x - m) ** 2 for x in nums) / len(nums)


def compute_metrics(text: str, findings: list, weights: dict = None) -> dict:
    """文本 + deslop 扫描 findings → 指标 dict（纯本地，不落盘）"""
    w = dict(AID_WEIGHTS)
    if weights:
        w.update(weights)
    chars = visible_chars(text)
    kilo = chars / 1000.0

    # 1) AID 特征密度
    aid_score = (sum(w.get(f.level, 1.0) for f in findings) / kilo) if kilo > 0 else 0.0

    # 2) 分规则命中表（复活 summarize_findings 作聚合底座）
    merged = {}
    for st in summarize_findings(findings or []).values():
        entry = merged.setdefault(st["rule"], {"count": 0, "level": "advisory",
                                               "review": REVIEW_AXIS.get(st["rule"],
                                                                         "mechanical")})
        entry["count"] += st["count"]
        if st["level"] == "blocking":
            entry["level"] = "blocking"
    by_rule = {rule: {"count": e["count"],
                      "per_kilo": round(e["count"] / kilo, 3) if kilo > 0 else 0.0,
                      "level": e["level"], "review": e["review"]}
               for rule, e in merged.items()}

    # 3) 节奏：句长/段长均值与方差、单句短段占比、连续短段最大游程
    sentences = [s for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]
    sent_lens = [visible_chars(s) for s in sentences]
    paras = [p for p in (text or "").splitlines() if p.strip()]
    para_lens = [visible_chars(p) for p in paras]
    short_flags = [n <= _SHORT_PARA_CHARS for n in para_lens]
    max_run = run = 0
    for flag in short_flags:
        run = run + 1 if flag else 0
        max_run = max(max_run, run)
    rhythm = {
        "sent_len_mean": round(_mean(sent_lens), 2),
        "sent_len_var": round(_pvar(sent_lens), 2),
        "para_len_mean": round(_mean(para_lens), 2),
        "para_len_var": round(_pvar(para_lens), 2),
        "short_para_ratio": round(sum(short_flags) / len(short_flags), 3) if short_flags else 0.0,
        "max_short_run": max_run,
    }

    # 4) 连接度：功能词/千字、白话连接词/千字、≥30 字承接句占比
    body = text or ""
    conn_hits = sum(body.count(wd) for wd in _CONNECTORS)
    func_hits = sum(body.count(wd) for wd in _FUNC_WORDS)
    long_sents = sum(1 for n in sent_lens if n >= _LONG_SENT_CHARS)
    connectivity = {
        "func_per_kilo": round(func_hits / kilo, 3) if kilo > 0 else 0.0,
        "conn_per_kilo": round(conn_hits / kilo, 3) if kilo > 0 else 0.0,
        "long_bridge_ratio": round(long_sents / len(sent_lens), 3) if sent_lens else 0.0,
    }

    # 专项密度（D1/D2/B6/C11 的读数，只进指标不设规则）
    gaze_hits = len(GAZE_MARKERS.findall(body))
    brake_hits = len(BRAKE_MARKERS.findall(body))
    quote_spans = _QUOTE_SPAN_RE.findall(body)
    tag_hits = len(_DIALOG_TAG_RE.findall(body))
    emph_hits = len([m for m in QUOTE_EMPHASIS.finditer(body)
                     if not in_dialogue(body, m.start())])
    special = {
        "dialog_tag_ratio": round(tag_hits / len(quote_spans), 3) if quote_spans else 0.0,
        "gaze_per_kilo": round(gaze_hits / kilo, 3) if kilo > 0 else 0.0,
        "brake_per_kilo": round(brake_hits / kilo, 3) if kilo > 0 else 0.0,
        "quote_emphasis": emph_hits,
    }

    return {"aid": round(aid_score, 3),
            "chars": chars,
            "by_rule": by_rule,
            "rhythm": rhythm,
            "connectivity": connectivity,
            "special": special,
            "guard": {"chars_kept_ratio": None, "para_delta": None,
                      "new_must_violations": None}}


def compute_guard(before_text: str, after_text: str, new_must_violations: int = None) -> dict:
    """改写质量护栏（需要改前稿）：字数保持率 / 段落数变化 / 新增 must 违规数。

    卡6S 只出读数；「改写不得更糟」的回退裁决归卡8 G1 / 卡7 双复扫接线。
    """
    b_paras = len([p for p in (before_text or "").splitlines() if p.strip()])
    a_paras = len([p for p in (after_text or "").splitlines() if p.strip()])
    b_chars = visible_chars(before_text)
    return {"chars_kept_ratio": round(visible_chars(after_text) / b_chars, 3) if b_chars else None,
            "para_delta": a_paras - b_paras,
            "new_must_violations": new_must_violations}
