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

C2 指标扩展（0.20.3；t8_deslop_research §8.1 清单 M1-M14 逐项落地，出处随项标注；
存量 aid/by_rule/rhythm/connectivity/special/guard 键与口径零变更，只增不改）：
  M1 cooccur              共现热点 escalate_cooccurrence：同千字窗内 ≥3 类 advisory
                          才升档（humanizer 三级强度体系/weak-alone 认识论——不加
                          词表先降误报；热点内 advisory 的 aid 贡献 ×2）
  M2 lexdiv 块            charbigram_ttr / type_token_ratio / mono_func_share
                          （arXiv:2606.04177：284 特征大研究中「唯一跨域稳健信号」；
                          HC3-Chinese TTR 人类 0.725 vs ChatGPT 0.543 定方向，
                          字符 bigram 为免分词近似，绝对阈待网文语料校准）
  M3 rhythm 扩展          sent_len_cv / burstiness / equal_len_run_max（CV=σ/μ；
                          B=(CV²−1)/(CV²+1) Goh & Barabási 2008；近等长游程 sepia
                          口径。lieflat 实测句长 CV 人机无差异——只作改碎护栏，
                          绝不作 AI 判定，与 0.22 rhythm 用途声明一致）
  M4 repetition 块        fourgram_repeat_ratio / zlib_ratio（arXiv:2210.08145
                          n-gram 自重复 + arXiv:2403.00553 压缩比代理；sloptrim #71
                          「六词跨重复 >20%=模型循环」同族思想，中文字单位先观测）
  M5 recap_overlap        章首×前章尾 4-gram 重叠率（humanizer #26 篇章级 tell
                          「章首复述前情」；独立函数，供跨章调用方接线）
  M6 dialog_ratio         对白占比 + dialog_band_offband 书级带宽越界（网文拆解
                          七本 5300 万字实测带宽中位 14.1%-31.7%——题材签名，
                          只设书级相对带不设全局阈）+ percentile 底座
  M7 per_book_threshold   密度型规则书级基线 = 各章读数 P90×1.2（humanizer 样本
                          覆盖规则 + baibanbao 裁决「抽他三篇旧稿数一数」；<3 章
                          不启用）
  M8 aid_adjusted         aid × (0.7+0.3×min(规则种类/10, 1))（sloptrim「pattern
                          diversity over raw density」：满篇同一病可矫，满篇各病
                          才是系统机味）
  M9 ending_mode          结尾模式读数 sendoff/introspective（StoryScope 内心接纳
                          47% vs 27% 最强结局指纹 + humanizer #13 送别段；读数
                          不设规则——规则化在 deslop.sendoff-para）
  M10 opening_ngram_max   同段首 4 字开头段落峰值（sloptrim opener repetition /
                          humanizer #7 的段落级形态）
  M11 abs_assert_per_kilo 绝对化副词密度（blader #9 反向移植：英文 AI 过度 hedge、
                          中文 AI 过度 assert——跨语言方向校验旗舰案例）
  M12 bei_per_kilo        「被」字结构粗读数（lieflat 实测人机无差异——只观测
                          不立规则；含「被子」类名词噪声，规则化前先看分布）
  M13 mood/turn/coord     语气词与连接词三子表（HC3 语气词人类 5 倍；lieflat 口语
                          转折人类多 vs HC3 并列连词 AI 多——方向相反必须拆表，
                          存量 conn_per_kilo 键保留不动）
  M14 aid_band/strategy   aid_adjusted 分档→处理策略（sloptrim 五档带宽思想：
                          clean 不改写保护人类味草稿；阈值为 qianbi 域起步校准值）
