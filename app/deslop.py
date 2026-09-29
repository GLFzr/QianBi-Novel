# -*- coding: utf-8 -*-
"""去 AI 味扫描器：本地正则规则集，检测网文 AI 写作痕迹

检测级别：
- blocking（阻断级）：确定性毒句式，必须修
- advisory（建议级）：密度型问题，提示人工复核

C16b/C1a 统一增强包（28→45）：oh-story 11 条增量（A1-A11）+ humanizer 6 条直命中
+ lieflat 实测倍率规则（R3/R4/R5）。校准纪律（oh-story §7 / t2 §3.2E）：每条新规则
注释必须带语料基线数字；「有真人命中就不许升 blocking」——本批 17 条新规则全部
advisory 起步，blocking 只收上游双库校准过的既有规则增补分支。网文语料复校准数据
（7 书×前 100 章）见 0.23.0 工作报告 P4 节。
"""
import re
from dataclasses import dataclass, field


@dataclass
class Finding:
    rule: str          # 规则 ID
    level: str         # blocking / advisory
    message: str       # 问题描述
    text: str          # 命中文本
    start: int         # 在原文中的起始位置
    end: int           # 结束位置
    fix_hint: str = "" # 修法建议


# ========== Blocking：确定性毒句式 ==========

# "不是A，（而）是B" 及其变体
NOT_IS_PATTERN = re.compile(
    r"不是[^。！？!?\n]{1,30}?[，,](?:而)?(?:只)?是[^。！？!?\n]{1,30}"
)
# 反序变体 "是B，不是A"
REVERSE_NOT_IS = re.compile(r"是[^。！？!?\n]{1,30}?[，,]不是[^。！？!?\n]{1,30}")
# 否定排比（C1a/A11+B4 双模式重写，见 NEGATION_PARADE_PATTERNS）
NEGATION_PARADE_PATTERNS = [
    # 模式①连排（qianbi 0.22 口径：第二段可不带尾逗号）+ 光杆「没」双护栏——
    #   前字排除黏着语素（沉没/淹没/埋没/出没/隐没/湮没/吞没/覆没/漫没/泯没），
    #   后字排除时间惯用语（没多久/没过多久）：「船沉没在雾里，没人回头」不算。
    re.compile(r"(?<![沉淹埋出隐湮吞覆漫泯])没(?:有)?(?!有?过?多久)"
               r"[^。！？!?\n，,]{1,12}[，,]\s*"
               r"(?<![沉淹埋出隐湮吞覆漫泯])没(?:有)?(?!有?过?多久)"
               r"[^。！？!?\n，,]{1,20}"),
    # 模式②先否后肯（oh-story 原样直译）：没X，没Y…只是Z。「船沉没在雾里，没人回头，
    # …只有…」「没多久，没等她撑伞，…只有…」两类歧义由同款护栏排除。
    re.compile(r"(?<![沉淹埋出隐湮吞覆漫泯])没(?!有?过?多久)(?:有)?"
               r"[^。！？!?\n，,]{1,12}[，,]\s*"
               r"没(?!有?过?多久)(?:有)?[^。！？!?\n，,]{1,16}"
               r"[，,。.][^。！？!?\n，,]{0,6}只(?:是|会|有)"),
]
# 音量反差腔 "声音不大/不高…却…"（C1b/B3 换 oh-story 校准正则，见 VOICE_CONTRAST）
VOICE_CONTRAST = re.compile(r"声音(?:并)?不[大高响亮][^。！？!?\n]{0,16}[却但偏]")
# 无情绪声线
FLAT_VOICE = re.compile(r"语气毫无波澜|平静无波|声音平直|声音平平|听不出(?:任何)?情绪")
# "，带着……" 万能状语
DAIZHE_ADVERB = re.compile(r"[，,]带着[^。！？!?\n]{1,30}")
# 章末预告 "他不知道的是……"
TRAILER_ENDING = re.compile(r"(?:他|她|我)不知道的是")
# 预告式总结收尾（C1a/A1+A10 扩为模式组 + 组内重叠去重；见 TRAILER_SUMMARY_PATTERNS）
TRAILER_SUMMARY_PATTERNS = [
    # ---- qianbi 0.22 存量（「没人知道」族按 qianbi 口径留在 trailer-summary；上游
    # 同窗同 severity 归 trailer-ending，仅标签不同——保持 0.22 测试契约）----
    re.compile(r"(?:没人知道|没有人知道)[^。！？!?\n]{0,30}"),
    re.compile(r"(?:反击|复仇|战争|较量|故事|命运|一切)[^。！？!?\n]{0,12}才刚刚开始"),
    # ---- A10 增补（oh-story 实战漏网 D；「正式拉开序幕/帷幕」是场内报幕陈述，
    # lookbehind 排除。《万疆》20 章排除 2 处报幕句后 0 命中）----
    re.compile(r"殊不知|谁也不知道|谁也没想到"),
    re.compile(r"正(?:朝着|向着)[^。！？!?\n]{0,24}(?:压|涌|袭|逼)(?:了?过去|了?过来|来)"),
    re.compile(r"(?<!正式)拉开(?:序幕|帷幕)"),
    # (?![的，]) 排除定语用法（「想到即将开始的聚会」）——700 章真人语料校准
    re.compile(r"即将(?:开始|来临|降临)(?![的，,])"),
    re.compile(r"(?:这)?才刚刚开(?:始|头)"),
    # ---- A1 四分支句末锚（oh-story trailer-summary 直译；各分支要求句末断言位，
    # 防吃进条件从句/动补/系表/间接疑问。「命运…齿轮」分支不收——fate-summary 已
    # 全文级同款 blocking，双收只添重复报）----
    re.compile(r"这一(?:夜|天|刻|战|年|局|役)[，,]?[^。！？!?，,\n]{0,6}"
               r"(?<!命中)(?<!是)注定[^。！？!?\n]{0,8}[。！]"),
    re.compile(r"就这样[，,][^。！？!?，,\n]{0,8}(?:一切|全部)"
               r"[^。！？!?，,\n]{0,4}(?:结束了|落幕|收场)[。！]"),
    re.compile(r"这一切[，,]?[^。！？!?，,\n]{0,6}(?:都)?(?:说明|意味着|结束了)"
               r"(?!的)(?:(?!什么)[^。！？!?\n]){0,6}[。！]"),
    re.compile(r"(?:新的篇章|新的旅程|崭新的篇章|新的人生)[^。！？!?\n]{0,6}(?:开始|拉开|展开)"),
]
# 章末预告族（trailer）检测窗口：trailer 是「章末」病——正文中段同款句子属
# 合法悬念铺陈不报，只收文末 600 可见字窗口（卡6S 存量修复）。
TRAILER_WINDOW = 600


def _tail_start(body: str) -> int:
    return max(0, len(body) - TRAILER_WINDOW)


def _tail_window_hits(pattern, body: str) -> list:
    """pattern 在文末 TRAILER_WINDOW 字窗口内的命中（越出窗口的中段命中丢弃）"""
    tail_start = _tail_start(body)
    return [m for m in pattern.finditer(body) if m.start() >= tail_start]


def _dedup_spans(spans: list) -> list:
    """区间重叠去重只报一次（oh-story findNegationParade 同款：排序后重叠者跳过并延展）"""
    spans = sorted(spans)
    out = []
    last_end = -1
    for s, e in spans:
        if s < last_end:
            last_end = max(last_end, e)
            continue
        out.append((s, e))
        last_end = e
    return out


# 抽象命运总结
FATE_SUMMARY = re.compile(
    r"(?:命运|宿命)[^。！？!?\n]{0,28}(?:齿轮|棋局|獠牙|改写|安排)|"
    r"这一刻[，,]?[^。！？!?\n]{0,24}(?:终于|才)(?:明白|意识到)|"
    r"从这一刻开始"
)
# 破折号（密度阈值策略：>6/千字 才阻断，低密度仅 advisory）
EM_DASH = re.compile(r"——|—(?!-)")

# 文言腔比喻标记（lieflat Phase 2 联动降级：原属一级禁用词逐词 blocking。
# 上游 283 万字语料：人类比喻频率是 AI 的 2.4 倍，逐词阻断与生成端
# 「每千字 ≥1 处具象比喻」下限自相矛盾（旧病：复扫 2 轮烧尽→章章待修）；
# 比喻总量另由 metaphor-density advisory 管控。现降为密度阈值型 advisory。
CLICHE_SIMILE = re.compile(r"仿佛|犹如|宛若|如同")

