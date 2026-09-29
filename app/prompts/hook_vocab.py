# -*- coding: utf-8 -*-
"""T2 钩子追读链账本——7 钩型受控词表 + 分档路由 + 解析落账纯函数（C34 段1）

来源与裁决（w2_methodology §5 / docs/落地计划附录B_引擎机制落点卡.md 卡4）：
- 钩子十三式+引子七式 **不原样内化**（无命中判据、约 5k 字超注入预算、留白式与
  去味红线冲突），提纯重写为 7 钩型受控词表；判据为自产表达，MIT 原文只作离线
  参考资料，不逐字进 prompt。
- 引子七式中「闪前碎片」「倒计时」两式并入细纲「章首钩子」填写指引
  （FIRST_HOOK_GUIDE），不新增独立引子段——格式契约「第一行章名，然后直接输出
  正文」不动；开局密度仍由 A8 开幕轮管辖。
- 钩型按细纲「章节定位」分档路由（HOOK_ROUTE）：高压/推进全 7 型；低压生活/
  信息整理只留 意象异变/情绪定格，且允许无钩（NO_HOOK_POSITIONS 白名单，
  对齐 lowkey 卡「留白收尾，不强求钩子」哲学）。

三处消费面（本卡只做词表 + 细纲字段注入 + 解析纯函数；stages/co_dialogue 的
落账与对账 **接线为 TODO**——B3/S2c 领地，数据形状在此冻结）：
1. 细纲模板（planning.py）：注入 HOOK_VOCAB_BLOCK / HOOK_TYPE_MENU /
   FIRST_HOOK_GUIDE；
2. 细纲解析落账：parse_hook_record → HookRecord.to_row()（「追踪/钩子账本.json」
   单行形状，卡4 schema 的超集）；
3. 账本侧纯函数：连弱钩检测 weak_hook_findings、枚举校验 validate_hook_row
   （钩型自报失真时的受控枚举兜底）。

注入纪律：HOOK_VOCAB_BLOCK / FIRST_HOOK_GUIDE 等会被拼接进 CHAPTER_OUTLINE_PROMPT，
随后整体走 str.format()——**这些块内禁止出现 ASCII 花括号**（tests/unit/
test_hook_ledger.py 有钉测）。
"""
import re
from dataclasses import dataclass

# ========== 受控词表（封闭枚举） ==========

# 7 钩型：唯一账本枚举值；顺序即展示顺序。任何一型不得是另一型的子串（解析按子串
# 命中，子串相撞会误判——test_hook_ledger 有钉测）。
HOOK_TYPES = ("悬念缺口", "危机迫近", "反转揭示", "两难抉择", "承诺威胁", "意象异变", "情绪定格")

# 每型一条命中判据（可检验的成立条件）：进细纲词表块、未来 F 维 rubric 与账本枚举。
# 键集必须与 HOOK_TYPES 完全相等（封闭性，钉测）。
HOOK_TYPE_CRITERIA = {
    "悬念缺口": "本章内抛出一个读者必须往后翻才能闭合的具体问题（谁/什么/为什么任一），且本章不给出答案",
    "危机迫近": "存在明确时限或逼近中的威胁，且本章结束时该威胁未解除",
    "反转揭示": "本章揭出一层新事实，且该事实推翻读者或主角此前持有的一个明确判断",
    "两难抉择": "主角面对两个及以上选项，每个选项都有真实代价，且本章未替读者消除代价",
    "承诺威胁": "以承诺/誓言/交易/威胁开出一张未来必须兑现或引爆的债，且写明指向的对象或事件",
    "意象异变": "已登场的具体物件/场景/习惯出现可指认的异常变化，且该异常指向尚未解释的后果",
    "情绪定格": "章末停在一个高浓度的情绪画面/动作/台词上，不解释、不收束，把情绪悬置带进下一章",
}

# 期待度三档（沿用原细纲字段口径，不扩档）
HOOK_STRENGTHS = ("强", "中", "弱")

