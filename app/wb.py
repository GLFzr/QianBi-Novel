# -*- coding: utf-8 -*-
"""世界书装配内核（SillyTavern character book 路线）

**双端共享模块**：本文件在 qianbi-novel(GUI) 与 qianbi-Novel-TUI 之间必须逐字节一致
（scripts/dual_sync_check.py 的 SHARED_ROOT_FILES 硬校验）。放在 app 根而不是 app/core，
是因为 app/project.py 依赖零副作用（只 import os/re/tempfile），不能被
app/core/__init__.py 的 PySide6 导入链拖住——CLI/脚本也直接 import project。

世界书文件格式契约（人工撰写与反哺写入都要遵守，装配层依赖）：
1. 条目块内**禁用** ``##`` / ``###`` 标题 —— memory.py 以 ``^##\\s+[^#]`` 判定
   「追加登记」分区的终点，条目里夹标题会把分区切断；
2. 元数据行**禁用** ``>`` 前缀 —— read_worldbook_additional 会剥掉引用行；
3. 触发词/深度等元数据**不要内联**在描述尾部的 ``｜`` 之后 —— upsert 原位更新
   按 ``｜`` 切分，内联元数据会留下 ``] `` 之类残渣。
4. 触发语义可以显式声明（可选，不声明则按节类型与专名命中推断）：条目块内单开一行
   ``[常驻]`` / ``[关键词：灯盟、当票]`` / ``[第3-10章]``。标记只供装配层读取，
   渲染进 prompt 时会被剥掉；``[触发]`` 是 ``[关键词]`` 的同义写法。
"""
import hashlib
import os
import re

# 专名：2-6 个汉字（可含中间圆点，兼容译名）
_NAME = r"[一-鿿][一-鿿·]{1,5}"

# 行首装饰（可叠加）：标题井号 / 列表符号 / 表格竖线 / 加粗星号
_LEAD = r"^[ \t]*(?:#{1,6}[ \t]*)?(?:[-*•][ \t]*)?(?:\|[ \t]*)?(?:\*\*)?"
# 「陈更：当铺学徒」「| **陈默** | 主角 |」「### 柳三更」——行首专名 + 冒号/竖线/行尾
_ROW_NAME = re.compile(_LEAD + r"(" + _NAME + r")(?:\*\*)?[ \t]*(?=[：:｜|]|$)", re.M)
# 「姓名：陈更」「主角：陈更」字段式登记
_FIELD_NAME = re.compile(r"(?:姓名|名字|角色名|主要角色|主角|配角)[：:][ \t]*(" + _NAME + r")")
# 细纲「出场顺序」类字段（planning.py 细纲模板里的真实字段名）
_CAST_LABEL = re.compile(
    r"(?:出场顺序|出场人物|出场角色|登场人物|主要角色|角色|人物|登场|出场)"
    r"[ \t]*[：:][ \t]*([^\n]+)")
_CAST_SPLIT = re.compile(r"[、，,/／|;；。\s]+")
# 专名后的括注（「柳三更（灰袍灯客）」）只留专名本体
_CAST_ANNOT = re.compile(r"[（(【\[].*\Z")
_NAME_FULL = re.compile(r"\A" + _NAME + r"\Z")

# 字段名不是人名：漏进锚点只会污染相关性排序
_LABEL_STOP = {
    "姓名", "名字", "角色", "角色名", "主要角色", "主角", "配角", "身份", "类型", "描述",
    "关联规则", "功能", "功能位", "关系", "动机", "一句话动机", "弱点", "缺陷", "核心事件",
    "故事内容", "章名", "字数", "字数目标", "阶段位置", "章节定位", "目标情绪", "章首钩子",
    "章尾钩子", "结尾设定", "钩子", "爽点", "起因", "发展", "转折", "高潮", "结尾",
    "主线推进", "辅线推进", "感情线", "逻辑线", "本章推进", "本章回收", "新埋设", "伏笔",
    "出场", "出场顺序", "人物关系", "人物关系变化", "视角", "信息差", "情节点序列",
    "预算合计", "承接锚点", "金手指", "金手指使用", "资源收支", "内容概括", "情节安排",
    "情节细化", "结尾设定和钩子", "人物关系和出场顺序", "伏笔推进", "无",
}