# 提示性冒号（lieflat 规则 5 形态一子集：提示语+冒号替自己说话，千字密度 advisory）
PROMPTING_COLON = re.compile(
    r"(?:一句话总结|核心是|关键在于|原因如下|结论是|答案是|先说结论|本质上|换句话说|说白了)[：:]")

# 顿号罗列句（lieflat 规则 2：分句内 ≥2 顿号连起 ≥3 并列项）
DUNHAO_IN_CLAUSE = re.compile(r"、")

# 模板化微表情（一级禁用词）
CLICHE_PATTERNS = [
    re.compile(r"一丝|一抹|些许|几分|隐约"),
    re.compile(r"深吸一口气|不禁"),
    re.compile(r"眼中闪过|嘴角勾起|眉头微皱|眉眼低垂|瞳孔微缩|瞳孔收缩|指节泛白|眼神锐利|目光锐利"),
    re.compile(r"心中涌起一股|心头一震|心中一动|心下了然|心中暗道|心中一凛|心底泛起|不由得"),
    re.compile(r"不容置疑|不容置喙|不易察觉|显而易见|毫无疑问|不可否认|前所未有"),
    re.compile(r"声音不大[，,]?却带着|语气平静无波|平静无波|声音平直|听不出情绪"),
    re.compile(r"散发着一股|不由自主|情不自禁|自然而然|话锋一转"),
    re.compile(r"取而代之的是|淬了|心里某个地方"),
]

# 认知直接告知 "他知道/她明白/他意识到"
TELLING_COGNITION = re.compile(r"(?<![不没未无])(?:他|她|我)(?:知道|明白|意识到|清楚)(?:[^。！？!?\n]{0,20})")

# 比喻标记（密度型）
METAPHOR_MARKERS = re.compile(r"好像|像是|仿佛|宛如|如同|犹如|(?<![不头图画影录摄肖])像(?![头像素])")

# 微动作复读「V了下 / V了一下」
MICRO_TIC = re.compile(r"了(?:[一两三几半])?[下阵圈道声眼口气会]")

# 抽象总结复读（密度型；C1a/A9 并入 oh-story 增补分支：「前所未有X」不收——
# cliche-word 一级表已逐词 blocking 同词面，双收只添重复报）
ABSTRACT_SUMMARY = [
    re.compile(r"这一刻[，,]?[^。！？!?\n]{0,24}(?:终于|才)(?:明白|意识到)"),
    re.compile(r"从这一刻开始"),
    re.compile(r"(?:命运|宿命)[^。！？!?\n]{0,28}(?:齿轮|棋局|獠牙|改写|推向|安排)"),
    re.compile(r"(?:反击|复仇|战争|较量|故事|命运)[^。！？!?\n]{0,12}才刚刚开始"),
    # A9 增补（oh-story abstract-summary 桶）
    re.compile(r"早已[^。！？!?\n]{0,8}(?:布好|安排好)[^。！？!?\n]{0,8}(?:棋局|局)"),
    re.compile(r"(?:新的开始|全新的开始)"),
]

# 解释链（密度型；C1b/B6 扩四桶四重门，见 REASONING_CHAIN_PATTERNS）
REASONING_CONNECTOR = re.compile(r"这意味着|也就是说|换句话说|问题在于|关键在于|想到这里")

# 引号强调滥用（叙述里短词加引号）——S6a 起真身在 core.deslop_metrics（与度量层
# 共用的特征登记处单一真源，app-top→core 合法方向），此处导入转发保调用面不变
from .core.deslop_metrics import (BRAKE_MARKERS, GAZE_MARKERS, QUOTE_EMPHASIS,
                                  in_dialogue as _in_dialogue,
                                  mask_quoted as _mask_quoted,
                                  strip_quoted as _strip_quoted,
                                  summarize_findings)

# 否定刹车句独立成段（结构型：可预测的段落刹车）
BRAKE_STANDALONE = re.compile(r"^[^\n]{0,6}没有[^。，！？\n]{1,6}[。！？]?$", re.M)

# 「猛地」反应词窄库（密度型：惊觉模板）
MENGDI = re.compile(r"猛地")


# ========== C1a 增量规则（17 条：oh-story 11 + humanizer 6 直命中/lieflat 实测）==========
# 校准基线：7 书×前 100 章（凡人修仙传/儒道至圣/剑来/太荒吞天诀/斗破苍穹/牧神记/诡秘之主，
# 700 章真人网文）实扫 + 命中逐条人工复核；调参记录见 0.23.0 工作报告 P4 节。

# 上游口径可见字长（oh-story visibleLength：只数汉字/全角字母/ASCII 字母数字——
# 千字密度阈值按此口径校准，不与 visible_chars（含标点）混用）
_UPSTREAM_VISIBLE_RE = re.compile(r"[一-鿿Ａ-ｚA-Za-z0-9]")


def _visible_len(s: str) -> int:
    return len(_UPSTREAM_VISIBLE_RE.findall(s))


def _body_lines(body: str) -> list:
    """[(line_text, offset)] 按行拆分并保留每行在 body 中的偏移"""
    out = []
    off = 0
    for ln in body.split("\n"):
        out.append((ln, off))
        off += len(ln) + 1
    return out


_DIVIDER_RE = re.compile(r"^(?:-{3,}|[*_]{3,})$")
_STRUCTURAL_RE = re.compile(r"^(?:#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|\|)")
_CHAPTER_HEAD_RE = re.compile(r"^第[零一二三四五六七八九十百千万\d]+章(?:\s|_|$)")


def _is_structural_line(trimmed: str) -> bool:
    """分隔线 / markdown 结构行 / 章节标题行：非叙述正文，行级规则跳过（oh-story isStructural）"""
    return bool(_DIVIDER_RE.match(trimmed) or _STRUCTURAL_RE.match(trimmed)
                or _CHAPTER_HEAD_RE.match(trimmed))


def _count_terms(text: str, terms) -> int:
    n = 0
    for t in terms:
        i = text.find(t)
        while i != -1:
            n += 1
            i = text.find(t, i + len(t))
    return n


# 1) negation-pair-tic「没A，也没B」否定对偶（oh-story #20；七猫人类长篇 0.07 处/千字
#    vs 模型稿 0.4-1.5 处/千字——写人物没做什么是英文式节奏）≥3 处报一条。
#    语料校准（7 书×前 100 章真人逐条人工复核）：「V不X（救不了/砸不了），也…」是
#    可能补语法连接不是修辞对偶——首段以 了/着/过/的/得 收尾的命中跳过；调参后
#    3/700 章 advisory 触发（0.43%，与上游 advisory 容忍线同量级，命中均为真形态）。
NEGATION_PAIR = re.compile(
    r"(?:没有|没|不)([^，。！？；,!?\n]{1,10})[，,；]\s*[^，。！？；,!?\n]{0,6}?也(?:没有|没|不)")
NEGATION_PAIR_COMPL_TAIL = re.compile(r"[了着过的得]$")
NEGATION_PAIR_MIN_HITS = 3

