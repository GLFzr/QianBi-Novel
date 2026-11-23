# -*- coding: utf-8 -*-
"""ChapterDirective 章纲合同（0.20.3 A1）：细纲从自由 markdown 升级为可校验合同。

思想来源：T1 报告 §2.3/§2.4/§3.3（chapter_outline_loader 的 17 字段 schema）——
「大纲先结构化，才谈得上即法律」。本模块是**纯函数域，零项目内依赖**（只 import
标准库），被 stages 接线前必须保持零依赖（D-stages 批从 _mc_assemble 调用）。

17 字段（与 T1 报告 chapter_directive schema 一一对应）：
    goal 目标 / obstacles 阻力 / cost 代价 / time_anchor 时间锚点 /
    chapter_span 跨度 / countdown 倒计时 / cbn 承接节点 / cpns 推进节点 /
    cen 章末节点 / must_cover_nodes 必须覆盖节点 / forbidden_zones 本章禁区 /
    chapter_end_open_question 章末未闭合问题 / hook_type 钩型 / hook_strength 钩子强度 /
    key_entities 关键实体 / strand 主线归属 / antagonist_tier 反派层级

节点三件套（T1 §8.3）：CBN 每章 1 个承接上章 CEN；CPNs 2-4 个按时间序；
CEN 1 个落到章末未闭合问题。格式「主体 | 动作/变化 | 对象/结果」由 prompt 层
约定，解析层宽容存字符串（结构拆解留给下游，不在本模块造语法）。

容错原则（T1 #143/#139/#141 洞察）：**未知字段保留进 extra（v7 容错读取）**，
缺字段=None，畸形输入绝不抛异常（parse 层面）。
挂点 TODO（D-stages 批，本卡不做）：_mc_assemble 读细纲后调
parse_directive(outline_text) → validate_directive 缺字段清单进 ctx.log warn；
directive 实例灌进状态卡 must 节 + 审校 prompt 附 planned_nodes（见研究报告
A1 行落点；A2 覆盖拒收在 _mc_review+finalize 消费 must_cover_nodes）。
"""
import json
import re
from dataclasses import dataclass, field as dc_field

# --------------------------------------------------------------------------
# 17 字段 schema（单一出处：FIELD_SPECS 驱动解析映射/校验/菜单/合同块四处）
# --------------------------------------------------------------------------

# kind: scalar=单值 / list=列表（顿号逗号分号或换行条目切分）
FIELD_SPECS = {
    # 字段:            (中文名,      kind,    说明)
    "goal":          ("目标",       "scalar", "本章核心目标/核心事件：谁要对谁做什么（一句话）"),
    "obstacles":     ("阻力",       "scalar", "主要阻力与对抗方（谁/什么在拦）"),
    "cost":          ("代价",       "scalar", "推进或失败的代价（压力来源）"),
    "time_anchor":   ("时间锚点",   "scalar", "本章故事时间（「主线第 X 日」口径，与已有章节对齐）"),
    "chapter_span":  ("跨度",       "scalar", "本章覆盖的故事时间跨度/章长方向"),
    "countdown":     ("倒计时",     "scalar", "本章处于哪个 D-N 倒计时/期限压力下（无则写无）"),
    "cbn":           ("承接节点",   "scalar", "CBN：本章开头节点，1 个，必须承接上章 CEN"),
    "cpns":          ("推进节点",   "list",   "CPNs：中段推进节点 2-4 个，按时间序"),
    "cen":           ("章末节点",   "scalar", "CEN：章末节点，1 个，落到章末未闭合问题"),
    "must_cover_nodes": ("必须覆盖节点", "list", "大纲即法律的核对清单：本章必演节点（≤4，正文缺失即拒收依据）"),
    "forbidden_zones":  ("本章禁区",      "list", "硬禁区：本章不得出现的内容（≤5；含禁止提前释放项）"),
    "chapter_end_open_question": ("章末未闭合问题", "scalar", "本章留给下一章的未闭合问题"),
    "hook_type":     ("钩型",       "scalar", "章尾钩型：七型受控词表之一（判据见 hook_vocab）"),
    "hook_strength": ("钩子强度",   "scalar", "期待度：强/中/弱（审校 F 维回写为权威值）"),
    "key_entities":  ("关键实体",   "list",   "本章关键实体/出场角色（占位符防线按此求交）"),
    "strand":        ("主线归属",   "scalar", "本章服务的主线/支线/感情线归属"),
    "antagonist_tier": ("反派层级", "scalar", "本章对手层级（压强标定）"),
}
FIELD_ORDER = tuple(FIELD_SPECS)                      # 17 字段权威顺序
LIST_FIELDS = tuple(f for f, s in FIELD_SPECS.items() if s[1] == "list")