# 以这些结尾的是栏目标签（「主要角色表」「实体名称」），不是专名
_LABEL_SUFFIX = ("表", "名称", "登记", "清单", "说明", "规则", "基准", "顺序",
                 "人物", "角色", "描述", "类型", "要点", "字段")


def _is_label(tok: str) -> bool:
    return tok in _LABEL_STOP or tok.endswith(_LABEL_SUFFIX)


# 表格分隔行：|---|:--:| —— 它的上一行是表头（单元格为栏目名，不是专名）
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|[ \t:|-]*$")


def roster_names(doc: str) -> list:
    """角色表 / 世界书实体区 → 专名列表

    兼容四种真实写法：``- 陈更：当铺学徒``、``| **陈默** | 主角 |``、
    ``### 柳三更``、``姓名：顾拾遗``。表格的表头行（紧贴 ``|---|`` 分隔行）跳过。
    """
    lines = (doc or "").splitlines()
    found = []
    for i, line in enumerate(lines):
        if _TABLE_SEP.match(line):
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            continue
        found += _ROW_NAME.findall(line) + _FIELD_NAME.findall(line)
    return [n for n in dict.fromkeys(found) if not _is_label(n)]


def cast_names(outline_doc: str) -> list:
    """细纲「出场顺序：陈更、柳三更」→ 专名列表

    旧实现只认 ``角色：`` 字段，而细纲模板（planning.py）里的真实字段名是
    ``出场顺序``，导致锚点恒为空、世界书相关性截断从未生效。
    """
    names = []
    for line in _CAST_LABEL.finditer(outline_doc or ""):
        for tok in _CAST_SPLIT.split(line.group(1)):
            tok = _CAST_ANNOT.sub("", tok).strip().strip("*_·、，。")
            if _NAME_FULL.match(tok) and not _is_label(tok):
                names.append(tok)
    return list(dict.fromkeys(names))


def matching_names(text: str, candidates) -> list:
    """细纲正文里逐字出现的既有专名（情节点行「陈更改写当票」不做 NER，只做已知名命中）"""
    body = text or ""
    return [c for c in candidates if c and len(c) >= 2 and c in body]


def merge_names(*groups) -> list:
    """按给定顺序去重合并（越靠前的组优先级越高：越靠近本章的专名越优先）"""
    out = []
    for group in groups:
        for name in group or []:
            if name and name not in out:
                out.append(name)
    return out


# ==================== 条目化解析与按章激活（W1）====================

BACKFLOW_SECTION = "追加登记"      # 机器反哺区（memory.upsert_worldbook_entries 维护）
GROW_KEYS = ("拓宽",)              # TUI 自动拓宽批次（### 拓宽·第6-10章）
RULE_KEYS = ("规则", "数值", "基准")       # 常驻节：约束不为「本章命中」让位
ENTITY_KEYS = ("实体", "登记", "角色")
BACKFLOW_RESERVE = 600             # 反哺区保底预算（登记被截掉 = 后文失忆）
RECENT_WINDOW = 5                  # 近章新近档窗口：首见/覆盖章落在 [num-5, num]
TRIM_FLOOR = 80                    # 剩余预算小于此值不再塞节选（半句话不如不给）
JOIN_COST = 2                      # 条目之间 "\n\n" 分隔的预算开销
TRIM_MARK = "…（节选）"     # 按锚点挑行后的省略
CUT_MARK = "…（截断）"      # 无锚点可挑、整段按字符切尾
EMPTY_PLACEHOLDER = "（本书尚未生成世界书——按核心设定写作，后续在世界书阶段补充）"

# 优先级档位（越小越先入预算）
P_CONSTANT = 0   # 常驻：[常驻] 标记、规则/数值基准节
P_HIT = 1        # 本章命中：专名/关键词出现在细纲+近窗摘要，或章节区间覆盖本章
P_RECENT = 2     # 近章登记：首见第N章落在近窗、反哺区、拓宽批次
P_SECTION = 3    # 节权重兜底：3 规则 / 4 实体 / 5 其余
WHY_SKELETON = "节骨架"

_HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_NUM_PREFIX = re.compile(r"^\d+[.、)]\s*")
_ENTRY_BOLD = re.compile(
    r"^[-*•][ \t]*\*\*[ \t]*(.+?)[ \t]*\*\*[ \t]*(?:[（(]([^）)]*)[）)])?[ \t]*[：:][ \t]*(.*)$")
_ENTRY_PLAIN = re.compile(r"^[-*•][ \t]*(" + _NAME + r")[ \t]*[：:][ \t]*(.*)$")
_TABLE_ROW = re.compile(r"^[ \t]*\|(.*)\|[ \t]*$")
_MARK_CONST = re.compile(r"[【\[]\s*(?:常驻|常駐|constant)\s*[】\]]", re.I)
_MARK_KEYS = re.compile(
    r"[【\[]\s*(?:关键词|触发词|触发|keyword)\s*(?:[：:]\s*([^】\]]*))?[】\]]", re.I)
_MARK_RANGE = re.compile(
    r"[【\[]\s*(?:第|章节|范围|区间)?\s*(\d+)\s*[-—~～至]\s*(\d+)\s*章?\s*[】\]]")
_FIRST_SEEN = re.compile(r"首见第\s*(\d+)\s*章")
_CHAPTER_RANGE = re.compile(r"(\d+)\s*[-—~～至]\s*(\d+)")
_CELL_DECOR = "*_ `《》「」“”\"'"


def norm_name(s: str) -> str:
    """专名归一（与 memory._norm_name 同口径）：去空白与书名号/引号"""
    return re.sub(r"\s+", "", (s or "")).strip("《》「」“”\"'")


def section_weight(head: str) -> int:
    """节权重：规则/数值基准 3 ＞ 实体/登记/角色 2 ＞ 其余 1（与旧 _wb_section_priority 同口径）"""
    head = head or ""
    if any(k in head for k in RULE_KEYS):
        return 3
    if any(k in head for k in ENTITY_KEYS):
        return 2
    return 1


def _kind_for(section: str) -> str:
    return "rule" if section_weight(section) >= 3 else "entity"


def _has_content(text: str) -> bool:
    """退到行边界后是否还剩正文（只剩标题与空行＝空壳，不值得退让）"""
    return any(l.strip() and not _HEADING.match(l.strip()) for l in text.split("\n"))


def _shrink(text: str, mark: str) -> str:
    """截断收尾：空行与只剩标题的尾巴一律丢掉（内容没进来就别留空壳）"""
    lines = [l for l in text.split("\n") if l.strip()]
    while lines and _HEADING.match(lines[-1]):
        lines.pop()
    return ("\n".join(lines) + mark) if lines else ""


def trim_lines(body: str, budget: int, anchors=None) -> str:
    """条目内截断：有锚点词的行优先保留，输出仍按原行序，总长不超预算（旧 _wb_trim_body）"""
    if len(body) <= budget:
        return body
    keep = budget - len(TRIM_MARK)     # TRIM_MARK 与 CUT_MARK 等长，省略号不撑破预算
    if keep <= 0:
        return ""
    lines = body.splitlines(keepends=True)
    if anchors:
        hit, rest = [], []
        for i, l in enumerate(lines):
            (hit if any(a in l for a in anchors) else rest).append((i, l))
        picked, total = [], 0
        for i, l in hit + rest:
            if total + len(l) > keep:
                break
            picked.append((i, l))
            total += len(l)
        picked.sort(key=lambda t: t[0])
        return _shrink("".join(l for _, l in picked), TRIM_MARK)
    cut = body[:keep]
    nl = cut.rfind("\n")
    if 0 < nl and not body[keep:].startswith("\n") and _has_content(cut[:nl]):
        # 退到行边界保住 markdown 结构；退完只剩空壳就切半行——给一半信息比整条丢掉强
        cut = cut[:nl]
    return _shrink(cut, CUT_MARK)