# 2) stock-reaction-tic 套式反应细节（oh-story 7 模式直译；校准 qimao 长篇 5584 章 +
#    heiyan 短篇 3983 篇：per-kilo 1.0→1.5 误报 0.43%→0.39%（长篇）/5.57%→1.46%（短篇），
#    故取 1.5 把两个总体拉到同一量级。此类词面变化大不能逐词 blocking。）
STOCK_REACTION_PATTERNS = [
    re.compile(r"(?:指尖|手指|指节|手背|掌心|拳头|袖口|衣角|裙角|下唇|嘴唇|唇角|嘴角|眉头|眼底|眸光|目光|视线|肩膀|呼吸)"
               r"[^。！？!?\n]{0,16}(?:轻轻|微微|缓缓|悄然|不自觉|无意识|下意识|攥紧|握紧|收紧|绞紧|泛白|发白|叩|敲|摩挲|抿紧|抿成|移开|垂下|躲开|一颤|颤了?一下|停了?一下|顿了?一下)"),
    re.compile(r"(?:语气|声音)[^。！？!?\n]{0,12}(?:平静|冷静|平淡|冷淡|淡漠|平直)"
               r"[^。！？!?\n]{0,12}(?:像|仿佛|如同|好像)[^。！？!?\n]{0,16}(?:念|读|报|说|陈述|宣判|背诵)"),
    re.compile(r"(?:胸口|心口)[^。！？!?\n]{0,16}(?:像|仿佛|如同|好像)"
               r"[^。！？!?\n]{0,16}(?:撞|锤|压|攥|堵)[^。！？!?\n]{0,8}(?:一下|一记|一拳)?"),
    re.compile(r"(?:声音|嗓音|语气)[^。！？!?\n]{0,12}(?:放轻|压低|发紧|发颤|很轻|轻了些)"),
    re.compile(r"(?:喉结|喉头|喉咙)[^。！？!?\n]{0,10}(?:滚|动|紧|堵|发涩|发干)"),
    re.compile(r"(?:眼眶|眼圈|鼻子)[^。！？!?\n]{0,8}(?:发红|红了|发热|发酸|一酸)"),
    re.compile(r"(?:抿了?下唇|抿了?抿唇|抿了?下嘴|抿着笑)"),
]
STOCK_REACTION_MIN_HITS = 4
STOCK_REACTION_PER_KILO = 1.5

# 3) action-list-tic 监控摄像头式动作清单（oh-story 38 词动词表；同段 ≥5 动词且
#    ≥4 逗号/顿号分隔符。打斗/追逐等功能性动作编排可保留——semantic 复核话术。）
ACTION_LIST_VERBS = re.compile(
    r"伸手|抬手|探手|拿起|拿过|取出|取过|掏出|摸出|抓起|攥住|握住|捏住|按住|推开|拉开|打开|"
    r"关上|放下|递给|挑开|掀开|扯开|拧开|倒出|端起|转身|回头|抬头|低头|弯腰|俯身|走到|走向|"
    r"坐下|站起|看向|看着|盯着|扫过")
ACTION_LIST_MIN_HITS = 5
ACTION_LIST_MIN_SEPARATORS = 4

# 4) system-notice-formality-tic 系统公告公文腔（oh-story 直译：只看 ^【…】$ 整行规则行；
#    行 ≥4 且 命中 ≥12 且 core ≥5 且 ≥60/千字（按规则行字数计）。单条严肃规则、
#    日常叙述或普通对话不触发；系统文题材用书级白名单豁免。）
NOTICE_LINE = re.compile(r"^【[^】]+】$")
NOTICE_FORMAL_PATTERNS = [
    re.compile(r"不得|必须|不可|禁止|严禁|应当|须|需|务必"),
    re.compile(r"当前|本公告|本规则|本系统|提示|任务失败|临时权限|权限|状态|等级"),
    re.compile(r"维持|公共区域|秩序|优先|惩罚|处罚|违规|指令|执行"),
    re.compile(r"被视为|同样计入|计入|承担|责任|单位|撤回|转发|截图"),
]
NOTICE_FORMAL_CORE = re.compile(r"不得|必须|不可|禁止|严禁|应当|须|需|务必|被视为|同样计入|计入")
NOTICE_FORMAL_MIN_LINES = 4
NOTICE_FORMAL_MIN_HITS = 12
NOTICE_FORMAL_CORE_MIN_HITS = 5
NOTICE_FORMAL_PER_KILO = 60

# 5) overcompressed-prose-tic 过度精炼短段（oh-story 四重与门直译：叙述 ≥1200 字 且
#    ≥45 段 且 ≤15 字短段占比 ≥58% 且 自然连接词 <85/千字。禁止机械注水；有意短镜头可留。）
OVERCOMPRESSED_PARTICLE = re.compile(r"[的了就着过呢吧啊呀嘛]")
OVERCOMPRESSED_MIN_CHARS = 1200
OVERCOMPRESSED_MIN_PARAS = 45
OVERCOMPRESSED_SHORT_MAX = 15
OVERCOMPRESSED_SHORT_RATIO = 0.58
OVERCOMPRESSED_PARTICLE_PER_KILO = 85

# 6) low-connective-density-tic 低连接密度（oh-story 三重与门直译：功能词 <100/千字 且
#    白话连接 <65/千字 且 ≥30 字承接句占比 <8%，样本 ≥800 字，只数引号外叙述。
#    与 overcompressed 互补；修法是恢复必要连接，禁止机械注水。）
LOW_CONN_FUNC_TERMS = ("的", "了", "就", "在", "是", "也", "都", "还", "又", "把", "被",
                       "给", "这个", "那个", "里面", "以后", "时候", "现在", "因为", "所以",
                       "但是", "不过", "然后", "已经", "还是", "起来", "出来", "下去")
LOW_CONN_PLAIN_TERMS = ("的", "了", "就", "也", "还", "又", "这个", "那个", "东西", "事情",
                        "时候", "里面", "以后", "一下", "一点", "有点", "还是")
LOW_CONN_MIN_CHARS = 800
LOW_CONN_FUNC_PER_KILO = 100
LOW_CONN_PLAIN_PER_KILO = 65
LOW_CONN_LONG_SENT_CHARS = 30
LOW_CONN_LONG_SENT_RATIO = 0.08

# 7) formulaic-parallelism 工整并列（oh-story 三模式；「不放辣，不放葱」靠宾语最短
#    长度排除。语料校准修正：①只扫引号外叙述——真人台词/指令里的否定清单（不要惊动，
#    不要打扰）是对话功能不是叙述指纹；②排除连词/副词性「不X」（不断/不同/不管/不可/
#    不曾/不仅…）——真人高频连接词，命中即误报。）
DECISION_FRAME = re.compile(r"至于([一-鿿]{1,3})不\1[，,]\s*怎么\1")
REPEATED_NEG_VERB = re.compile(r"不([一-鿿]{1,2})([一-鿿]{2,8})[，,]\s*不\1([一-鿿]{2,8})")
# 连词/副词/助动性「不X」：不断学习/不同的X/不管怎样/不可打听/不曾走动/不是A，不是B/
# 不要看到/不能着急/不再注视/不需为难/不知所措/不变的X/不一定有——真人高频复用，
# 收录即误报；规则只留内容动词否定清单（不放辣，不放葱）。
REPEATED_NEG_CONJ = {"不断", "不同", "不管", "不可", "不曾", "不时", "不少", "不由",
                     "不禁", "不免", "不妨", "不限", "不单", "不仅", "不但", "不过",
                     "不只", "不外", "不知", "不要", "不再", "不是", "不能", "不变",
                     "不需", "不一定", "不宜", "难以"} - {"难以"}
CROSS_NEG_START = re.compile(r"^不是[^。！？!?\n]{1,24}[。！？!?]?$")
CROSS_NEG_MIDDLE = re.compile(r"^(?:也|还)不是[^。！？!?\n]{1,24}[。！？!?]?$")
CROSS_NEG_END = re.compile(r"^只是[^。！？!?\n]{1,32}[。！？!?]?$")

# 8) cliche-density-tic 套词密度（oh-story 密度哲学：单个词可能是正常中文，高密度聚集才报。
#    词表只收 qianbi cliche-word 一级表 / simile-marker-density **未收**的二级形态，防双报：
#    缓缓/微微/轻轻/淡淡、不知何时/唾手可得/沉默蔓延/难以言说、冰冷的光 等上游高危组，
#    加 lieflat/t8 二级候选（堪称/可谓/息息相关/毫无征兆/几不可闻/微不可察/瞳孔一缩）。
#    ≥8 处 且 ≥12/千字（引号外叙述）才报。）
CLICHE_DENSITY_PATTERNS = [
    re.compile(r"缓缓|微微|轻轻|淡淡"),
    re.compile(r"眸光微微一闪"),
    re.compile(r"不知何时|唾手可得|无声翻涌|沉默(?:在[^。！？!?\n]{0,16})?蔓延|难以言说"),
    re.compile(r"冰冷的光|格外刺眼|深邃而冰冷"),
    re.compile(r"堪称|可谓|无不"),
    re.compile(r"息息相关|密不可分|千丝万缕"),
    re.compile(r"毫无征兆|几不可闻|微不可察|瞳孔一缩"),
]
CLICHE_DENSITY_MIN_HITS = 8
CLICHE_DENSITY_PER_KILO = 12