# 必填核心（缺任一 → validate_directive fail 候选清单）：大纲即法律的机器抓手——
# goal/节点三件套/must_cover_nodes/章末问题是覆盖校验与钩子账本的输入；
# 时间锚点进时间线对账；钩型/强度是账本权威值的自报基线。
REQUIRED_FIELDS = ("goal", "time_anchor", "cbn", "cpns", "cen",
                   "must_cover_nodes", "chapter_end_open_question",
                   "hook_type", "hook_strength")

# 中英字段名映射表（T1 §2.4：中英字段名映射表是「大纲可校验」的前提）。
# 归一化后的标签 → 字段。半角全角冒号、大小写、空白差异在 _norm_label 处理。
_LABEL_ALIASES = {
    "goal": "goal", "目标": "goal", "本章目标": "goal", "核心目标": "goal",
    "核心事件": "goal", "本章核心事件": "goal", "主角目标": "goal",
    "主角目标/关键选择": "goal", "目标/核心事件": "goal",
    "obstacles": "obstacles", "阻力": "obstacles", "障碍": "obstacles",
    "主要阻力": "obstacles", "对抗力量": "obstacles",
    "cost": "cost", "代价": "cost",
    "time_anchor": "time_anchor", "时间锚点": "time_anchor", "时间戳": "time_anchor",
    "头部时间戳": "time_anchor", "时间线锚点": "time_anchor",
    "chapter_span": "chapter_span", "跨度": "chapter_span", "章节跨度": "chapter_span",
    "故事跨度": "chapter_span", "章长方向": "chapter_span", "章长": "chapter_span",
    "countdown": "countdown", "倒计时": "countdown", "期限": "countdown",
    "cbn": "cbn", "承接节点": "cbn", "承接": "cbn", "开章节点": "cbn", "开场节点": "cbn",
    "cpns": "cpns", "cpn": "cpns", "推进节点": "cpns", "中段节点": "cpns",
    "中段推进节点": "cpns", "推进节点序列": "cpns",
    "cen": "cen", "章末节点": "cen", "收束节点": "cen", "收尾节点": "cen", "章末落点": "cen",
    "must_cover_nodes": "must_cover_nodes", "必须覆盖节点": "must_cover_nodes",
    "必演节点": "must_cover_nodes", "必须覆盖": "must_cover_nodes",
    "必覆盖节点": "must_cover_nodes", "核心节点": "must_cover_nodes",
    "forbidden_zones": "forbidden_zones", "本章禁区": "forbidden_zones", "禁区": "forbidden_zones",
    "禁止提前释放": "forbidden_zones", "本章禁止提前释放": "forbidden_zones", "硬禁区": "forbidden_zones",
    "chapter_end_open_question": "chapter_end_open_question",
    "章末未闭合问题": "chapter_end_open_question", "未闭合问题": "chapter_end_open_question",
    "章末悬念": "chapter_end_open_question", "章末开放问题": "chapter_end_open_question",
    "hook_type": "hook_type", "钩型": "hook_type", "钩子类型": "hook_type",
    "钩子": "hook_type", "章尾钩型": "hook_type",
    "hook_strength": "hook_strength", "期待度": "hook_strength", "钩子强度": "hook_strength",
    "烈度": "hook_strength", "强度": "hook_strength",
    "key_entities": "key_entities", "关键实体": "key_entities", "出场角色": "key_entities",
    "出场人物": "key_entities", "关键角色": "key_entities", "本章实体": "key_entities",
    "strand": "strand", "主线归属": "strand", "主线": "strand", "线归属": "strand", "剧情线": "strand",
    "antagonist_tier": "antagonist_tier", "反派层级": "antagonist_tier",
    "对手层级": "antagonist_tier", "反派强度": "antagonist_tier", "反派档次": "antagonist_tier",
}

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def cn_num_to_int(s: str):
    """中文数字 → int（「一百零三」「两千零五」单位制解析）；非中文数字返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, segment, seen = 0, 0, False
    for ch in s:
        if ch in _CN_DIGITS:
            segment = _CN_DIGITS[ch]
            seen = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit >= 10000:
                total = (total + segment) * unit
            else:
                total += (segment or 1) * unit
            segment = 0
            seen = True
        else:
            return None
    return total + segment if seen else None


def _norm_label(label: str) -> str:
    """标签归一：去空白/全半角冒号句号/统一小写（英文键）。"""
    t = (label or "").strip().lower()
    t = t.rstrip("：:。．.： ")
    t = re.sub(r"\s+", "", t)
    return t


def _split_list(value: str) -> list:
    """顿号/逗号/分号/换行条目切分，去空去重保序。

    注意：`|`、`｜`、`/` **不是**分隔符——节点三件套「主体 | 动作/变化 | 对象/结果」
    格式内含竖线与斜杠，切掉会把一个节点撕成三段。
    """
    parts = re.split(r"[、，,；;\n]+", value)
    out = []
    for p in parts:
        p = p.strip().strip("·-—* ").strip()
        if p and p not in out:
            out.append(p)
    return out


def _coerce(kind: str, value):
    """按字段类型把原始值收敛成 scalar(str|None) / list(list|None)。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = _split_list("；".join(str(v) for v in value if str(v).strip())) \
            if kind == "list" else None
        if kind != "list":
            joined = "；".join(str(v) for v in value if str(v).strip())
            return joined or None
        return items or None
    text = str(value).strip()
    if not text or text in ("无内容", "（未声明）"):
        return None
    return _split_list(text) or None if kind == "list" else text