class Entry:
    """世界书条目：触发与装配的最小单位

    ``kind``：prose（节标题/散正文/表头骨架）/ entity（专名条目）/ rule（规则节条目）
    ``meta``：constant / keywords / range（章节区间）/ first_seen（首见章号）
    ``skeletons``：所在节的骨架条目索引（外→内，入预算时要连带，标题/表头不丢）
    ``group``：最近的节（骨架条目索引）——激活优先级以节为单位排
    ``src``：原文行号首末——渲染时判断能否紧挨上一块（表格行之间不能插空行）
    """

    def __init__(self, name: str, kind: str, section: str, lines=None, meta=None,
                 skeletons=(), group=-1, src=None):
        self.name = (name or "").strip()
        self.kind = kind
        self.section = section or ""
        self.lines = list(lines or [])
        self.meta = {"keywords": [], "constant": False, "range": None, "first_seen": None}
        self.meta.update(meta or {})
        self.skeletons = tuple(skeletons)
        self.group = group
        self.src = list(src or [])
        # 骨架块之下还有子节（内容全在子节里）：只能随子节条目连带进入
        self.container = False

    def add(self, line: str):
        self.lines.append(line)

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip("\n")

    @property
    def size(self) -> int:
        return len(self.body)

    @property
    def id(self) -> str:
        """稳定标识：归一化名 + 节（条目改名/换节即视为新条目）"""
        return "%s#%s" % (norm_name(self.name) or "_", norm_name(self.section) or "_")

    @property
    def content_hash(self) -> str:
        """内容指纹：与 id 分开，快照才能区分「条目还在但内容变了」"""
        return hashlib.sha1(self.body.encode("utf-8")).hexdigest()[:12]

    @property
    def is_backflow(self) -> bool:
        return BACKFLOW_SECTION in self.section


def _range_from(text: str):
    m = _CHAPTER_RANGE.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _apply_markers(text: str, meta: dict) -> str:
    """抽出 [常驻]/[关键词：…]/[第3-10章] 标记写入 meta，并从渲染文本里剥掉"""
    if _MARK_CONST.search(text):
        meta["constant"] = True
    for m in _MARK_KEYS.finditer(text):
        meta["keywords"] += [w.strip() for w in _CAST_SPLIT.split(m.group(1) or "") if w.strip()]
    m = _MARK_RANGE.search(text)
    if m:
        meta["range"] = (int(m.group(1)), int(m.group(2)))
    text = _MARK_RANGE.sub("", _MARK_KEYS.sub("", _MARK_CONST.sub("", text)))
    return text.strip()


def _read_meta(body: str, extra: str = "") -> tuple:
    """条目文本 → (去掉触发标记的文本, meta)；节/条目标题里的「第6-10章」也当章节区间"""
    meta = {"keywords": [], "constant": False, "range": None, "first_seen": None}
    text = _apply_markers(body, meta)
    m = _FIRST_SEEN.search(body)
    if m:
        meta["first_seen"] = int(m.group(1))
    if not meta["range"]:
        meta["range"] = _range_from(extra)
    meta["keywords"] = list(dict.fromkeys(meta["keywords"]))
    return text, meta


class _Blk:
    """标题块：level 0 = 首个标题前的散正文"""

    __slots__ = ("level", "title", "lines", "children")

    def __init__(self, level: int, title: str):
        self.level = level
        self.title = title
        self.lines = []
        self.children = []


def _build_tree(lines: list) -> _Blk:
    """按标题建树；块内直属行存 (原文行号, 文本)"""
    root = _Blk(0, "")
    stack = [root]
    for no, raw in enumerate(lines):
        line = raw.rstrip()
        m = _HEADING.match(line)
        if m:
            blk = _Blk(len(m.group(1)), _NUM_PREFIX.sub("", (m.group(2) or "").strip()))
            while len(stack) > 1 and stack[-1].level >= blk.level:
                stack.pop()
            stack[-1].children.append(blk)
            stack.append(blk)
        stack[-1].lines.append((no, line))
    return root