# 细纲「章节定位」枚举（planning.py 章节定位字段的六个取值，分档路由的输入）
OUTLINE_POSITIONS = ("高压", "推进", "修炼试错", "关系回收", "低压生活", "信息整理")

# 账本行「钩子定位」枚举：章首 / 章尾（跨章「钩子未应」对账以章尾行为主键）
HOOK_POSITIONS = ("章首", "章尾")

# 分档路由：章节定位 → 本章可用钩型。低压两档只留意象异变/情绪定格（lowkey 哲学）；
# 修炼试错留瓶颈/险情/异象向四型；关系回收留承诺/抉择/情绪向四型。
HOOK_ROUTE = {
    "高压": HOOK_TYPES,
    "推进": HOOK_TYPES,
    "修炼试错": ("悬念缺口", "危机迫近", "反转揭示", "意象异变"),
    "关系回收": ("悬念缺口", "两难抉择", "承诺威胁", "情绪定格"),
    "低压生活": ("意象异变", "情绪定格"),
    "信息整理": ("意象异变", "情绪定格"),
}

# 无钩白名单：低张力章允许章尾钩子写「无」（须写明读者往下看的理由）。
# 对齐 scene_cards lowkey 卡「留白收尾，不强求钩子」；连弱钩检测对白名单章让行。
NO_HOOK_POSITIONS = ("低压生活", "信息整理")


def route_hook_types(outline_position: str) -> tuple:
    """章节定位 → 可用钩型元组；未知/空定位 fail-open 放开全 7 型（不硬拦）"""
    return HOOK_ROUTE.get((outline_position or "").strip(), HOOK_TYPES)


def no_hook_allowed(outline_position: str) -> bool:
    """低张力章白名单：允许章尾无钩（低压生活/信息整理）"""
    return (outline_position or "").strip() in NO_HOOK_POSITIONS


# ========== prompt 注入块（禁止 ASCII 花括号，见模块 docstring） ==========

# 章尾钩子行的钩型菜单（planning.py 章尾钩子字段用）
HOOK_TYPE_MENU = "/".join(HOOK_TYPES)

# 章首钩子填写指引（原字段是空壳）：引子七式「闪前碎片」「倒计时」并入于此，
# 不新增独立引子段（w2_methodology §5 裁决）。
FIRST_HOOK_GUIDE = ("首 500 字内落地的事件/异象/数字压力；可用「闪前碎片」——先亮后文场景的"
                    "一角再倒回现场，或「倒计时」——写明期限与剩余量；禁止纯环境白描开场")


def _render_route_lines() -> str:
    """HOOK_ROUTE → 一行分档路由文本（同档相邻定位合并，顺序稳定）"""
    keys = list(HOOK_ROUTE)
    parts = []
    i = 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and HOOK_ROUTE[keys[j + 1]] == HOOK_ROUTE[keys[i]]:
            j += 1
        label = "/".join(keys[i:j + 1])
        types = HOOK_ROUTE[keys[i]]
        rhs = "七型皆可" if set(types) == set(HOOK_TYPES) else "仅 " + "/".join(types)
        parts.append(f"{label}→{rhs}")
        i = j + 1
    return "；".join(parts)


# 细纲模板注入的词表块（planning.py 在「## 输出格式」前拼接）
HOOK_VOCAB_BLOCK = (
    "## 钩型受控词表（章尾钩子的「钩型」必须从下列七型中选一，按「章节定位」分档可用）\n"
    + "\n".join(f"- {t}：{HOOK_TYPE_CRITERIA[t]}" for t in HOOK_TYPES)
    + "\n钩型分档路由：" + _render_route_lines() + "。\n"
    "低压生活/信息整理章不强求钩子：章尾钩子可写「无」，但必须写明读者往下看的理由。\n"
    "选型要求：钩型必须与判据相符——填「危机迫近」本章就得真有时限或逼近中的威胁且未解除，"
    "乱填型别会在审校复核时打回。"
)


# ========== 解析落账：账本行 schema + 纯函数 ==========