"""
import re
import zlib
from collections import Counter

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

# ---- C2 指标扩展词表（0.20.3，M6/M9/M11-M13；只进读数不设规则，先观测后定阈）----
# 连接词三子表（M13 / t8 §5 冲突 6 裁决）：转折/口语子表「低=坏」（改碎信号）、
# 并列/书面子表「高=坏」（翻译腔信号）——lieflat 实测口语转折人类多 3.8× 与 HC3
# 实测并列连词 AI 多，两个方向相反的信号混计一个 conn_per_kilo 方向不明，必须拆表。
# 存量 conn_per_kilo/func_per_kilo 键与其全文口径保留不动，子表另计。
_TURN_CONNS = ("但是", "可是", "不过", "然而", "其实", "倒是", "毕竟", "反正", "总之")
_COORD_CONNS = ("以及", "并且", "同时", "此外", "另外", "和", "与", "或")
# 叙述层语气词（M13，HC3-Chinese：人类 0.016 vs ChatGPT 0.003 五倍差）——只在
# strip_quoted 后的叙述层计数：对话内语气词是台词的一部分，不是叙述指纹。
_MOOD_PARTICLE_RE = re.compile(r"[啊吧呢嘛呀啦喔呗]")
# 绝对化副词（M11，blader #9 反向移植：中文 AI 过度 assert 非 hedge；叙述层）
_ABS_ASSERT_RE = re.compile(r"无疑|显然|必然|注定|毋庸置疑|理所当然|必定|绝对|断然|势必")
# 「被」字结构粗读数（M12，lieflat 实测人机无差异：只观测不立规则；「被+1-4字」
# 会吃进「被子」类名词噪声，故为粗读数，规则化前先看真机稿分布）
_BEI_RE = re.compile(r"被[一-鿿]{1,4}")
# 结尾抽象名词（M9 ending_mode 读数；与 deslop.SENDOFF_NOUNS 规则词表各自独立——
# 读数层不依赖 app-top，避免 core→app 反向边）
_ENDING_NOUN_RE = re.compile(r"未来|希望|命运|黎明|明天|新篇章|新的人生|远方|尽头|光芒")
# 动作动词线索（M9 introspective 判定的「无动作」粗筛；字面单字匹配足够作读数）
_ACTION_HINT_RE = re.compile(
    r"拿|推|抓|走|跑|跳|打|踢|拉|掷|扔|接|递|劈|砍|刺|挡|冲|退|站|坐|转身|回头"
    r"|抬|低|翻|掏|摸|握|松|咬|吞|喝|吃")


def in_dialogue(text: str, pos: int) -> bool:
    """判断位置是否在对话引号内（C16b/C3 maskQuoted 重写：引号片段一律不跨行）。

    旧实现统计位置之前全文引号开合计数——正文漏一个收引号很常见（多段台词只在
    末段收尾、全半角引号混用都会漏），一个未闭合的开引号会把后面成百上千字全算成
    「引号内」，让消费方把整段叙述静默豁免掉（oh-story QUOTE_SOURCES 注释点名的
    失败模式）。现改为逐行计算引号区间：行内漏收引号只吞到行尾，不会跨行泄漏。
    """
    if not (0 <= pos < len(text)):
        return False
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    return any(s <= pos < e for s, e in quoted_ranges(text[line_start:line_end]))


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


# ---- C2 新指标函数（M1-M10/M14；纯函数、零依赖、手算可对照）----

def _norm_visible(text: str) -> str:
    """去空白后的连续文本（n-gram/重复度统计口径；保留标点——标点模式也是模板的一部分）"""
    return re.sub(r"\s+", "", text or "")


def _norm_ngrams(text: str, n: int) -> list:
    t = _norm_visible(text)
    return [t[i:i + n] for i in range(len(t) - n + 1)]


def charbigram_ttr(text: str) -> float:
    """M2 字符 bigram TTR = 不同 bigram 数 / bigram 总数。

    词汇多样性主读数（arXiv:2606.04177：284 特征大研究中唯一跨域稳健信号；
    HC3-Chinese 词级 TTR 人类 0.725 vs ChatGPT 0.543 定方向）。stdlib 无分词，
    字符 bigram 是免分词近似，长度比词级 TTR 稳定；绝对阈待网文语料校准。
    """
    grams = _norm_ngrams(text, 2)
    return round(len(set(grams)) / len(grams), 3) if grams else 0.0


def type_token_ratio(text: str) -> float:
    """M2 字符级 TTR = 不同字符 / 总字符（短章辅助读数；长度依赖，只与同长文本比）"""
    t = _norm_visible(text)
    return round(len(set(t)) / len(t), 3) if t else 0.0


def mono_func_share(text: str) -> float:
    """M2 单字功能词占比近似（HC3-Chinese：单音节词占比人类 0.483 vs AI 0.379，
    AI 中文双音节化偏置；免分词，以 _FUNC_WORDS 单字功能词表命中/总字数近似）"""
    t = _norm_visible(text)
    if not t:
        return 0.0
    return round(sum(t.count(w) for w in _FUNC_WORDS) / len(t), 3)


def fourgram_repeat_ratio(text: str) -> float:
    """M4 4-gram 自重复度 = 重复 4-gram 覆盖字符 / 总字符。

    arXiv:2210.08145「self-repetition as the number of n-grams of length four
    or longer」的中文字单位落地：4 字命中即高置信；sloptrim #71「六词跨重复
    >20%=模型在循环」同族思想。观察读数，中文域阈值待校准。
    """
    t = _norm_visible(text)
    grams = _norm_ngrams(t, 4)
    if not grams:
        return 0.0
    counts = Counter(grams)
    repeated = sum(c for c in counts.values() if c >= 2)
    return round(4 * repeated / len(t), 3)


def zlib_ratio(text: str) -> float:
    """M4 压缩比代理 = len(zlib(text)) / len(text)（UTF-8 字节）。

    arXiv:2403.00553：快速压缩算法捕捉的信息与既有多样性分数收敛——越模板化
    越低。与 fourgram_repeat_ratio 交叉验证模板化；观察读数不设阈。
    """
    raw = (text or "").encode("utf-8")
    return round(len(zlib.compress(raw)) / len(raw), 3) if raw else 0.0


def _cv(nums: list) -> float:
    """变异系数 CV = σ/μ（无量纲，跨章可比；lieflat 实测人机无差异——只作改碎护栏）"""
    m = _mean(nums)
    if not nums or m == 0:
        return 0.0
    return _pvar(nums) ** 0.5 / m


def burstiness(nums: list) -> float:
    """M3 阵发参数 B = (CV²−1)/(CV²+1)（Goh & Barabási 2008 经典式：B=0 泊松、
    B→1 极端阵发、B→−1 规则周期）。arXiv:2604.05188 指出 BP 对部分幂律漏检、
    BTI 为后备——先上零依赖的 B 作读数，不做规则。"""
    m = _mean(nums)
    if not nums or m == 0:
        return 0.0
    cv2 = _pvar(nums) / (m * m)
    return round((cv2 - 1) / (cv2 + 1), 3)


def equal_len_run_max(lens: list, tol: float = 0.15) -> int:
    """M3 相邻句近等长（长度差 < tol×较长者）的最长游程句数。

    sepia 口径「runs of three or more adjacent near-equal sentences」——比方差
    更局部、可定位到具体句群；qianbi 校准样本正常中文多为 1-2，模型循环稿可达 6+。
    """
    best = run = 0
    prev = None
    for n in lens:
        if prev is not None and prev > 0 and n > 0 \
                and abs(n - prev) < max(prev, n) * tol:
            run += 1
        else:
            run = 1
        best = max(best, run)
        prev = n
    return best


def escalate_cooccurrence(findings: list, window: int = 1000,
                          min_rules: int = 3) -> list:
    """M1 共现热点：同 window 字窗内 ≥min_rules 类不同 rule 的 advisory 定位型命中
    → 热点段清单（humanizer 三级强度体系：weak alone 共现才行动——「人类写作也在
    吸收 AI 习惯，多条痕迹共现才是安全保障」；不加词表先降误报）。

    返回 [{"start", "end", "rules"}]（起点有序、两两不重叠）。聚合型 finding
    （start==end，章级无位置）与 blocking 不参与。消费方对热点内 advisory 加倍计
    aid 贡献（compute_metrics 已接 M8 接线）；规则 level 本身不升级——升档只动
    权重不动标签，单条弱信号不直接烧复扫轮次。
    """
    pts = sorted((f.start, f.end, f.rule) for f in (findings or [])
                 if f.level == "advisory" and f.end > f.start)
    out = []
    i = 0
    while i < len(pts):
        j = i
        rules = {pts[i][2]}
        while j + 1 < len(pts) and pts[j + 1][0] - pts[i][0] <= window:
            j += 1
            rules.add(pts[j][2])
        if len(rules) >= min_rules:
            span_end = max(p[1] for p in pts[i:j + 1])
            if out and pts[i][0] <= out[-1]["end"]:
                out[-1]["end"] = max(out[-1]["end"], span_end)
                out[-1]["rules"] = sorted(set(out[-1]["rules"]) | rules)
            else:
                out.append({"start": pts[i][0], "end": span_end,
                            "rules": sorted(rules)})
            i = j + 1
        else:
            i += 1
    return out


def recap_overlap(current: str, prev: str, head: int = 800,
                  tail: int = 600) -> float:
    """M5 章首复述重叠率 = |4-gram(本章前 head 字) ∩ 4-gram(前章尾 tail 字)|
    / |4-gram(本章前 head 字)|。

    humanizer #26 篇章级 tell：「上一章说到…」把读者刚看完的内容再演一遍，句级
    清理杀不死它。qianbi 追踪体系（前章正文/摘要）独有优势的度量层落点；
    说书传统允许简要回顾——先观测真机稿分布再定阈，不在正则域设规则。
    """
    cur = _norm_visible(current)[:head]
    pv = _norm_visible(prev)[-tail:]
    if len(cur) < 4 or len(pv) < 4:
        return 0.0
    cur_grams = {cur[i:i + 4] for i in range(len(cur) - 3)}
    pv_grams = {pv[i:i + 4] for i in range(len(pv) - 3)}
    return round(len(cur_grams & pv_grams) / len(cur_grams), 3)


def dialog_ratio(text: str) -> float:
    """M6 对白占比 = 引号内可见字 / 全文可见字。

    网文拆解 l1_stats 口径（「」“”同计）。七本 5300 万字实测带宽中位 14.1%
    （太荒吞天诀）～31.7%（牧神记）——题材/文风签名，只出读数配合书级
    P10-P90 带（dialog_band_offband），不设全局阈。
    """
    body = text or ""
    total = visible_chars(body)
    if total <= 0:
        return 0.0
    inner = 0
    for pat in _QUOTE_SPAN_RES:
        for m in pat.finditer(body):
            inner += visible_chars(m.group(0)[1:-1])
    return round(inner / total, 3)


def percentile(values: list, q: float) -> float:
    """线性插值百分位（确定性、手算可对照；M6 书级带宽 / M7 书级基线的底座）"""
    vs = sorted(values)
    if not vs:
        return 0.0
    if len(vs) == 1:
        return float(vs[0])
    pos = (len(vs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vs) - 1)
    frac = pos - lo
    return vs[lo] * (1 - frac) + vs[hi] * frac


def per_book_threshold(values: list, k: float = 1.2) -> float:
    """M7 书级密度基线 = 书内各章读数的 P90×k。

    humanizer 样本覆盖规则（含破折号条款）+ baibanbao 裁决 5「抽他三篇旧稿数一数」：
    破折号/视线/刹车等密度型规则以本书已成章为样本浮动阈值。书内 <3 章返回 0.0 =
    不启用（样本不足退回全局阈——sepia venue-corpus 同款护栏）。
    """
    if not values or len(values) < 3:
        return 0.0
    return round(percentile(values, 0.9) * k, 4)


def dialog_band_offband(ratio: float, p10: float, p90: float) -> bool:
    """M6 章级对白占比是否越出书级 P10-P90 带。

    带宽是题材/文风变量（快节奏书 58% 的章在 10-20% 档、群像书中位 31.6%——
    分布形态完全不同），只能设书级相对带；带参无效（p90<=p10 或 None）返回
    False = 不判。
    """
    if p10 is None or p90 is None or p90 <= p10:
        return False
    return ratio < p10 or ratio > p90


def opening_ngram_max(text: str, k: int = 4) -> int:
    """M10 段首复读峰值 = 同一段首 k 可见字开头的最大段落数。

    sloptrim detect_opener_repetition / humanizer #7 句首复读的段落级形态
    （「他看着天／他看着地」式同构开场成批复现）。
    """
    keys = [t for t in (_norm_visible(p)[:k] for p in (text or "").splitlines()) if t]
    return max(Counter(keys).values()) if keys else 0


def ending_mode(text: str) -> str:
    """M9 结尾模式读数：sendoff / introspective / normal。

    - sendoff：末段抽象名词 ≥2 且无台词（humanizer #13 送别段——整段砍掉落回
      最后一个具体事实）；规则化在 deslop.sendoff-para，此处只出读数。
    - introspective：末 3 段无台词无动作动词（StoryScope：内心接纳式结局
      人类 27% vs AI 47%，最强结局指纹）。
    """
    paras = [t for t in (_norm_visible(p) for p in (text or "").splitlines()) if t]
    if not paras:
        return "normal"
    last = paras[-1]
    if len(set(_ENDING_NOUN_RE.findall(last))) >= 2 \
            and not any(q in last for q in "「“"):
        return "sendoff"
    tail = paras[-3:]
    if len(tail) == 3 and not any(q in p for p in tail for q in "「“") \
            and not any(_ACTION_HINT_RE.search(p) for p in tail):
        return "introspective"
    return "normal"


# M14 AID 分档→处理策略（sloptrim 五档带宽思想；阈值为 qianbi 域起步校准值——
# aid_adjusted 是「每千字加权命中」量纲，与 sloptrim 0-100 分不同域，只借分档哲学。
# clean 不改写是关键消费语义：保护人类味草稿，只做字符层清洗）。
AID_BANDS = (
    (2.0, "clean", "只做字符层清洗，不改写"),
    (5.0, "light", "只修 blocking 与共现热点"),
    (10.0, "mixed", "标准 deslop 改写"),
)
AID_HEAVY_STRATEGY = "整章重写+金丝雀复扫"


def aid_band(aid_adjusted: float) -> tuple:
    """M14 aid_adjusted → (档位, 处理策略)：clean/light/mixed/heavy 四档"""
    for upper, name, strategy in AID_BANDS:
        if aid_adjusted <= upper:
            return name, strategy
    return "heavy", AID_HEAVY_STRATEGY


def compute_metrics(text: str, findings: list, weights: dict = None) -> dict:
    """文本 + deslop 扫描 findings → 指标 dict（纯本地，不落盘）。

    C2 起返回键：aid / aid_adjusted / aid_band / aid_strategy / chars / by_rule /
    rhythm / lexdiv / repetition / connectivity / special / cooccur / guard——
    存量六键口径零变更，其余为 0.20.3 新增（形状变更记录见 0.20.3 工作报告）。
    """
    w = dict(AID_WEIGHTS)
    if weights:
        w.update(weights)
    chars = visible_chars(text)
    kilo = chars / 1000.0
    _findings = findings or []

    # 1) AID 特征密度（存量口径：Σ(命中数×权重)/千字，不含 M1 升档与 M8 多样性加权）
    aid_score = (sum(w.get(f.level, 1.0) for f in _findings) / kilo) if kilo > 0 else 0.0

    # M1 共现热点 + M8 多样性加权 + M14 分档（只动 aid_adjusted，aid 保持兼容口径）
    hotspots = escalate_cooccurrence(_findings)
    hotspot_extra = sum(w.get("advisory", 1.0) for f in _findings
                        if f.level == "advisory" and f.end > f.start
                        and any(s <= f.start < e for s, e in
                                ((h["start"], h["end"]) for h in hotspots)))
    n_rules = len({f.rule for f in _findings})
    diversity_factor = 0.7 + 0.3 * min(n_rules / 10.0, 1.0)
    aid_adjusted = round((aid_score + hotspot_extra / kilo) * diversity_factor, 3) \
        if kilo > 0 else 0.0
    band, strategy = aid_band(aid_adjusted)

    # 2) 分规则命中表（复活 summarize_findings 作聚合底座）
    merged = {}
    for st in summarize_findings(_findings).values():
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
    #    （M3 扩展：CV/burstiness/近等长游程——只作改碎护栏读数，不作 AI 判定）
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
        # M3（t8 §6.1）：CV=σ/μ 跨书可比；B=(CV²−1)/(CV²+1)；近等长游程 sepia 口径
        "sent_len_cv": round(_cv(sent_lens), 3),
        "burstiness": burstiness(sent_lens),
        "equal_len_run_max": equal_len_run_max(sent_lens),
    }

    # M2 lexdiv 块（t8 §6.2：词汇丰富度是 284 特征研究中唯一跨域稳健信号）
    lexdiv = {
        "charbigram_ttr": charbigram_ttr(text or ""),
        "type_token_ratio": type_token_ratio(text or ""),
        "mono_func_share": mono_func_share(text or ""),
    }

    # M4 repetition 块（t8 §6.4：n-gram 自重复 + 压缩比代理，交叉验证模板化）
    repetition = {
        "fourgram_repeat_ratio": fourgram_repeat_ratio(text or ""),
        "zlib_ratio": zlib_ratio(text or ""),
    }

    # 4) 连接度：功能词/千字、白话连接词/千字、≥30 字承接句占比（存量口径不动）
    #    + M13 三子表：转折/并列（全文口径，与存量 func/conn 同分母）+ 叙述层语气词
    body = text or ""
    conn_hits = sum(body.count(wd) for wd in _CONNECTORS)
    func_hits = sum(body.count(wd) for wd in _FUNC_WORDS)
    long_sents = sum(1 for n in sent_lens if n >= _LONG_SENT_CHARS)
    narr = strip_quoted(body)
    narr_kilo = visible_chars(narr) / 1000.0
    turn_hits = sum(body.count(wd) for wd in _TURN_CONNS)
    coord_hits = sum(body.count(wd) for wd in _COORD_CONNS)
    mood_hits = len(_MOOD_PARTICLE_RE.findall(narr))
    connectivity = {
        "func_per_kilo": round(func_hits / kilo, 3) if kilo > 0 else 0.0,
        "conn_per_kilo": round(conn_hits / kilo, 3) if kilo > 0 else 0.0,
        "long_bridge_ratio": round(long_sents / len(sent_lens), 3) if sent_lens else 0.0,
        # M13（t8 §5 冲突 6 / §6.3）：方向相反的双信号拆表 + 语气词（人类 5 倍）
        "turn_conn_per_kilo": round(turn_hits / kilo, 3) if kilo > 0 else 0.0,
        "coord_conn_per_kilo": round(coord_hits / kilo, 3) if kilo > 0 else 0.0,
        "mood_particle_per_kilo": round(mood_hits / narr_kilo, 3) if narr_kilo > 0 else 0.0,
    }

    # 专项密度（D1/D2/B6/C11 的读数，只进指标不设规则）
    gaze_hits = len(GAZE_MARKERS.findall(body))
    brake_hits = len(BRAKE_MARKERS.findall(body))
    quote_spans = _QUOTE_SPAN_RE.findall(body)
    tag_hits = len(_DIALOG_TAG_RE.findall(body))
    emph_hits = len([m for m in QUOTE_EMPHASIS.finditer(body)
                     if not in_dialogue(body, m.start())])
    abs_hits = len(_ABS_ASSERT_RE.findall(narr))
    bei_hits = len(_BEI_RE.findall(narr))
    special = {
        "dialog_tag_ratio": round(tag_hits / len(quote_spans), 3) if quote_spans else 0.0,
        "gaze_per_kilo": round(gaze_hits / kilo, 3) if kilo > 0 else 0.0,
        "brake_per_kilo": round(brake_hits / kilo, 3) if kilo > 0 else 0.0,
        "quote_emphasis": emph_hits,
        # M6/M9/M10/M11/M12（t8 §8.1；对白占比为题材签名读数，配合书级带宽消费）
        "dialog_ratio": dialog_ratio(body),
        "opening_ngram_max": opening_ngram_max(body),
        "ending_mode": ending_mode(body),
        "abs_assert_per_kilo": round(abs_hits / narr_kilo, 3) if narr_kilo > 0 else 0.0,
        "bei_per_kilo": round(bei_hits / narr_kilo, 3) if narr_kilo > 0 else 0.0,
    }

    return {"aid": round(aid_score, 3),
            "aid_adjusted": aid_adjusted,
            "aid_band": band,
            "aid_strategy": strategy,
            "chars": chars,
            "by_rule": by_rule,
            "rhythm": rhythm,
            "lexdiv": lexdiv,
            "repetition": repetition,
            "connectivity": connectivity,
            "special": special,
            "cooccur": {"count": len(hotspots), "hotspots": hotspots},
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