@dataclass
class ChapterDirective:
    """章纲合同实例：17 字段 + 章号 + 容错保留的未知字段（v7 原则）。"""
    chapter_num: int | None = None
    goal: str | None = None
    obstacles: str | None = None
    cost: str | None = None
    time_anchor: str | None = None
    chapter_span: str | None = None
    countdown: str | None = None
    cbn: str | None = None
    cpns: list | None = None
    cen: str | None = None
    must_cover_nodes: list | None = None
    forbidden_zones: list | None = None
    chapter_end_open_question: str | None = None
    hook_type: str | None = None
    hook_strength: str | None = None
    key_entities: list | None = None
    strand: str | None = None
    antagonist_tier: str | None = None
    extra: dict = dc_field(default_factory=dict)

    def missing_required(self) -> list:
        """缺字段 fail 候选清单（与 validate_directive 同口径）。"""
        return validate_directive(self)

    def to_dict(self) -> dict:
        d = {"chapter_num": self.chapter_num}
        for f in FIELD_ORDER:
            d[f] = getattr(self, f)
        return d


# --------------------------------------------------------------------------
# 解析：JSON / 结构化文本 双形态，宽容降级，畸形输入不炸
# --------------------------------------------------------------------------

_JSON_KEY_ALIASES = {k: v for k, v in _LABEL_ALIASES.items()}