# 钩子账本单行的字段冻结（卡4 侧书 schema {"num","type","strength","is_event_hook",
# "event_kw"} 的超集；多出 position/summary/outline_position 三列）。
HOOK_ROW_KEYS = ("num", "position", "type", "strength", "summary",
                 "event_kw", "is_event_hook", "outline_position")


@dataclass(frozen=True)
class HookRecord:
    """钩子账本单行（「追踪/钩子账本.json」的行形状，落账/对账接线方按此消费）。

    - num：章号；position：HOOK_POSITIONS 之一（章首/章尾，跨章对账以章尾行的主键）；
    - type：HOOK_TYPES 之一；模型未填/乱填 → ""（落账侧 fail-open，待 F 维回写修正）；
    - strength：HOOK_STRENGTHS 之一；章首钩无烈度档或未填 → ""；
    - summary：钩子内容一句概括（去「期待度/钩型」标签后的原句）；
    - event_kw：1-2 个事件关键词（「」『』引文优先；无引文 → "" 弃权转 LLM 轨，
      不硬判——卡4 风险②）；is_event_hook：有 event_kw 即事件钩（F 维可回写覆盖）；
    - outline_position：该章「章节定位」档（白名单让行的判定输入）。
    """
    num: int
    position: str = "章尾"
    type: str = ""
    strength: str = ""
    summary: str = ""
    event_kw: str = ""
    is_event_hook: bool = False
    outline_position: str = ""

    def to_row(self) -> dict:
        return {k: getattr(self, k) for k in HOOK_ROW_KEYS}


# 细纲「章节定位」行（截到行内第一个分隔符；再对 OUTLINE_POSITIONS 做包含归一）
_POS_LINE_RE = re.compile(r"章\s*节\s*定\s*位\s*[：:][ \t]*([^\n（(；;，,。]{1,16})")

# 钩子字段行：兼容 - /* 前缀与「章尾/章末/章首」变体（模型输出两种都见过）
_HOOK_LINE_RES = {
    "章首": re.compile(r"^[ \t]*[-*·]*[ \t]*章首钩子[ \t]*[：:](.*)$", re.M),
    "章尾": re.compile(r"^[ \t]*[-*·]*[ \t]*章[尾末]钩子[ \t]*[：:](.*)$", re.M),
}

# 「期待度：强/中/弱」三档提取
_STRENGTH_RE = re.compile(r"期待度\s*[：:]\s*([强中弱])")

# 一句概括的截断点：从第一个结构标签起不算概括内容
_SUMMARY_CUT_RE = re.compile(r"[（(；;，,]?\s*(?:期待度|钩型|与下一章|承接)")

# 事件关键词：优先引文（「」『』""''），单条 2-24 字，最多 2 条
_EVENT_KW_RE = re.compile(r"[「『“\"']([^「」『』“”\"']{2,24})[」』”\"']")