def _chunks(lines: list) -> list:
    """块内直属行 → [("prose", "", [(行号, 文本)])] / [("item", 专名, [...])]

    表格数据行、反哺行 ``- **名**（类）：述``、TUI ``- 名：述`` 是条目；
    表头与分隔行是表格骨架（留在 prose），缩进续行并入所属条目。
    """
    out = []

    def sink() -> list:
        if out and out[-1][0] == "prose":
            return out[-1][2]
        out.append(("prose", "", []))
        return out[-1][2]

    n = len(lines)
    for idx, pair in enumerate(lines):
        line = pair[1]
        row = _TABLE_ROW.match(line)
        if row:
            nxt = lines[idx + 1][1] if idx + 1 < n else ""
            if _TABLE_SEP.match(line) or _TABLE_SEP.match(nxt):
                sink().append(pair)
                continue
            cells = [c.strip() for c in row.group(1).split("|")]
            name = _CAST_ANNOT.sub("", (cells[0] or "").strip(_CELL_DECOR)).strip()
            if name and len(cells) > 1 and not _is_label(name):
                out.append(("item", name, [pair]))
                continue
            sink().append(pair)
            continue
        stripped = line.strip()
        mb = _ENTRY_BOLD.match(stripped)
        if mb:            # 粗体反哺行恒是条目：登记名可能以「规则」「表」等后缀结尾
            out.append(("item", mb.group(1).strip(), [pair]))
            continue
        mp = _ENTRY_PLAIN.match(stripped)
        if mp and not _is_label(mp.group(1)):
            out.append(("item", mp.group(1).strip(), [pair]))
            continue
        if out and out[-1][0] == "item" and line[:1].isspace():
            out[-1][2].append(pair)
            continue
        sink().append(pair)
    return out


def _trim_edges(pairs: list) -> list:
    """去掉块直属行首尾的空行：空行不占预算，也不该把相邻两块撑开"""
    i, j = 0, len(pairs)
    while i < j and not pairs[i][1].strip():
        i += 1
    while j > i and not pairs[j - 1][1].strip():
        j -= 1
    return pairs[i:j]


def _heading_fields(root: _Blk) -> set:
    """跨标题复现的裸条目行名（身份/约束/声口）＝字段名，不是子条目

    只统计 ``- 名：述``：表格行与 ``- **名**（类）：`` 反哺行恒是实体条目，
    同一实体名出现在两个节里（实体登记 + 拓宽批次）不能被误判成字段。
    """
    seen = {}
    stack = [root]
    while stack:
        blk = stack.pop()
        stack += blk.children
        if not blk.title:
            continue
        for kind, name, pairs in _chunks(blk.lines):
            if kind == "item" and _ENTRY_PLAIN.match(pairs[0][1].strip()):
                seen.setdefault(norm_name(name), set()).add(norm_name(blk.title))
    return {k for k, v in seen.items() if len(v) > 1}