def _try_json(text: str):
    """全文或文中首个平衡 {} 块尝试 json.loads；成功返回 dict 否则 None。"""
    candidates = []
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        candidates.append(m.group(1))
    l, r = text.find("{"), text.rfind("}")
    if 0 <= l < r:
        candidates.append(text[l:r + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _apply_mapping(directive: "ChapterDirective", mapping: dict) -> None:
    """字段映射表 → ChapterDirective 赋值；未知键进 extra（v7 容错保留）。"""
    for raw_key, raw_val in mapping.items():
        norm = _norm_label(str(raw_key))
        if norm == "chapter_num":
            n = int(raw_val) if isinstance(raw_val, (int, float)) else cn_num_to_int(str(raw_val))
            if n:
                directive.chapter_num = n
            continue
        fname = _JSON_KEY_ALIASES.get(norm)
        if fname is None:
            directive.extra[str(raw_key)] = raw_val
            continue
        kind = FIELD_SPECS[fname][1]
        setattr(directive, fname, _coerce(kind, raw_val))


_CH_HEADER_RE = re.compile(r"={2,}\s*第\s*(\d+)\s*章\s*={2,}|^#{1,4}\s*第\s*(\d+)\s*章|^第\s*([一二三四五六七八九十百千零〇两\d]+)\s*章")
_LABEL_LINE_RE = re.compile(r"^\s*(?:[-*•·]\s*)?(?:#{2,5}\s*)?([^：:]{1,24})[：:]\s*(.*)$")


def _detect_chapter_num(text: str):
    for line in text.splitlines():
        m = _CH_HEADER_RE.search(line.strip())
        if m:
            for g in m.groups():
                if g is None:
                    continue
                n = int(g) if str(g).isdigit() else cn_num_to_int(str(g))
                if n:
                    return n
    return None


def parse_directive(text: str, chapter_num: int | None = None) -> ChapterDirective:
    """细纲文本 → ChapterDirective（宽容解析，任何输入都不抛异常）。

    双形态：
    1. JSON 形态——全文/围栏代码块/首尾平衡花括号块为 JSON 对象（键可为英文
       字段名或中文标签；允许嵌套在 "chapter_directive" 键下）；
    2. 结构化文本形态——逐行扫描「标签：值」行（-/*/•/## 前缀皆容），列表字段
       按顿号逗号分号切分；标签命中映射表才入字段，未命中进 extra。
    缺字段=None；chapter_num 未显式给出时从「第N章」头探测（支持中文数字）。
    """
    d = ChapterDirective(chapter_num=chapter_num)
    text = text or ""
    try:
        if not chapter_num:
            d.chapter_num = _detect_chapter_num(text)
    except Exception:                                    # noqa: BLE001
        d.chapter_num = chapter_num

    data = None
    try:
        data = _try_json(text)
    except Exception:                                    # noqa: BLE001
        data = None
    if data is not None:
        inner = data.get("chapter_directive") if isinstance(data.get("chapter_directive"), dict) else data
        try:
            _apply_mapping(d, inner if isinstance(inner, dict) else {})
        except Exception:                                # noqa: BLE001
            pass
        return d

    # 结构化文本形态
    try:
        for line in text.splitlines():
            m = _LABEL_LINE_RE.match(line)
            if not m:
                continue
            label_raw, value_raw = m.group(1), m.group(2)
            fname = _LABEL_ALIASES.get(_norm_label(label_raw))
            if fname is None:
                # 章名行「### 第 N 章：XXX」的标签部分归一后不命中 → 忽略（不进
                # extra，避免章名/正文叙述行污染扩展位）
                continue
            value = value_raw.strip()
            kind = FIELD_SPECS[fname][1]
            if value:
                setattr(d, fname, _coerce(kind, value))
            elif kind == "list" and getattr(d, fname) is None:
                setattr(d, fname, [])          # 空值列表字段占位，等后续无（缺字段校验仍按内容判）
    except Exception:                                    # noqa: BLE001
        pass
    return d


# --------------------------------------------------------------------------
# 校验 / 渲染
# --------------------------------------------------------------------------

def validate_directive(directive: ChapterDirective) -> list:
    """必填校验：返回缺失必填字段的 fail 候选清单（FIELD_ORDER 序，英文键）。

    空列表 [] = 合同完备；非空 = 每项是一条可上报的缺字段候选（A2 覆盖拒收/
    ctx 警告的消费形态由接线批决定，本函数只产清单不落库）。
    """
    if directive is None:
        return list(REQUIRED_FIELDS)
    missing = []
    for f in REQUIRED_FIELDS:
        v = getattr(directive, f, None)
        if v is None or (isinstance(v, (list, str)) and not v):
            missing.append(f)
    return missing


def to_prompt_block(directive: ChapterDirective) -> str:
    """ChapterDirective → 可注入写作/审校 prompt 的合同块（含全部 17 字段名）。

    缺字段渲染为（未声明）；列表字段以顿号连接。块内零 ASCII 花括号——调用方
    可能把它拼进 .format() 模板（与 hook_criteria_block 同一纪律）。
    """
    d = directive or ChapterDirective()
    lines = ["### 本章细纲合同（ChapterDirective · 17 字段）"]
    for f in FIELD_ORDER:
        cn, kind, _desc = FIELD_SPECS[f]
        v = getattr(d, f, None)
        if kind == "list":
            shown = "、".join(str(x) for x in v) if v else "（未声明）"
        else:
            shown = str(v) if v not in (None, "") else "（未声明）"
        lines.append(f"- {cn}（{f}）：{shown}")
    return "\n".join(lines)


def directive_contract_menu() -> str:
    """字段菜单（planning 细纲 prompt 注入用）：FIELD_SPECS 单出处渲染。

    每行 = 字段中文名 + 英文键 + 必填标记 + 说明。**零 ASCII 花括号**（拼接进
    .format() 模板，test_chapter_directive 钉测）。
    """
    lines = []
    for f in FIELD_ORDER:
        cn, _kind, desc = FIELD_SPECS[f]
        req = "必填" if f in REQUIRED_FIELDS else "可选"
        lines.append(f"- {cn}（{f}，{req}）：{desc}")
    return "\n".join(lines)
