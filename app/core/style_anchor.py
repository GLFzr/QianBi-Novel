# -*- coding: utf-8 -*-
"""文风基准四件套 + 全书统计镜像（0.24.0 W3；纯本地，零 LLM 零新依赖）

病根与解法（三测实证 + 研究结论五源收敛）：
- 病根：AI 味定量超真人基线——陈词 2.8×、「不是…而是」2.08×、句长方差 0.22×、
  对话占比 0.48×。生成端此前只有「负面清单」（别这么写），没有「正面锚」
  （照这个样子写）——没有样例约束时模型回落到自身分布＝AI 味。
- 解法：文风基准四件套（指纹/基准段/负面清单/本书校准段）落在
  设定/文风基准.md（用户可读可手改的单一真源），全书统计镜像回注生成 prompt
  ——「你这本书目前的高频病是 X」让本章主动压低，而不是写完再扫。

调用面（stages 集成方已定，签名不许动）：
- ensure_file(proj)               文件不存在时落模板并返回全文；存在返回全文（幂等）
- anchor_text(proj, max_chars)    基准段一/二 + 本书校准段的已填正文语态样本
                                  （跳过占位段，按文件节序拼接，超长截到段边界）
- backfill_from_chapter(proj, n)  第 n 章定稿后把本书自己的语态回填进校准段（幂等）
- stats_mirror(proj, top)         全书各章 by_rule per_kilo 均值 top N 的一行镜像
- fingerprint_line(proj)          文风指纹节原文（≤300 字）
- assembly_block(proj)            草稿 prompt 末位装配块：指纹→镜像→锚
                                  （锚最后＝语态样例最贴近生成点）

纪律：读路径全 fail-open（文件缺失/损坏 → 空串，不抛不写）；写入走
project.write_file 原子落盘；stats_mirror 每次全量重算（章数 ≤几百可接受，
不做缓存——缓存失效比重算贵）。纯标准库 + app 内模块，无新依赖。
"""
import os
import re

from .. import project
from . import deslop_metrics, gates

PATH_REL = "设定/文风基准.md"

# ---- 节名（模板结构是 stages/UI 的共同契约，改名须同步调用方）----
_SEC_FINGERPRINT = "文风指纹"
_SEC_BASE_ONE = "基准段一"
_SEC_BASE_TWO = "基准段二"
_SEC_CALIB = "本书校准段"
_ANCHOR_SECS = (_SEC_BASE_ONE, _SEC_BASE_TWO, _SEC_CALIB)

# 占位标记：段内含任一字样即视为未填（「贴 」＝「贴」+半角空格，模板占位行原样）
_PLACEHOLDER_MARKS = ("占位", "贴 ", "范文")

# 指纹节注入上限（字符数，行边界截断）
_FINGERPRINT_CAP = 300

# 校准段回填字数带（可见字口径，与 count_chars/visible_chars 一致）
_BACKFILL_MIN = 600
_BACKFILL_MAX = 1000

# 对话开引号族（含对话段判定用；与 deslop_metrics._QUOTE_PAIRS 的开引号集对齐）
_DIALOG_OPEN = "「『“\"'"

# 规则中文小注（stats_mirror 展示用；未登记者只显示 by_rule 键名——
# 名称对照 app/deslop.py 各规则的 message 首词，不新增语义）
_RULE_NOTE = {
    "cliche-word": "陈词", "em-dash": "破折号", "gaze-density": "视线词",
    "quote-emphasis": "引号强调", "telling-cognition": "认知告知",
    "micro-action-tic": "微动作复读", "brake-sentence": "否定刹车",
    "brake-standalone-para": "刹车独立段", "not-is-comparison": "不是而是句式",
    "reverse-not-is": "反序对比", "negation-parade": "否定排比",
    "voice-contrast": "音量反差腔", "flat-voice": "无情绪声线",
    "trailer-ending": "章末预告", "trailer-summary": "预告式总结",
    "fate-summary": "抽象命运总结", "abstract-summary-tic": "抽象总结复读",
    "reasoning-chain": "解释链", "daizhe-adverb": "带着状语",
    "simile-marker-density": "文言比喻标记", "metaphor-density": "比喻密度",
    "prompting-colon": "提示性冒号", "dunhao-list-density": "顿号罗列",
    "period-stutter": "句号结巴", "long-paragraph": "超长段",
    "mengdi-density": "猛地惊觉", "one-line-para": "单句短段",
    "stamp-para": "盖章段", "negation-pair-tic": "否定对偶",
    "stock-reaction-tic": "模板身体反应", "action-list-tic": "动作清单",
    "system-notice-formality-tic": "系统公文腔", "overcompressed-prose-tic": "过密短段",
    "low-connective-density-tic": "低连接密度", "formulaic-parallelism": "公式化排比",
    "cliche-density-tic": "陈词密度", "forced-triad": "强凑三连",
    "sentence-opening-run": "句首复读", "idealized-persona-simile": "拟人化喻体",
    "adjacent-sentence-isomorph": "邻句同构", "zero-subject-comment": "零主语评断",
    "vague-rider": "空转状语", "closer-recap-tic": "例子后点题",
    "sendoff-para": "送别升华段", "recap-opening": "章首复述前情",
}