# 9) forced-triad 强凑三连（humanizer #6 + liefast 句间裁准：收「句间同构复用」不收
#    「恰好三」——同段三项以同一 2-4 字开头复用（他看着天，他看着地，他看着自己的手）。
#    语料校准修正：①恰三才报——真人枚举惯用 4 项以上（有的缺手，有的断腿，有的脑袋
#    少一半，有的胸口破开），≥4 项是列举不是凑三；②枚举/修辞开头排除（有的/时而/
#    无比/有些/有时）；③三段全同是复沓修辞（平静，平静，平静）不报。没/不 开头归
#    negation-parade/negation-pair 域不双报；≥2 处才报，叙事推进三连交语义复核。）
FORCED_TRIAD = re.compile(r"([一-鿿]{2,4})[一-鿿]{0,4}[，,]\s*\1[一-鿿]{0,4}[，,]\s*\1")
FORCED_TRIAD_ENUM_OPENERS = {"有的", "时而", "无比", "有些", "有时", "偶尔", "屡屡"}
FORCED_TRIAD_MIN_HITS = 2

# 10) sentence-opening-run 句首复读（humanizer #7：连续 ≥3 句以同一 1-2 字代词/人名
#     开头且句长均 ≤10 可见字——「她看着他。她转身。她走了。」主语补全过度指纹。
#     语料校准修正：拟声/惊叹连发（咚！咚！咚！/后天二重！后天三重！）与对话标签行
#     （「……」方运道）是真人正常形态——只收以句号收尾的陈述短句，句尾是说/道/问等
#     引语动词的标签句打断计数。）
SENT_OPEN_PRONOUNS = set("他她它我你")
SENT_OPEN_MAX_LEN = 10
SENT_OPEN_MIN_RUN = 3
_SENT_OPEN_TAG_TAIL = re.compile(r"(?:说|道|问|答|喊|叫|嚷|嘀咕|笑道|开口)[:：]?$")

# 11) idealized-persona-simile 拟人化喻体（lieflat 第 7 条：AI 0.018/千字 vs 人类 0.002，
#     倍率 7.3×——带「智慧/不朽」类修饰达 12.6×，全表最高。只收抽象角色词表 +
#     褒义/抽象修饰；父亲/母亲/老师等真人常用喻体不收。）
IDEALIZED_SIMILE = re.compile(
    r"(?:像|好像|仿佛|宛如|犹如|如同|好似)(?:一位|一个|尊|座|名)?"
    r"[一-鿿]{0,4}?(?:智慧|睿智|慈祥|温和|宽容|公正|威严|永恒|不朽|沉默|冷峻|庄严|高高在上)?(?:的)?"
    r"(?:导师|智者|先知|审判者|裁决者|引路人|摆渡人|守夜人|君王|帝王|神明|圣人|哲人|预言者)")

# 12) adjacent-sentence-isomorph 相邻句同构（lieflat 第 3 条：AI 9.41/百段 vs 人类 4.81，
#     2.0×。字面判准：同段相邻两句逗号数相同（≥1）且长度差 ≤25%。语料校准修正：
#     ①一段内 ≥3 对才计（真人叙述里 2 对同构常见——凡人修仙传 700 章实测）；
#     ②骈文/古赋豁免（洛神赋式「肩若削成，腰如约素」四四对仗是文体传统）：段内无
#     的/了/着/是/很/就 等现代功能词的段落跳过。全章 ≥2 段才报。）
ISOMORPH_MIN_PAIRS_PER_PARA = 3
ISOMORPH_MIN_PARAS = 2
ISOMORPH_LEN_RATIO = 0.25
ISOMORPH_MODERN_RE = re.compile(r"[的了着是很就]")

# 13) zero-subject-comment 段首零主语评论（lieflat 第 11 条：AI 0.61% vs 人类 0.14%，
#     4.4×。非首段以评论语开头且全句无「这/那/其/此」回指——修法极轻：补回指词。）
ZERO_SUBJECT_OPENERS = re.compile(
    r"^(?:听起来|看起来|说起来|说白了|显然|无疑|当然|或许|似乎|换句话说|也就是说|事实上|"
    r"本质上|归根结底|值得一提|有意思的是|问题是|重点是|关键是|不得不说|可以说)")
ZERO_SUBJECT_MIN_HITS = 3

# 14) vague-rider 浅层伴随状语（humanizer #15：简单事实后拖一个「仿佛在诉说着…」
#     式空转状语显得深刻；与 gaze 视线词常共现。≥2 处报一条。）
VAGUE_RIDER = re.compile(
    r"(?:仿佛|似乎|好像|像是)(?:在)?(?:诉说着?|昭示着?|宣告着?|讲述着?)"
    r"|无声地(?:诉说|宣告|讲述)着?")
VAGUE_RIDER_MIN_HITS = 2

# 15) closer-recap-tic 例子后点题句（humanizer #2：一句话段落复述前段/例子后点题。
#     「这意味着」归 reasoning-chain 不双收；网文单句段是核心节奏手段——只在高密度
#     （≥3 处/章）时报，单句段形态由 one-line-para/stamp-para 管。）
CLOSER_RECAP_PATTERNS = [
    re.compile(r"这就是[^。！？!?\n]{0,16}"),
    re.compile(r"这(?:说明|证明|代表)了?[^。！？!?\n]{0,12}"),
    re.compile(r"那一刻[，,]?[^。！？!?\n]{0,8}(?:他|她|我)[^。！？!?\n]{0,6}(?:明白|懂了)"),
]
CLOSER_RECAP_MIN_HITS = 3

# 16) sendoff-para 送别段/章尾升华段（humanizer #13 送别段概念：末段 ≥2 个抽象名词
#     且零引号台词——整段落在最后一个具体事实上。advisory：真人也升华，AI 频率高得多。）
SENDOFF_NOUNS = re.compile(r"未来|希望|命运|黎明|明天|新篇章|新的人生|远方|尽头|光芒")
SENDOFF_MIN_NOUNS = 2
SENDOFF_MIN_CHARS = 20

# 17) recap-opening 章首复述前情（humanizer #26 换形适用：AI 高频开篇「上一章说到…」
#     把读者刚看完的内容再演一遍。只收开篇 400 可见字窗内的复述句式；跨章 N-gram
#     重叠版归 deslop_metrics 观测读数，不在正则域。）
RECAP_OPENING = re.compile(
    r"上一章(?:中|里)?说到|前情提要|前文(?:说到|提到)过?|回顾一?下"
    r"|还记得(?:昨天|上次|前一天)|此前发生(?:的|了)(?:事|一切)")
RECAP_WINDOW = 400