def extract_outline_position(outline_text: str) -> str:
    """细纲文本 → 章节定位档（OUTLINE_POSITIONS 之一；识别不出 → ""）"""
    m = _POS_LINE_RE.search(outline_text or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    for pos in OUTLINE_POSITIONS:
        if pos in raw:
            return pos
    return ""


def extract_hook_type(text: str) -> str:
    """自由文本 → 7 型之一；无命中 → ""（封闭性：只可能返回枚举值或空串）"""
    text = text or ""
    for t in HOOK_TYPES:
        if t in text:
            return t
    return ""


def extract_hook_strength(text: str) -> str:
    """自由文本 → 期待度三档之一；无「期待度：」标注 → """""
    m = _STRENGTH_RE.search(text or "")
    return m.group(1) if m else ""


def _clean_summary(raw: str) -> str:
    """钩子行原文 → 一句概括：截掉「期待度/钩型/承接」标签段，去首尾分隔符"""
    text = (raw or "").strip()
    m = _SUMMARY_CUT_RE.search(text)
    if m:
        text = text[:m.start()]
    return text.strip().strip("；;，,。 ").strip()


def _event_kw(summary: str) -> str:
    """概括 → 事件关键词（引文优先，最多 2 条，「|」相连；无引文弃权 → ""）"""
    kws = [k.strip() for k in _EVENT_KW_RE.findall(summary or "") if k.strip()]
    return "|".join(kws[:2])


def parse_hook_record(num: int, outline_text: str, position: str = "章尾",
                      outline_position: str = "") -> HookRecord:
    """一章细纲文本 → HookRecord（账本单行）。

    position="章首" 解析「- 章首钩子：」行，"章尾" 解析「- 章尾/章末钩子：」行；
    行缺失时返回全空字段记录（fail-open，由账本侧判弱钩）。outline_position 缺省时
    自动从细纲「章节定位：」行识别。
    """
    text = outline_text or ""
    if not outline_position:
        outline_position = extract_outline_position(text)
    raw = ""
    line_re = _HOOK_LINE_RES.get(position)
    if line_re:
        m = line_re.search(text)
        if m:
            raw = m.group(1)
    summary = _clean_summary(raw)
    event_kw = _event_kw(summary)
    return HookRecord(
        num=num, position=position if position in HOOK_POSITIONS else "章尾",
        type=extract_hook_type(raw), strength=extract_hook_strength(raw),
        summary=summary, event_kw=event_kw, is_event_hook=bool(event_kw),
        outline_position=outline_position,
    )


def weak_hook_findings(rows: list, window: int = 2) -> list:
    """连弱钩检测（纯函数段；账本接线 TODO 的裁决内核，卡4：近 2 章全弱钩 → 核对级）。

    rows：账本行列表（HookRecord.to_row() 形状；乱序可、缺章可、只看章尾行）。
    弱行 = 烈度为「弱」或非事件钩；章号须相邻（差 1）才计连排；一段弱行连排 ≥window
    章产出一条核对级 finding（长连排只报一条，nums 标出区间）。
    白名单让行：整段连排都落在 NO_HOOK_POSITIONS 章（低张力章）时不报——
    无钩/弱钩本就是这些章的允许态。
    """
    ordered = sorted((r for r in rows if r.get("position", "章尾") == "章尾"),
                     key=lambda r: r.get("num", 0))
    runs, cur, prev = [], [], None
    for r in ordered:
        num = r.get("num")
        weak = (r.get("strength") == "弱") or (not r.get("is_event_hook"))
        if weak and cur and prev is not None and num == prev + 1:
            cur.append(r)
        elif weak:
            if len(cur) >= window:
                runs.append(cur)
            cur = [r]
        else:
            if len(cur) >= window:
                runs.append(cur)
            cur = []
        prev = num
    if len(cur) >= window:
        runs.append(cur)
    findings = []
    for run in runs:
        if all(str(r.get("outline_position", "")) in NO_HOOK_POSITIONS for r in run):
            continue
        nums = [r.get("num") for r in run]
        findings.append({
            "level": "核对级", "kind": "连弱钩", "nums": nums,
            "text": f"第{nums[0]}-{nums[-1]}章连续 {len(run)} 章弱钩/非事件钩，追读链衰减",
        })
    return findings


def validate_hook_row(row: dict) -> list:
    """账本行受控枚举校验（钩型自报失真的兜底，卡4 风险③）→ 问题列表（空 = 合格）"""
    problems = []
    num = row.get("num")
    if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
        problems.append(f"num 非法：{num!r}")
    if row.get("position", "章尾") not in HOOK_POSITIONS:
        problems.append(f"position 不在枚举：{row.get('position')!r}")
    if row.get("type", "") and row["type"] not in HOOK_TYPES:
        problems.append(f"钩型不在七型枚举：{row.get('type')!r}")
    if row.get("strength", "") and row["strength"] not in HOOK_STRENGTHS:
        problems.append(f"期待度不在三档：{row.get('strength')!r}")
    if row.get("outline_position", "") and row["outline_position"] not in OUTLINE_POSITIONS:
        problems.append(f"章节定位不在枚举：{row.get('outline_position')!r}")
    if bool(row.get("is_event_hook")) != bool(row.get("event_kw")):
        problems.append("is_event_hook 与 event_kw 不一致")
    return problems