# 文风基准模板（四件套；五个 ## 节标题是解析锚点，用户改内容不改标题）
_TEMPLATE = """# 文风基准

> 文风纪律的单一真源（四件套）：指纹给参数、基准段给语态、负面清单给禁则、
> 本书校准段由第 1 章定稿后自动回填。内容可手改，五个节标题别动。

## 文风指纹

- 对话占比带宽：14%～32%
- 句长节奏：长短句交错，避免等长句连排
- 叙述距离：贴身第三人称

## 基准段一

（占位：贴 500-800 字该书期望文风的范文——选一段你最想「写成这个样子」的正文。）

## 基准段二

（占位：贴 500-800 字该书期望文风的范文——换一场景或节奏再贴一段，与基准段一互补。）

## 负面清单

- 禁「不是…而是…」句式滥用
- 禁排比堆砌与机械三段式
- 禁章首回顾上章情节

## 本书校准段

（占位：第 1 章定稿后自动回填，无需手填。）
"""

_SEC_HEAD_RE = re.compile(r"^##\s+(.+?)\s*$")


def _anchor_path(proj: str) -> str:
    return os.path.join(proj, *PATH_REL.split("/"))


def _read_doc(proj: str) -> str:
    """读文风基准全文（fail-open：缺失/损坏 → 空串，读路径零副作用）"""
    try:
        return project.read_file(_anchor_path(proj))
    except (OSError, ValueError):
        return ""


def _split_sections(doc: str) -> dict:
    """`## 节名` 小节结构 → {节名: 节体}（节体不含标题行；保持文件出现序）"""
    out = {}
    cur, buf = None, []
    for line in (doc or "").splitlines():
        m = _SEC_HEAD_RE.match(line)
        if m and not line.startswith("###"):
            if cur is not None:
                out[cur] = "\n".join(buf).strip("\n")
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip("\n")
    return out


def _is_placeholder(para: str) -> bool:
    """占位段判定：含「占位」「贴 」「范文」任一字样即视为未填"""
    return any(mark in para for mark in _PLACEHOLDER_MARKS)


def _filled_paras(section_body: str) -> list:
    """节体 → 已填正文段列表（跳过空段与占位段，保持行序）"""
    if not section_body:
        return []
    return [p.strip() for p in section_body.splitlines()
            if p.strip() and not _is_placeholder(p)]


def _trim_sentences(para: str, room: int) -> str:
    """句边界截断：向 room 可见字装满整句为止。

    装不下一句、或余量装完不足 50 字（防残句碎尾）→ 返回 ""（宁缺毋滥）。
    """
    if room <= 0:
        return ""
    out, used = [], 0
    for s in re.split(r"(?<=[。！？!?…])", para.strip()):
        if not s:
            continue
        n = deslop_metrics.visible_chars(s)
        if used + n > room:
            break
        out.append(s)
        used += n
    if used < 50:
        return ""
    return "".join(out).strip()


def _join_within(paras: list, max_chars: int) -> str:
    """按序拼接段落到 max_chars 字以内（段边界截断；首段独自超长时句边界截断）"""
    out, used = [], 0
    for p in paras:
        need = len(p) + (1 if out else 0)
        if used + need > max_chars:
            if not out:
                t = _trim_sentences(p, max_chars)
                if t:
                    out.append(t)
            break
        out.append(p)
        used += need
    return "\n".join(out)


# ---------------- 模块 1：文风基准四件套 ----------------