def parse(doc: str) -> list:
    """世界书全文 → [Entry]（按文件顺序）

    一次吃下四种现存语法：反哺行 ``- **名**（类）：述 ｜ 首见第N章``、``### 名`` + 属性行、
    TUI ``- 名：述``、表格行 ``| 名 | 类 | 述 |``。

    标题块先建树再判定角色：``##`` 级与「块内还有条目行/子块」的 ``###`` 是**节**
    （``### 1. 实体登记`` 这种表格容器即节），其余 ``###`` 是**条目**（``### 柳三更`` +
    ``- 身份：…`` 属性行——属性字段名跨标题复现即认定整块折叠，条目不被切成空标题骨架）。
    节的标题行与散正文、表头分隔行聚成该节唯一的 prose 骨架，
    激活时随内容连带——截断后仍是合法表格、不丢小标题。
    同名（归一化）且同节的条目跨语法合并；触发标记只进 meta，不进渲染文本。
    """
    entries = []
    index = {}       # id → 条目在 entries 中的下标（合并后仍在原位，索引对骨架链稳定）

    def add(name, kind, section, pairs, skeletons, group):
        text, meta = _read_meta("\n".join(t for _s, t in pairs),
                                extra="%s %s" % (section, name))
        src = [s for s, _t in pairs]
        e = Entry(name, kind, section, text.split("\n") if text else [], meta,
                  skeletons, group, src[:1] + src[-1:])
        if kind != "prose" and e.id in index:
            keep = entries[index[e.id]]
            for ln in e.lines:
                if ln not in keep.lines:
                    keep.add(ln)
            if src:
                keep.src = [keep.src[0], max(keep.src[-1], src[-1])] if keep.src else src[:1]
            for k in e.meta["keywords"]:
                if k not in keep.meta["keywords"]:
                    keep.meta["keywords"].append(k)
            keep.meta["constant"] = bool(keep.meta["constant"] or e.meta["constant"])
            for f in ("range", "first_seen"):
                if not keep.meta[f] and e.meta[f]:
                    keep.meta[f] = e.meta[f]
            return index[e.id]
        entries.append(e)
        index[e.id] = len(entries) - 1
        return len(entries) - 1

    def visit(blk, ancestors, section, group):
        chunks = _chunks(blk.lines)
        items = [n for c in chunks if c[0] == "item" for n in [c[1]]]
        # 裸「##」残段（自动生成的收尾常见）：除标题行外什么都没有 → 整块丢掉，别留空壳
        if (blk is not tree and not (blk.title or "").strip() and not blk.children
                and not items and all(_HEADING.match(l.strip()) or not l.strip()
                                      for _n, l in blk.lines)):
            return
        # 「### 陈更」+ 属性行：字段名（身份/约束/声口）跨标题复现 → 整块是一条条目
        if (blk.level >= 3 and items and not _is_label(blk.title or "")
                and any(norm_name(n) in fields for n in items)):
            g = add(blk.title, _kind_for(section), section,
                    _trim_edges([p for c in chunks for p in c[2]]), ancestors, group)
            for c in blk.children:
                visit(c, ancestors + (g,), section, g)
            return
        # 容器 vs 单条目：##/### 级标题块内还有条目行或子块 → 它是「节」
        if blk.level <= 2 or items or blk.children:
            title = blk.title or section
            body = _trim_edges([p for c in chunks if c[0] == "prose" for p in c[2]])
            g = add(title, "prose", title, body, ancestors, group)
            # 节骨架归本节：只随本节条目连带进入，不作为一个可独立填预算的兜底组
            entries[g].group = g
            entries[g].container = bool(blk.children)
            anc = ancestors + (g,)
            for kind, name, pairs in chunks:
                if kind == "item":
                    add(name, _kind_for(title), title, pairs, anc, g)
            for c in blk.children:
                visit(c, anc, title, g)
            return
        g = add(blk.title, _kind_for(section), section,
                _trim_edges([p for c in chunks for p in c[2]]), ancestors, group)
        for c in blk.children:
            visit(c, ancestors + (g,), section, g)

    tree = _build_tree((doc or "").splitlines())
    fields = _heading_fields(tree)
    visit(tree, (), "", -1)
    return entries


def chapter_context(proj: str, num: int) -> str:
    """触发检索文本：本章细纲 + 近窗章节摘要（缺文件一律容忍为空）"""
    from . import project
    if not num:
        return ""
    parts = []
    try:
        parts.append(project.read_file(project.get_outline_path(proj, num)))
    except Exception:  # noqa: BLE001
        pass
    try:
        doc = project.read_file(os.path.join(proj, "追踪", "章节摘要.md"))
    except Exception:  # noqa: BLE001
        doc = ""
    lo = max(1, num - RECENT_WINDOW)
    for line in doc.splitlines():
        m = re.match(r"^-\s*第(\d+)章", line.strip())
        if m and lo <= int(m.group(1)) < num:
            parts.append(line)
    return "\n".join(p for p in parts if p)


def trigger(entry: Entry, num: int, ctx_text: str = "", anchors=None) -> tuple:
    """非骨架条目 → (优先级, 命中原因)

    默认按「节类型 + 专名命中」推断，无需迁移既有世界书文件；``[常驻]``/``[关键词：…]``/
    ``[第3-10章]`` 标记只做显式覆盖。
    """
    meta = entry.meta
    weight = section_weight(entry.section)
    if meta["constant"] or weight >= 3:
        return P_CONSTANT, "常驻"
    keys = list(meta["keywords"])
    if entry.name and entry.name not in keys:
        keys.insert(0, entry.name)
    anchors = anchors or []
    hit = next((k for k in keys if k and (k in ctx_text or k in anchors)), None)
    if hit:
        return P_HIT, "本章命中·" + hit
    rng = meta["range"]
    if rng and rng[0] <= num <= rng[1]:
        return P_HIT, "章节区间·第%d-%d章" % rng
    fs = meta["first_seen"]
    if fs and num - RECENT_WINDOW <= fs <= num:
        return P_RECENT, "近章登记·首见第%d章" % fs
    if rng and num - RECENT_WINDOW <= rng[1] < num:
        return P_RECENT, "近章覆盖·第%d-%d章" % rng
    if entry.is_backflow or any(k in entry.section for k in GROW_KEYS):
        return P_RECENT, "近章登记"
    return P_SECTION + (3 - weight), "节权重"    # 规则3 / 实体4 / 其余5