def scan_text(text: str) -> list:
    """扫描正文，返回 Finding 列表"""
    findings = []
    body = text
    # 去掉第一行标题
    if body.startswith("#"):
        nl = body.find("\n")
        if nl > 0:
            body_offset = nl + 1
            body = body[body_offset:]
        else:
            body_offset = 0
    else:
        body_offset = 0

    total_chars = max(len(body), 1)
    kilo = total_chars / 1000.0
    masked = _mask_quoted(body)      # 等长「？」占位——偏移不变，引号内豁免
    narration = _strip_quoted(body)  # 引号外叙述——密度分母/计数用（会移位，不定位）

    def add(rule, level, msg, m, hint=""):
        findings.append(Finding(
            rule=rule, level=level, message=msg,
            text=m.group(0), start=m.start() + body_offset, end=m.end() + body_offset,
            fix_hint=hint,
        ))

    def add_span(rule, level, msg, s, e, hit_text="", hint=""):
        findings.append(Finding(
            rule=rule, level=level, message=msg,
            text=hit_text, start=s + body_offset, end=e + body_offset,
            fix_hint=hint,
        ))

    # ---- Blocking 单句命中 ----
    for m in NOT_IS_PATTERN.finditer(body):
        add("not-is-comparison", "blocking", "「不是A，（而）是B」翻转句式（最毒）", m,
            "直接写 B，或拆成动作")
    for m in REVERSE_NOT_IS.finditer(body):
        # 排除 either-or 连词「不是A就是B」
        seg = m.group(0)
        if "就是" in seg or "也是" in seg:
            continue
        add("reverse-not-is", "blocking", "「是B，不是A」反序对比（not-is 变体）", m, "直接写 B")
    np_spans = []
    for pat in NEGATION_PARADE_PATTERNS:
        for m in pat.finditer(body):
            np_spans.append((m.start(), m.end()))
    for s, e in _dedup_spans(np_spans):
        add_span("negation-parade", "blocking", "「没有X，没有Y」否定排比", s, e, body[s:e],
                 "保留一项或改白描")
    for m in VOICE_CONTRAST.finditer(body):
        add("voice-contrast", "blocking", "「声音不大，却……」音量反差腔", m, "直接写台词内容或动作")
    for m in FLAT_VOICE.finditer(body):
        add("flat-voice", "blocking", "无情绪声线（毫无波澜/平静无波）", m, "写具体声音特征或动作")
    # trailer 族引号掩码后扫描（等长占位保偏移）——规则注释口径「引号内台词不计」
    # 的落地：台词里的「谁也不知道…」是角色说话不是叙述者预告（700 章真人语料校准：
    # 儒道至圣 台词命中 1 处为误报，掩码后消除）
    for m in _tail_window_hits(TRAILER_ENDING, masked):
        add("trailer-ending", "blocking", "「他不知道的是……」章末预告", m, "用具体钩子物件/事件收束")
    ts_spans = [(m.start(), m.end()) for m in _tail_window_hits(
        TRAILER_SUMMARY_PATTERNS[0], masked)]
    for pat in TRAILER_SUMMARY_PATTERNS[1:]:
        for m in _tail_window_hits(pat, masked):
            ts_spans.append((m.start(), m.end()))
    for s, e in _dedup_spans(ts_spans):
        add_span("trailer-summary", "blocking", "预告式总结收尾（才刚刚开始/没人知道…）", s, e,
                 body[s:e], "用未解决问题或具体动作收束")
    for m in FATE_SUMMARY.finditer(body):
        add("fate-summary", "blocking", "抽象命运总结（齿轮/棋局/这一刻终于明白）", m, "回到角色当下可见的动作/对话/物件")
    # 破折号：密度阈值策略（T2.3）——低密度属合法文风仅提示，高密度才是 AI 腔
    em_hits = list(EM_DASH.finditer(body))
    if len(em_hits) > kilo * 6:
        for m in em_hits:
            add("em-dash", "blocking",
                f"破折号高密度（{len(em_hits)} 处 / {kilo:.1f} 千字）", m,
                "用句号、逗号或动作断句")
    else:
        for m in em_hits:
            add("em-dash", "advisory", "破折号（低密度，文风容忍）", m,
                "追求紧凑可改句号断句；低密度不强制改写")

    # 「，带着……」万能状语：密度超阈值才算 blocking，单个为 advisory
    daizhe_hits = list(DAIZHE_ADVERB.finditer(body))
    daizhe_level = "blocking" if len(daizhe_hits) >= max(3, kilo * 1.5) else "advisory"
    for m in daizhe_hits:
        add("daizhe-adverb", daizhe_level, "「，带着……」万能状语", m, "删状语留主句，或换具体动作")

    # 一级禁用词：逐词命中
    cliche_total = 0
    for pat in CLICHE_PATTERNS:
        for m in pat.finditer(body):
            cliche_total += 1
            add("cliche-word", "blocking", f"一级禁用词「{m.group(0)}」", m,
                "替换为具体动作/白描")

    # 文言腔比喻标记：密度阈值型 advisory（lieflat Phase 2 降级，不再 blocking）。
    # 人类语料基线 1.78/千字（上游）/1.14/千字（corpus_pd 实测）；阈值 2/千字
    # 且 ≥4 处起报——人类文风零误报，AI 堆叠（3.21/千字）稳定触发。
    simile_hits = list(CLICHE_SIMILE.finditer(body))
    if len(simile_hits) >= max(4, kilo * 2):
        for m in simile_hits:
            add("simile-marker-density", "advisory",
                f"文言腔比喻标记高密度（仿佛/犹如/宛若/如同 {len(simile_hits)} 处"
                f" / {kilo:.1f} 千字）", m,
                "只留最有功能的一两个，其余改成动作/物件承接的具象描写")

    # 提示性冒号：提示语+冒号替自己说话（lieflat 规则 5；人类 0.08/千字，
    # AI 0.29——阈值 ≥max(2, 1/千字)，corpus_pd 18.4 千字人类语料实测 0 命中）
    colon_hits = [m for m in PROMPTING_COLON.finditer(body)
                  if not _in_dialogue(body, m.start())]
    if len(colon_hits) >= max(2, kilo * 1):
        for m in colon_hits:
            add("prompting-colon", "advisory",
                f"提示性冒号（核心是/关键在于…替自己说话 ×{len(colon_hits)}）", m,
                "删提示语直接写内容，或冒号换句号/逗号")

    # 顿号罗列密度：分句内 ≥2 顿号（≥3 并列项）为一条罗列句（lieflat 规则 2；
    # corpus_pd 人类实测 1.14/千字——阈值 2/千字且 ≥4 句起报，人类文风零误报）
    list_clauses = []
    for seg in re.split(r"[。！？!?；;" + chr(92) + "n]", body):
        if seg.count("、") >= 2:
            pos = body.find(seg)
            if pos >= 0 and not _in_dialogue(body, pos):
                list_clauses.append(seg.strip())
    if len(list_clauses) >= max(4, kilo * 2):
        findings.append(Finding(
            rule="dunhao-list-density", level="advisory",
            message=f"顿号罗列句高密度（{len(list_clauses)} 句 / {kilo:.1f} 千字，"
                    f"如「{list_clauses[0][:24]}…」）",
            text="", start=body_offset, end=body_offset,
            fix_hint="能概括就别逐项列举；必须保留时改变其中一项的句法结构",
        ))

    # 认知直接告知（密度超阈值才逐个报）
    cog_hits = list(TELLING_COGNITION.finditer(body))
    if len(cog_hits) >= 3:
        for m in cog_hits:
            add("telling-cognition", "advisory", "「他知道/她明白」直接告知认知", m,
                "用行为展示认知")

    # ---- Advisory 密度型 ----
    # 比喻密度
    metaphor_hits = list(METAPHOR_MARKERS.finditer(body))
    if len(metaphor_hits) >= max(7, kilo * 3):
        for m in metaphor_hits:
            add("metaphor-density", "advisory", "比喻密度过高（成片复现）", m,
                "只留最有功能的一两个，其余改直接描述")

    # 微动作复读
    micro_hits = [m for m in MICRO_TIC.finditer(body) if not _in_dialogue(body, m.start())]
    if len(micro_hits) >= max(5, kilo * 6):
        findings.append(Finding(
            rule="micro-action-tic", level="advisory",
            message=f"「V了下/V了一下」轻量补语高密度（{len(micro_hits)} 处），电报体指纹",
            text="", start=body_offset, end=body_offset,
            fix_hint="删减过头的补语，恢复自然连接",
        ))

    # 抽象总结复读
    abs_hits = []
    for pat in ABSTRACT_SUMMARY:
        abs_hits.extend(pat.finditer(body))
    if len(abs_hits) >= max(3, kilo * 4):
        for m in abs_hits:
            add("abstract-summary-tic", "advisory", "抽象总结复读（作者拔高腔）", m,
                "落回角色当下证据")

    # 解释链密度
    reason_hits = list(REASONING_CONNECTOR.finditer(body))
    if len(reason_hits) >= 3:
        for m in reason_hits:
            add("reasoning-chain", "advisory", "解释链连接词（替读者推理）", m,
                "回到角色当下证据")

    # 碎句号：连续 6 个以上 ≤5 字的叙述短句
    sentences = re.split(r"(?<=[。！？!?])", body)
    run = 0
    run_start = 0
    for i, s in enumerate(sentences):
        visible = re.sub(r"[\s，,、；;：:\"'“”「」]", "", s)
        if 0 < len(visible) <= 5 and not _in_dialogue(body, body.find(s)):
            if run == 0:
                run_start = body.find(s)
            run += 1
        else:
            if run >= 6:
                findings.append(Finding(
                    rule="period-stutter", level="advisory",
                    message=f"碎句号：连续 {run} 个短叙述句无呼吸",
                    text="", start=run_start + body_offset, end=run_start + body_offset + 50,
                    fix_hint="合并短句，增加句长变化",
                ))
            run = 0

    # 长段落：单段超 200 字
    for m in re.finditer(r"[^\n]{200,}", body):
        add("long-paragraph", "advisory",
            f"长段落（{len(m.group(0))} 字），建议按镜头断段", m, "")

    # 引号强调滥用
    quote_hits = [m for m in QUOTE_EMPHASIS.finditer(body)
                  if not _in_dialogue(body, m.start())]
    if len(quote_hits) >= 4:
        for m in quote_hits:
            add("quote-emphasis", "advisory", "叙述里短词加引号强调（密度型）", m,
                "去掉引号直接陈述")

    # ---- 结构层 AI 味（2026-08 真机语料分析新增：词表层已清洁，残留全在结构层）----

    # 视线词族密度（盯着/看向/望向/注视/目光合计 >1.5/千字 = 凝视循环镜头单一；
    # 语料基准：改命笔记 1.8/千字（仍被评「第一指纹」），时间当铺 2.9/千字，健康线 ≈1）
    gaze_hits = list(GAZE_MARKERS.finditer(body))
    if len(gaze_hits) >= max(5, kilo * 1.5):
        findings.append(Finding(
            rule="gaze-density",
            level="blocking" if len(gaze_hits) > kilo * 5 else "advisory",
            message=f"视线词族高密度（盯着/看向/目光等 {len(gaze_hits)} 处 / {kilo:.1f} 千字），凝视循环",
            text="", start=body_offset, end=body_offset,
            fix_hint="情绪与注意改用动作/物件/环境反应外化（指节抵着桌沿、茶凉了没喝）",
        ))

    # 否定刹车句族（「没有动/没有回头/没有说话」——短促否定节奏自重复）
    brake_hits = list(BRAKE_MARKERS.finditer(body))
    if len(brake_hits) >= max(4, kilo * 1.5):
        findings.append(Finding(
            rule="brake-sentence", level="advisory",
            message=f"「没有+动词」刹车句高密度（{len(brake_hits)} 处）",
            text="", start=body_offset, end=body_offset,
            fix_hint="全章最多保留 2 处，其余改为动作或对白呈现",
        ))

    # 否定刹车句独立成段（结构型：可预测的段落刹车）
    brake_paras = BRAKE_STANDALONE.findall(body)
    if len(brake_paras) >= 2:
        findings.append(Finding(
            rule="brake-standalone-para", level="advisory",
            message=f"「没有×」短句独立成段 ×{len(brake_paras)}（段落刹车模板化）",
            text="", start=body_offset, end=body_offset,
            fix_hint="同款刹车全章至多 1 次独立成段",
        ))

    # 单句碎段占比（≤15 字独立单句段 >45% = 节奏模板化；语料基准：改命笔记 29-31%）
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    if len(paras) >= 8 and total_chars > 1500:
        single = sum(1 for p in paras
                     if len(p) <= 15 and len(re.findall(r"[。！？!?…]", p)) <= 1)
        if single / len(paras) > 0.45:
            findings.append(Finding(
                rule="one-line-para", level="advisory",
                message=f"单句短段占比 {single}/{len(paras)}（{single / len(paras):.0%}），节奏模板化",
                text="", start=body_offset, end=body_offset,
                fix_hint="关联动作并成复合段，短段只留给关键转折",
            ))

    # 单词定性独句段（「循环。」「门锁着。」——两字定性+句号替代描写，同一写作模块复用）
    stamp_paras = [p2 for p2 in paras if re.fullmatch(r"[一-鿿]{1,4}[。！？]", p2)]
    if len(stamp_paras) >= 3:
        findings.append(Finding(
            rule="stamp-para", level="advisory",
            message=f"单词定性独句段 ×{len(stamp_paras)}（{'、'.join(stamp_paras[:4])}），描写被标签替代",
            text="", start=body_offset, end=body_offset,
            fix_hint="定性段全章至多 1 处；其余把标签还原成可拍摄的细节",
        ))

    # 「猛地」反应词窄库（惊觉模板复用）
    mengdi_hits = list(MENGDI.finditer(body))
    if len(mengdi_hits) >= max(4, kilo * 1.5):
        for m in mengdi_hits:
            add("mengdi-density", "advisory", "「猛地」反应词复用（惊觉模板）", m,
                "换具体身体反应或直接写动作")

    # ========== C1a 增量规则扫描（17 条，全部 advisory）==========
    # 引号外叙述可见字数（上游口径分母，供千字密度门）
    narr_chars = _visible_len(narration)

    # 1) negation-pair-tic「没A，也没B」否定对偶（补语尾排除）
    npair_hits = [m for m in NEGATION_PAIR.finditer(narration)
                  if not NEGATION_PAIR_COMPL_TAIL.search(m.group(1))]
    if len(npair_hits) >= NEGATION_PAIR_MIN_HITS:
        samples = " | ".join(m.group(0) for m in npair_hits[:4])
        findings.append(Finding(
            rule="negation-pair-tic", level="advisory",
            message=f"否定对偶偏多：「没A，也没B」式叙述 {len(npair_hits)} 处（{samples}）；"
                    f"写人物没做什么是英文式节奏",
            text="", start=body_offset, end=body_offset,
            fix_hint="改成他做了什么，留一两处真正要强调的否定即可",
        ))

    # 2) stock-reaction-tic 套式反应细节（7 模式，引号外）
    stock_hits = []
    for pat in STOCK_REACTION_PATTERNS:
        stock_hits.extend(pat.finditer(masked))
    if narr_chars and len(stock_hits) >= STOCK_REACTION_MIN_HITS \
            and len(stock_hits) / narr_chars * 1000 >= STOCK_REACTION_PER_KILO:
        samples = " | ".join(m.group(0) for m in stock_hits[:4])
        findings.append(Finding(
            rule="stock-reaction-tic", level="advisory",
            message=f"套式反应细节：指尖/指节/喉结/眼圈/声音放轻等通用反应 {len(stock_hits)} 处"
                    f"（{len(stock_hits) / narr_chars * 1000:.1f}/千字，{samples}）；"
                    f"逐处做删除测试",
            text="", start=body_offset, end=body_offset,
            fix_hint="只标注情绪、不改变选择/关系/物件/动作结果的删掉，不要换部位或同义动作",
        ))

    # 3) action-list-tic 监控摄像头式动作清单（段级）
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t):
            continue
        seg = _strip_quoted(t).strip()
        if not seg:
            continue
        verbs = ACTION_LIST_VERBS.findall(seg)
        if len(verbs) < ACTION_LIST_MIN_HITS:
            continue
        seps = len(re.findall(r"[，、；;]", seg))
        if seps < ACTION_LIST_MIN_SEPARATORS:
            continue
        findings.append(Finding(
            rule="action-list-tic", level="advisory",
            message=f"监控摄像头式动作清单：同段动作动词 {len(verbs)} 个、分隔符 {seps} 个",
            text="", start=off + body_offset, end=off + body_offset,
            fix_hint="合并琐碎步骤，只留有情绪/情节功能的动作；打斗等功能性编排可保留",
        ))

    # 4) system-notice-formality-tic 系统公告公文腔（整行【…】规则行）
    notice_lines = notice_hits = notice_core = 0
    notice_chars = 0
    notice_first = None
    notice_samples = []
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not NOTICE_LINE.match(t):
            continue
        notice_lines += 1
        notice_chars += _visible_len(t)
        notice_core += len(NOTICE_FORMAL_CORE.findall(t))
        for pat in NOTICE_FORMAL_PATTERNS:
            for m in pat.finditer(t):
                notice_hits += 1
                if notice_first is None:
                    notice_first = off
                if len(notice_samples) < 6 and m.group(0) not in notice_samples:
                    notice_samples.append(m.group(0))
    if (notice_lines >= NOTICE_FORMAL_MIN_LINES and notice_chars
            and notice_hits >= NOTICE_FORMAL_MIN_HITS
            and notice_core >= NOTICE_FORMAL_CORE_MIN_HITS
            and notice_hits / notice_chars * 1000 >= NOTICE_FORMAL_PER_KILO):
        findings.append(Finding(
            rule="system-notice-formality-tic", level="advisory",
            message=f"系统公告公文腔过密：{notice_lines} 行方括号规则行中硬规则词 "
                    f"{notice_hits} 处（{notice_hits / notice_chars * 1000:.0f}/千字，"
                    f"{'、'.join(notice_samples[:5])}）",
            text="", start=(notice_first or 0) + body_offset, end=(notice_first or 0) + body_offset,
            fix_hint="保留载体，把部分硬词改成白话或补角色当场看懂的具体后果；系统文题材可书级白名单豁免",
        ))

    # 5) overcompressed-prose-tic 过度精炼短段（四重与门）
    oc_paras = oc_short = oc_particles = 0
    oc_chars = 0
    oc_first = None
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t) or NOTICE_LINE.match(t):
            continue
        seg = _strip_quoted(t).strip()
        n = _visible_len(seg)
        if n == 0:
            continue
        if oc_first is None:
            oc_first = off
        oc_paras += 1
        oc_chars += n
        if n <= OVERCOMPRESSED_SHORT_MAX:
            oc_short += 1
        oc_particles += len(OVERCOMPRESSED_PARTICLE.findall(seg))
    if (oc_chars >= OVERCOMPRESSED_MIN_CHARS and oc_paras >= OVERCOMPRESSED_MIN_PARAS
            and oc_short / oc_paras >= OVERCOMPRESSED_SHORT_RATIO
            and oc_particles / oc_chars * 1000 < OVERCOMPRESSED_PARTICLE_PER_KILO):
        findings.append(Finding(
            rule="overcompressed-prose-tic", level="advisory",
            message=f"过度精炼短段：叙述段 {oc_paras} 个，其中 {oc_short} 个"
                    f"≤{OVERCOMPRESSED_SHORT_MAX} 字（{oc_short / oc_paras:.0%}），"
                    f"自然连接 {oc_particles / oc_chars * 1000:.1f}/千字偏少，像提纲/分镜表",
            text="", start=(oc_first or 0) + body_offset, end=(oc_first or 0) + body_offset,
            fix_hint="先通读判断，确有提纲感再补断裂处和必要结构虚词；有意短镜头可留，别机械注水",
        ))

    # 6) low-connective-density-tic 低连接密度（三重与门，引号外叙述）
    if narr_chars >= LOW_CONN_MIN_CHARS:
        func_hits = _count_terms(narration, LOW_CONN_FUNC_TERMS)
        plain_hits = _count_terms(narration, LOW_CONN_PLAIN_TERMS)
        narr_sents = [s for s in re.split(r"[。！？!?]+", narration) if s.strip()]
        long_ratio = (sum(1 for s in narr_sents
                          if _visible_len(s) >= LOW_CONN_LONG_SENT_CHARS) / len(narr_sents)
                      if narr_sents else 0.0)
        func_k = func_hits / narr_chars * 1000
        plain_k = plain_hits / narr_chars * 1000
        if (func_k < LOW_CONN_FUNC_PER_KILO and plain_k < LOW_CONN_PLAIN_PER_KILO
                and long_ratio < LOW_CONN_LONG_SENT_RATIO):
            findings.append(Finding(
                rule="low-connective-density-tic", level="advisory",
                message=f"低连接密度：引号外叙述功能词 {func_k:.1f}/千字、白话连接 "
                        f"{plain_k:.1f}/千字，≥{LOW_CONN_LONG_SENT_CHARS} 字承接句仅 "
                        f"{long_ratio:.0%}，像提纲/电报体",
                text="", start=body_offset, end=body_offset,
                fix_hint="通读后补必要连接和中长句群，别机械注水",
            ))

    # 7) formulaic-parallelism 工整并列（两模式逐处 + 跨段三行窗；叙述层——
    #    真人台词/指令里的否定清单是对话功能，不扫）
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t):
            continue
        seg_masked = _mask_quoted(t)
        for pat, msg in ((DECISION_FRAME, "「至于X不X，怎么X」把同一决定拆成工整栏目"),
                         (REPEATED_NEG_VERB, "同动词「不V A，不V B」否定清单")):
            for m in pat.finditer(seg_masked):
                if pat is REPEATED_NEG_VERB and (
                        ("不" + m.group(1)) in REPEATED_NEG_CONJ
                        or ("不" + m.group(1)[:1]) in REPEATED_NEG_CONJ):
                    continue
                add_span("formulaic-parallelism", "advisory", msg,
                         off + m.start(), off + m.end(), m.group(0),
                         "压成角色当下的一次判断或直接动作；台词内有功能可保留")
    # 跨段「不是A / 也不是B / 只是C」3 行滑窗（行距 ≤2 行，引号掩码后判）
    cross_win = []  # (raw_index, line_no, trimmed_masked, trimmed_raw)
    for idx, (ln, off) in enumerate(_body_lines(body)):
        t = ln.strip()
        if not t or _is_structural_line(t):
            cross_win = []
            continue
        if cross_win and idx - cross_win[-1][0] > 2:
            cross_win = []
        cross_win.append((idx, off, _mask_quoted(t), t))
        if len(cross_win) > 3:
            cross_win.pop(0)
        if len(cross_win) != 3:
            continue
        if (CROSS_NEG_START.match(cross_win[0][2]) and CROSS_NEG_MIDDLE.match(cross_win[1][2])
                and CROSS_NEG_END.match(cross_win[2][2])):
            findings.append(Finding(
                rule="formulaic-parallelism", level="advisory",
                message="跨段「不是… / 也不是… / 只是…」工整否定铺排（可能承担辩解或悬念排除）",
                text="", start=cross_win[0][1] + body_offset, end=cross_win[0][1] + body_offset,
                fix_hint="通读语境，只在重复细纲或拖慢画面时改写",
            ))

    # 8) cliche-density-tic 套词密度（二级词表，引号外叙述）
    cd_hits = []
    for pat in CLICHE_DENSITY_PATTERNS:
        cd_hits.extend(pat.finditer(narration))
    if narr_chars and len(cd_hits) >= CLICHE_DENSITY_MIN_HITS \
            and len(cd_hits) / narr_chars * 1000 >= CLICHE_DENSITY_PER_KILO:
        samples = " ".join(dict.fromkeys(m.group(0) for m in cd_hits))[:40]
        findings.append(Finding(
            rule="cliche-density-tic", level="advisory",
            message=f"套词密度过高：高危套词 {len(cd_hits)} 处"
                    f"（{len(cd_hits) / narr_chars * 1000:.1f}/千字，{samples}）",
            text="", start=body_offset, end=body_offset,
            fix_hint="不要同义词轮换，改成角色当下可见的动作、物件、对话和具体后果",
        ))

    # 9) forced-triad 强凑三连（同段同开头**恰三**复用；≥4 项是列举、全同是复沓，
    #    均豁免——700 章真人语料校准）
    triad_spans = []
    for m in FORCED_TRIAD.finditer(masked):
        op = m.group(1)
        if op[0] in "没不" or op in FORCED_TRIAD_ENUM_OPENERS:
            continue
        e = m.end()
        # 第 4 段同开头 → 枚举非凑三（第三段尾先于逗号，故先吞 ≤4 字段尾）
        m4 = re.match(r"[一-鿿]{0,4}\s*[，,]\s*" + re.escape(op), masked[e:])
        if m4:
            continue
        seg = m.group(0)
        parts = re.split(r"[，,]", seg)
        core = [re.sub(r"\s", "", p) for p in parts]
        # 三段全同 → 复沓修辞
        if len(core) == 3 and core[0] == core[1] == core[2]:
            continue
        triad_spans.append((m.start(), m.end()))
    if len(triad_spans) >= FORCED_TRIAD_MIN_HITS:
        for s, e in triad_spans:
            add_span("forced-triad", "advisory",
                     "强凑三连：同段三项以同一开头复用（同义堆叠凑数）", s, e, masked[s:e],
                     "各项语义不同→保留；同质堆叠→合并发展最强项或变化结构")

    # 10) sentence-opening-run 句首复读（引号外叙述句；拟声/惊叹连发与对话标签句
    #     不参与——只收句号收尾的陈述短句，700 章真人语料校准）
    sent_spans = [(m.start(), m.end(), m.group(0))
                  for m in re.finditer(r"[^。！？!?]+[。！？!]?", masked)]
    run_open = None
    run_len = 0
    run_start_pos = None

    def _flush_open_run():
        if run_len >= SENT_OPEN_MIN_RUN and run_start_pos is not None:
            add_span("sentence-opening-run", "advisory",
                     f"句首复读：连续 {run_len} 句以「{run_open}」开头且均为短句",
                     run_start_pos, run_start_pos,
                     hint="合并/换主语/以动作开头；有意排比（情绪峰值三连）可保留")

    for s, e, raw in sent_spans:
        st = raw.strip()
        vis = _visible_len(st)
        # 拟声/惊叹（咚！/砰！/后天二重！）与对话标签句（……方运道。）打断计数
        if not st.endswith("。") or (vis and _SENT_OPEN_TAG_TAIL.search(st)):
            _flush_open_run()
            run_open = None
            run_len = 0
            run_start_pos = None
            continue
        if vis == 0:
            continue
        opener = st[0] if st[0] in SENT_OPEN_PRONOUNS else (st[:2] if len(st) >= 2 else st[0])
        if vis <= SENT_OPEN_MAX_LEN and opener == run_open:
            run_len += 1
        else:
            _flush_open_run()
            run_open = opener if vis <= SENT_OPEN_MAX_LEN else None
            run_len = 1 if vis <= SENT_OPEN_MAX_LEN else 0
            run_start_pos = s if vis <= SENT_OPEN_MAX_LEN else None
    _flush_open_run()

    # 11) idealized-persona-simile 拟人化喻体（lieflat 7.3×/带修饰 12.6×）
    for m in IDEALIZED_SIMILE.finditer(masked):
        add("idealized-persona-simile", "advisory",
            "拟人化喻体：「像一位智慧的导师」式抽象角色比喻（AI 味最高倍率指纹 7.3×）", m,
            "换有具体来历/功能的人物对比，或直接写它做了什么")

    # 12) adjacent-sentence-isomorph 相邻句同构（lieflat 2.0×；一段 ≥3 对 + 现代语体
    #     护栏——骈文/古赋四四对仗是文体传统，700 章真人语料校准）
    iso_paras = 0
    iso_first = None
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t):
            continue
        seg = _strip_quoted(t)
        if not ISOMORPH_MODERN_RE.search(seg):
            continue  # 无现代功能词的段落=骈文/古赋语体，豁免
        sents = [s for s in re.split(r"[。！？!?]+", seg) if s.strip()]
        pairs = 0
        for a, b2 in zip(sents, sents[1:]):
            ca = a.count("，") + a.count(",")
            cb = b2.count("，") + b2.count(",")
            la, lb = _visible_len(a), _visible_len(b2)
            if ca >= 1 and ca == cb and la and lb \
                    and abs(la - lb) <= max(la, lb) * ISOMORPH_LEN_RATIO:
                pairs += 1
        if pairs >= ISOMORPH_MIN_PAIRS_PER_PARA:
            iso_paras += 1
            if iso_first is None:
                iso_first = off
    if iso_paras >= ISOMORPH_MIN_PARAS:
        findings.append(Finding(
            rule="adjacent-sentence-isomorph", level="advisory",
            message=f"相邻句同构：{iso_paras} 个段落内相邻句逗号数/长度同款复用（结构模板腔）",
            text="", start=(iso_first or 0) + body_offset, end=(iso_first or 0) + body_offset,
            fix_hint="变化句子结构：一句给动作、一句给反应，别让相邻句共用同一副骨架",
        ))

    # 13) zero-subject-comment 段首零主语评论（lieflat 4.4×）
    zs_hits = 0
    zs_first = None
    first_prose_seen = False
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t):
            continue
        seg = _strip_quoted(t).strip()
        if not seg:
            continue
        if not first_prose_seen:
            first_prose_seen = True
            continue
        first_sent = re.split(r"[。！？!?]", seg)[0]
        if ZERO_SUBJECT_OPENERS.match(first_sent) and not re.search(r"[这那其此]", first_sent):
            zs_hits += 1
            if zs_first is None:
                zs_first = off
    if zs_hits >= ZERO_SUBJECT_MIN_HITS:
        findings.append(Finding(
            rule="zero-subject-comment", level="advisory",
            message=f"段首零主语评论 ×{zs_hits}（评论语开头且无回指，像悬空的旁白）",
            text="", start=(zs_first or 0) + body_offset, end=(zs_first or 0) + body_offset,
            fix_hint="补回指词（这/那）或主语，把评论挂回具体对象——最小改动即可解",
        ))

    # 14) vague-rider 浅层伴随状语（humanizer #15）
    rider_hits = list(VAGUE_RIDER.finditer(masked))
    if len(rider_hits) >= VAGUE_RIDER_MIN_HITS:
        findings.append(Finding(
            rule="vague-rider", level="advisory",
            message=f"浅层伴随状语 ×{len(rider_hits)}（仿佛在诉说着…式空转深刻）",
            text="", start=rider_hits[0].start() + body_offset,
            end=rider_hits[0].end() + body_offset,
            fix_hint="删状语让事实自己站住，或把「诉说着什么」落成具体内容",
        ))

    # 15) closer-recap-tic 例子后点题句（humanizer #2）
    closer_hits = []
    for pat in CLOSER_RECAP_PATTERNS:
        closer_hits.extend(pat.finditer(masked))
    if len(closer_hits) >= CLOSER_RECAP_MIN_HITS:
        for m in closer_hits:
            add("closer-recap-tic", "advisory", "点题句复读（这就是……/这说明……替读者收束）", m,
                "信息增量为零的复述删掉；确有点题功能则换具体后果承载")

    # 16) sendoff-para 送别段/章尾升华段（humanizer #13）
    last_line = None
    for ln, off in _body_lines(body):
        t = ln.strip()
        if t and not _is_structural_line(t):
            last_line = (t, off)
    if last_line is not None:
        t, off = last_line
        seg = _strip_quoted(t).strip()
        if _visible_len(seg) >= SENDOFF_MIN_CHARS and not re.search(r"[「“【]", t):
            nouns = set(SENDOFF_NOUNS.findall(seg))
            if len(nouns) >= SENDOFF_MIN_NOUNS:
                findings.append(Finding(
                    rule="sendoff-para", level="advisory",
                    message=f"章尾升华段（抽象名词 {'、'.join(sorted(nouns))} 聚集且无具体事件落地）",
                    text="", start=off + body_offset, end=off + body_offset,
                    fix_hint="整段砍掉，落在最后一个具体事实上；钩子用未解决的事件不用大词",
                ))

    # 17) recap-opening 章首复述前情（humanizer #26，开篇窗）
    win_end = 0
    acc = 0
    for ln, off in _body_lines(body):
        t = ln.strip()
        if not t or _is_structural_line(t):
            continue
        seg = _strip_quoted(t)
        acc += _visible_len(seg)
        if acc >= RECAP_WINDOW:
            win_end = off + len(ln)
            break
        win_end = off + len(ln)
    for m in RECAP_OPENING.finditer(masked):
        if m.start() < win_end:
            add("recap-opening", "advisory",
                "章首复述前情（上一章说到…把读者刚看完的内容再演一遍）", m,
                "删复述，从新信息进入；确要回顾，压缩到一句并只留影响本章的成分")
        break

    return findings


# summarize_findings：S6a 起真身在 core.deslop_metrics（与度量层同处单一真源），
# 模块顶部已导入转发——调用面（deslop.summarize_findings）不变。


def findings_to_prompt_text(findings: list) -> str:
    """把扫描结果转成给 LLM 的文本（卡7：带规则 ID——改写稿复扫验收按规则 ID
    归零/降档计算；尾部附正例修法口径与负例守则，防「换措辞复发同族句式」）

    修法（fix_hint）即正例口径；负例统一收尾一句，不逐条膨胀 token。
    """
    lines = []
    for f in findings:
        if f.text:
            lines.append(f"- [{f.level}|{f.rule}] {f.message}：「{f.text}」→ 修法：{f.fix_hint}")
        else:
            lines.append(f"- [{f.level}|{f.rule}] {f.message} → 修法：{f.fix_hint}")
    if lines:
        lines.append("- 验收口径：每条命中按规则 ID 复扫，必须归零或至少降一档；"
                     "不许把 B 写成新的否定铺垫，也不许换个措辞复发同族句式。")
    return "\n".join(lines)