def ensure_file(proj: str) -> str:
    """文件不存在时创建模板并返回全文；存在则返回全文（幂等，不改用户内容）"""
    path = _anchor_path(proj)
    if os.path.exists(path):
        return _read_doc(proj)
    project.write_file(path, _TEMPLATE)
    return _TEMPLATE


def anchor_text(proj: str, max_chars: int = 1200) -> str:
    """已填正文语态样本：基准段一/二 + 本书校准段（按文件节序拼接）。

    - 跳过占位段（含「占位」「贴 」「范文」字样的段视为未填）；全未填返回 ""。
    - 校准段排在末位＝本书自己的语态离生成点最近（与装配块「锚最后」同纪律）。
    - 超 max_chars 截到段边界（首段独自超长时句边界截断），返回长度 ≤ max_chars。
    """
    secs = _split_sections(_read_doc(proj))
    paras = []
    for name, body in secs.items():        # dict 保持文件序
        if name in _ANCHOR_SECS:
            paras.extend(_filled_paras(body))
    if not paras:
        return ""
    return _join_within(paras, max_chars)


def backfill_from_chapter(proj: str, num: int) -> bool:
    """把第 num 章的正文语态回填进「## 本书校准段」（第 1 章定稿后由 stages 调用）。

    取材：该章开头段（首个非标题非空段）+ 全文最长的含对话段，合计凑
    600-1000 可见字（两段不足下限时按文档序续补后续段；超上限时末段句边界截断）。
    写入为追加式（保留节内既有内容，占位行不动）；节不存在则先 ensure_file 补
    模板（文件缺失同理）。成功返回 True；已回填 / 第 num 章正文不存在返回 False。
    """
    chapter_path = None
    for n, _title, p in project.list_chapters(proj):
        if n == num:
            chapter_path = p
            break
    if chapter_path is None:
        return False
    try:
        text = project.read_file(chapter_path)
    except (OSError, ValueError):
        return False
    paras = [ln.strip() for ln in (text or "").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if not paras:
        return False
    ensure_file(proj)                      # 文件/节缺失先补模板（幂等）
    path = _anchor_path(proj)
    doc = _read_doc(proj)
    if _filled_paras(_split_sections(doc).get(_SEC_CALIB, "")):
        return False                       # 已回填（幂等）
    picked = _pick_calib_paras(paras)
    if not picked:
        return False
    _append_to_section(path, doc, _SEC_CALIB, "\n\n".join(picked))
    return True


def _pick_calib_paras(paras: list) -> list:
    """开头段 + 最长含对话段 → 凑 [_BACKFILL_MIN, _BACKFILL_MAX] 可见字的段落清单"""
    dialog_idx = None
    best_len = -1
    for i, p in enumerate(paras):
        if any(q in p for q in _DIALOG_OPEN):
            n = deslop_metrics.visible_chars(p)
            if n > best_len:
                dialog_idx, best_len = i, n
    order = [0]
    if dialog_idx is not None and dialog_idx != 0:
        order.append(dialog_idx)
    # 命名两段不足下限时按文档序续补（凑字；不重复取）
    used_idx = set(order)
    total = sum(deslop_metrics.visible_chars(paras[i]) for i in order)
    for i in range(len(paras)):
        if total >= _BACKFILL_MIN:
            break
        if i in used_idx:
            continue
        order.append(i)
        used_idx.add(i)
        total += deslop_metrics.visible_chars(paras[i])
    order.sort()                           # 落盘按文档序（开头段仍在最前）
    # 上限裁剪：装不下的段句边界截断，截不出整段就丢弃
    out, used = [], 0
    for i in order:
        p = paras[i]
        n = deslop_metrics.visible_chars(p)
        if n <= _BACKFILL_MAX - used:
            out.append(p)
            used += n + 2                  # 段间 "\n\n" 近似计入预算
        else:
            t = _trim_sentences(p, _BACKFILL_MAX - used)
            if t:
                out.append(t)
            break
    return out


def _append_to_section(path: str, doc: str, sec_name: str, body: str) -> None:
    """把 body 追加到 doc 的 `## sec_name` 节体末尾（保留节内既有内容）；
    节不存在则在文末新增该节。重写全文件（原子写盘）。"""
    lines = (doc or "").splitlines()
    start = end = None
    for i, line in enumerate(lines):
        m = _SEC_HEAD_RE.match(line)
        if m and not line.startswith("###"):
            if start is None:
                if m.group(1).strip() == sec_name:
                    start = i
            else:                          # 目标节之后的第一个节头
                end = i
                break
    if start is None:
        base = (doc or "").strip("\n")
        merged = (base + "\n\n" if base else "") \
            + "## " + sec_name + "\n\n" + body + "\n"
    else:
        if end is None:
            end = len(lines)
        last = end - 1                     # 节内最后一个非空行
        while last > start and not lines[last].strip():
            last -= 1
        ins = last + 1
        block = [""] + body.splitlines()
        if ins < len(lines) and _SEC_HEAD_RE.match(lines[ins]):
            block.append("")               # 后面紧贴节头时补一空行
        merged = "\n".join(lines[:ins] + block + lines[ins:]).rstrip("\n") + "\n"
    project.write_file(path, merged)


def stats_mirror(proj: str, top: int = 3) -> str:
    """全书统计镜像：各章 by_rule per_kilo 的书级均值 top N → 一行注入文本。

    对 正文/ 已有各章跑 gates.scan_deslop + deslop_metrics.compute_metrics，
    聚合各规则 per_kilo 均值（缺席章节按 0 计＝书级平均密度口径——镜像的是
    「这本书整体在高频犯什么」，不是「犯起来有多凶」）。每次全量重算，不缓存。
    章数 <2 / 无可报规则 → ""（样本不足不立镜，与 per_book_threshold 同纪律）。
    """
    texts = []
    for _num, _title, p in project.list_chapters(proj):
        try:
            t = project.read_file(p)
        except (OSError, ValueError):
            continue
        if t.strip():
            texts.append(t)
    if len(texts) < 2:
        return ""
    sums = {}
    for t in texts:
        blocking, advisory = gates.scan_deslop(t, proj=proj)
        metrics = deslop_metrics.compute_metrics(t, blocking + advisory)
        for rule, entry in (metrics.get("by_rule") or {}).items():
            sums[rule] = sums.get(rule, 0.0) + float(entry.get("per_kilo") or 0.0)
    n = len(texts)
    ranked = sorted(((v / n, r) for r, v in sums.items() if v > 0),
                    key=lambda vr: (-vr[0], vr[1]))[:max(1, int(top))]
    if not ranked:
        return ""

    def _item(mean: float, rule: str) -> str:
        note = _RULE_NOTE.get(rule)
        if note:
            return "%s(%s 均 %.1f/千字)" % (note, rule, mean)
        return "%s 均 %.1f/千字" % (rule, mean)

    items = "、".join(_item(v, r) for v, r in ranked)
    return "【全书文风镜像】本章主动压低高频项：" + items


def fingerprint_line(proj: str) -> str:
    """「## 文风指纹」节原文（≤300 字，行边界截断；无文件/空节返回 ""）"""
    body = _split_sections(_read_doc(proj)).get(_SEC_FINGERPRINT, "") or ""
    body = body.strip()
    if not body:
        return ""
    if len(body) <= _FINGERPRINT_CAP:
        return body
    out, used = [], 0
    for ln in body.splitlines():
        need = len(ln) + (1 if out else 0)
        if used + need > _FINGERPRINT_CAP:
            break
        out.append(ln)
        used += need
    capped = "\n".join(out)
    return capped if capped.strip() else body[:_FINGERPRINT_CAP]


# ---------------- 模块 2：草稿 prompt 末位装配块 ----------------

def assembly_block(proj: str, *, stats_top: int = 3) -> str:
    """供草稿 prompt 末位拼接的整块文本（顺序纪律：指纹→镜像→锚，锚最后）。

    各部分为空时跳过该节（指纹与镜像同栖「文风纪律」头下，两者全空则该头
    也省；锚为空则锚头省）；全空返回 ""。读路径零副作用（不建文件）。
    """
    fp = fingerprint_line(proj)
    mirror = stats_mirror(proj, top=stats_top)
    anchor = anchor_text(proj)
    parts = []
    if fp or mirror:
        inner = "\n".join(x for x in (fp, mirror) if x)
        parts.append("【文风纪律（全书镜像与锚）】\n" + inner + "\n")
    if anchor:
        parts.append("【本书文风锚——动笔前最后读入的正文语态样本】\n" + anchor + "\n")
    if not parts:
        return ""
    return "\n\n" + "\n".join(parts)