def _note(entry: Entry, why: str) -> dict:
    """激活清单条目（供章级快照与真机 diff）"""
    return {"id": entry.id, "name": entry.name, "kind": entry.kind,
            "section": entry.section, "why": why, "size": entry.size,
            "hash": entry.content_hash}


def _groups(entries: list, num: int, ctx_text: str, anchors) -> list:
    """按节分组打分 → 排序后的 [{band, gid, prose, items, whys, backflow}]（节内按档位）"""
    groups = {}
    for i, e in enumerate(entries):
        if e.size <= 0:
            continue
        g = groups.get(e.group)
        if g is None:
            g = {"gid": e.group, "band": P_SECTION + 2, "prose": [], "items": [],
                 "whys": {}, "backflow": BACKFLOW_SECTION in e.section}
            groups[e.group] = g
        if e.kind == "prose":
            g["prose"].append(i)
            continue
        band, why = trigger(e, num, ctx_text, anchors)
        g["items"].append((band, i))
        g["whys"][i] = why
        g["band"] = min(g["band"], band)
    out = list(groups.values())
    for g in out:
        if not g["items"]:
            g["band"] = trigger(Entry("", "entity", entries[g["gid"]].section),
                                num, ctx_text, anchors)[0]
    return sorted(out, key=lambda g: (g["band"], g["gid"]))


def _pick(entries: list, groups: list, budget: int, anchors) -> dict:
    """按节贪心入预算 → {下标: 原因}

    反哺区先留保底再单独吃满，常规节的档位排在前面的先进；条目入预算时连带其节骨架
    （标题/表头随内容走）。选择顺序不等于渲染顺序——渲染仍按文件原序。
    """
    chosen, used = {}, 0
    # 反哺保底要连它的节骨架一起算：只留条目钱、骨架挤进来照样丢登记
    reserve = max(0, min(BACKFLOW_RESERVE,
                         sum(e.size + JOIN_COST for e in entries if e.is_backflow),
                         budget - TRIM_FLOOR))

    def fit(i, why, cap):
        """条目自身入预算（装不下就节选到剩余额度）；成功 True，不动骨架"""
        nonlocal used
        e = entries[i]
        if used + e.size + JOIN_COST <= cap:
            chosen[i] = why
            used += e.size + JOIN_COST
            return True
        if cap - used < TRIM_FLOOR:
            return False
        backup, body = e.lines, e.body
        e.lines = trim_lines(body, cap - used - JOIN_COST, anchors).split("\n")
        if e.size and used + e.size + JOIN_COST <= cap:
            chosen[i] = why + "·节选"
            used += e.size + JOIN_COST
            return True
        e.lines = backup
        return False

    def take(i, why, cap):
        nonlocal used
        if i in chosen:
            return True
        linked = [s for s in entries[i].skeletons
                  if s not in chosen and entries[s].size > 0]
        for s in linked:               # 骨架先占额度：标题/表头随内容走
            chosen[s] = WHY_SKELETON
            used += entries[s].size + JOIN_COST
        if fit(i, why, cap):
            return True
        for s in linked:               # 条目没进来 → 骨架不许单独留个空标题
            chosen.pop(s)
            used -= entries[s].size + JOIN_COST
        return False

    def fill(group_list, cap):
        for g in group_list:
            if used >= cap:
                break
            # 有内容的节：只按档位取条目，节骨架由 skeletons 连带（避免出现只有表头的空节）
            # 容器节（内容全在子节）没有自己的条目，单独进来只剩空标题 → 不做兜底填充
            picks = ([i for _b, i in sorted(g["items"])]
                     or [i for i in g["prose"] if not entries[i].container])
            for i in picks:
                if i in chosen:
                    continue
                ok = take(i, WHY_SKELETON if entries[i].kind == "prose" else g["whys"][i], cap)
                if not ok:
                    break               # 档位优先：吃不下就停，不给低档位条目让路

    normal = [g for g in groups if not g["backflow"]]
    fill(normal, max(0, budget - reserve))
    fill([g for g in groups if g["backflow"]], budget)
    fill(normal, budget)          # 反哺保底没吃满 → 余量回灌常规节
    return chosen


def _render(entries: list, chosen: dict) -> str:
    """按文件原序输出入预算条目；原文相邻的两块之间不插空行（表格行不能被空行切断）"""
    parts, prev_last = [], None
    for i in sorted(chosen):
        e = entries[i]
        body = e.body
        if not body.strip():
            continue
        if parts:
            parts.append("\n" if (prev_last is not None and e.src
                                  and e.src[0] == prev_last + 1) else "\n\n")
        parts.append(body)
        if e.src:
            prev_last = e.src[-1]
    return "".join(parts) + "\n" if parts else ""


def _budget_for(preset, phase: str, budget: int) -> int:
    """预设可覆盖世界书注入预算：``worldbook_budget: {phase: n}``，``"*"`` 为默认档"""
    if isinstance(preset, dict):
        ov = preset.get("worldbook_budget")
    else:
        ov = getattr(preset, "worldbook_budget", None) if preset is not None else None
    if not isinstance(ov, dict):
        return budget
    val = ov.get(phase or "") or ov.get("*")
    try:
        return int(val) if val else budget
    except (TypeError, ValueError):
        return budget


def assemble(proj: str, num: int = 0, budget: int = 2000, *, preset=None,
             phase: str = "", anchors=None, doc: str = None) -> dict:
    """按章激活世界书 → {text, activated, dropped, budget, phase}

    档位：常驻（规则/数值节、``[常驻]``）＞ 本章命中（专名/关键词在细纲+近窗摘要里
    出现、``[关键词]``、章节区间）＞ 近章新近档（``首见第N章`` 落在近窗、反哺登记区、
    TUI 拓宽批次）＞ 节权重（规则＞实体＞其余）。反哺区另有 BACKFLOW_RESERVE 保底。

    **快速路径不变式**：全文不超预算时逐字返回原文件（老书零变化的硬保证）。
    """
    from . import project
    budget = max(0, int(budget or 0))
    budget = _budget_for(preset, phase, budget)
    if doc is None:
        doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    if not (doc or "").strip():
        return {"text": EMPTY_PLACEHOLDER, "activated": [], "dropped": [],
                "budget": budget, "phase": phase}
    entries = parse(doc)
    if len(doc) <= budget:
        return {"text": doc, "activated": [_note(e, "全文") for e in entries],
                "dropped": [], "budget": budget, "phase": phase}
    if anchors is None:
        try:
            anchors = project.worldbook_anchors(proj, num) if num else []
        except Exception:  # noqa: BLE001
            anchors = []
    anchors = list(anchors or [])
    chosen = _pick(entries, _groups(entries, num, chapter_context(proj, num), anchors),
                   budget, anchors)
    text = _render(entries, chosen)
    return {"text": text or EMPTY_PLACEHOLDER,
            "activated": [_note(entries[i], why) for i, why in sorted(chosen.items())],
            "dropped": [{"id": e.id, "name": e.name, "section": e.section}
                        for i, e in enumerate(entries)
                        if e.kind != "prose" and i not in chosen and e.size > 0],
            "budget": budget, "phase": phase}


def constant_entries(proj: str, budget: int = 0) -> str:
    """常驻条目独立渲染（体验轮 A2'：跨章逐字节稳定，供共享前缀使用）。

    - 只取 ``meta["constant"]`` 为真的条目，按 ``norm_name(name)`` 排序输出——
      确定性是本函数的灵魂：同一世界书两次调用必须逐字节一致；
    - budget>0 时按条截断（不切半条），截断时末尾注明；
    - 无常驻条目返回空串。**不触碰 assemble 本体与其快速路径不变式。**
    """
    from . import project
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    if not (doc or "").strip():
        return ""
    entries = [e for e in parse(doc) if e.meta.get("constant") and e.body.strip()]
    if not entries:
        return ""
    entries.sort(key=lambda e: norm_name(e.name) or "")
    out, used = [], 0
    for e in entries:
        body = e.body
        if budget and used + len(body) > budget and out:
            out.append("…（常驻条目截断）")
            break
        out.append(body)
        used += len(body) + 2
    return "\n\n".join(out) + "\n"
