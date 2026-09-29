# -*- coding: utf-8 -*-
"""质量闸门：字数校验 + 本地 AI 味扫描 → 裁决微循环走向

策略（config.gates.strategy）：
- mark_continue（默认）：修复失败 → 标待修继续写
- strict：修复失败 → 自动暂停等人（auto_pause）

C4/C5（0.23.0 新增检测区）：生成退化检测（degeneration_findings，advisory 先观测）
与字数双带判定（word_double_band/check_word_double_band，±12% 常规带/±15% 硬带）。
"""
import logging
import os
import re
from collections import Counter

from .. import deslop, project
from ..slots import GATE_MARK_CONTINUE, GATE_STRICT
from . import deslop_metrics


class GateResult:
    def __init__(self):
        self.word_ok = True
        self.word_actual = 0
        self.word_target = 0
        self.need_enrich = False
        self.blocking_findings = []
        self.advisory_findings = []
        self.deslop_rounds_used = 0
        self.review_blocking = []       # 审校阻塞问题（文本）
        self.review_advisory = []        # 审校建议（文本）
        self.review_verdict = ""         # 最终审核 Agent 总评：PASS/PASS_WITH_NOTES/REJECT/REJECT_HARD
        self.review_rounds_used = 0
        self.final_status = "pass"   # pass / needs_fix
        self.metrics = {}            # 卡6S：deslop_metrics.compute_metrics 读数（改前/轮次随章落盘）

    @property
    def blocking_count(self) -> int:
        return len(self.blocking_findings)

    @property
    def advisory_count(self) -> int:
        return len(self.advisory_findings)

    def to_record(self) -> dict:
        rec = {
            "words": self.word_actual,
            "deslop_blocking": self.blocking_count,
            "deslop_advisory": self.advisory_count,
            "review_blocking": len(self.review_blocking),
            "status": self.final_status,
            # 卡6S：完整指标 dict（AID/分规则/节奏/连接度），未计算时为空 dict——
            # 随章记录落盘，章与章可横向对比、卷/书可看趋势
            "metrics": self.metrics,
        }
        return rec


def check_words(text: str, target: int, tolerance: float = 0.1) -> tuple:
    """返回 (ok, actual)；actual 低于 target*(1-tolerance) 则不达标"""
    actual = project.count_chars(text)
    return actual >= int(target * (1 - tolerance)), actual


def check_word_bounds(text: str, target: int, tolerance: float = 0.2) -> tuple:
    """字数双界检查：返回 (low_ok, high_ok, actual)

    low_ok  = actual >= target*(1-tolerance)         （不足需扩写）
    high_ok = actual <= target*(1+tolerance)         （超出需压缩）
    tolerance 默认 0.2：超 20% 视为超标（与写作 prompt 口径一致）。
    """
    actual = project.count_chars(text)
    low_ok = actual >= int(target * (1 - tolerance))
    high_ok = actual <= int(target * (1 + tolerance))
    return low_ok, high_ok, actual


def scan_deslop(text: str, proj: str = None) -> tuple:
    """返回 (blocking_findings, advisory_findings)。

    proj 给定时加载书级白名单（C16b/C3）：proj/.deslop-whitelist 每行一个字面量，
    命中白名单的字面 span 不参与扫描（世界观术语/招式名误报的解法）；不传 proj
    行为与 0.22 一致（stages/co_dialogue 既有调用面不变）。
    """
    whitelist = load_deslop_whitelist(proj) if proj else None
    findings = deslop.scan_text(text, whitelist=whitelist)
    blocking = [f for f in findings if f.level == "blocking"]
    advisory = [f for f in findings if f.level == "advisory"]
    return blocking, advisory


# 书级白名单（C16b/C3，oh-story style-whitelist.js 直译）：只认本书目录，
# 不继承工作区或他书的选择；长词优先掩码。
_WHITELIST_NAME = ".deslop-whitelist"


def load_deslop_whitelist(proj: str) -> list:
    """读 proj/.deslop-whitelist → 字面量列表（长词优先）。

    行格式：每行一个字面量，# 开头为注释；文件缺失/损坏 → 空表（fail-open，
    与 load_sensitive_words 同款纪律）。
    """
    if not proj:
        return []
    path = os.path.join(proj, _WHITELIST_NAME)
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return []
    out = [ln for ln in lines if ln and not ln.startswith("#")]
    out.sort(key=len, reverse=True)
    return out


def resolve_failed(ctx, reason: str, gr: GateResult):
    """修复（去味/审校）轮次耗尽仍失败时，按策略裁决。

    - mark_continue：标待修，继续写
    - strict：自动暂停等人处理（用户点「继续」后仍按待修继续）
    """
    gr.final_status = "needs_fix"
    strategy = ctx.cfg.get("gates", {}).get("strategy", GATE_MARK_CONTINUE)
    if strategy == GATE_STRICT:
        ctx.auto_pause(f"{reason}，自动修复后仍未通过，请人工处理")
    else:
        ctx.log("warn", f"{reason}，已标记「待修」，继续写作（可在章节详情中人工修改）")


def chapter_word_target(proj: str, num: int, default: int, source: list = None) -> int:
    """正文目标字数优先取本章细纲登记的字数目标（C2 联动）；缺省回退默认。

    防模型幻觉：细纲文本里的「字数目标」若与默认值偏差超过 50%，视为模型
    自造数字（曾出现细纲写 3000 而配置为 300 的污染），一律回退默认值。

    N-07：细纲读取失败不再静默回落——warning 带原因；调用方可传 source 列表
    接收取值出处（outline=细纲登记 / config_read_fail / config_deviation /
    config_absent），供门摘要区分「按哪个数、是否回落」。阈值语义未动。
    """
    _log = logging.getLogger("qianbi.gates")
    try:
        text = project.read_file(project.get_outline_path(proj, num))
    except Exception as e:  # noqa: BLE001
        _log.warning("第 %s 章 细纲字数目标读取失败（%s），回落配置值 %s", num, e, default)
        if source is not None:
            source.append("config_read_fail")
        return default
    if not (text or "").strip():
        # read_file 对缺失/空文件静默返回 ""——对字数闸门而言同样什么都没读到，
        # 必须与「读到了但没登记」区分（N-07：否则按错阈值判，可误锁/误放）
        _log.warning("第 %s 章 细纲不存在或为空，字数目标回落配置值 %s", num, default)
        if source is not None:
            source.append("config_read_fail")
        return default
    m = re.search(r"字数目标\s*[：:]\s*(\d+)", text or "")
    if m:
        target = int(m.group(1))
        if abs(target - default) <= default * 0.5:
            if source is not None:
                source.append("outline")
            return target
        _log.warning("第 %s 章 细纲字数目标 %s 与配置 %s 偏差过大，按配置执行（防模型幻觉）",
                     num, target, default)
        if source is not None:
            source.append("config_deviation")
        return default
    if source is not None:
        source.append("config_absent")
    return default


def word_count_precheck(proj: str, num: int, prose: str, cfg: dict) -> tuple:
    """字数预检（本地，零 LLM）：短章不得静默过审。

    实际字数 < 目标×(1-word_tolerance) 时，合成一条 [字数] 阻塞项并给 REJECT，
    调用方据此短路（跳过审校 LLM）。达标返回 ([], [], "")。

    Returns:
        (items, blocking, verdict) —— items 与 parse_final_review_v2 的 item 结构一致
    """
    gates_cfg = (cfg or {}).get("gates", {})
    if not gates_cfg.get("word_block_on_review", True):
        return [], [], ""
    default = int((cfg or {}).get("writing", {}).get("chapter_word_target", 3000))
    tolerance = float(gates_cfg.get("word_tolerance", 0.1))
    _src: list = []
    target = chapter_word_target(proj, num, default, source=_src)
    actual = project.count_chars(prose or "")
    floor = int(target * (1 - tolerance))
    if actual >= floor:
        return [], [], ""
    # N-07：门摘要写明目标字数取自哪、是否回落——短章申诉时能对上口径
    _src_txt = {"outline": "细纲登记",
                "config_read_fail": "配置值（细纲读取失败回落）",
                "config_deviation": "配置值（细纲登记偏差过大回落）",
                "config_absent": "配置值（细纲未登记）"}.get(_src[0] if _src else "", "配置值")
    text = (f"[字数] 第{num}章正文 {actual} 字，低于目标 {target}（来源：{_src_txt}；"
            f"容差 {tolerance:.0%}，下限 {floor}），需扩写达标后再过审")
    items = [{"dim": "D_PLOT", "level": "fail", "text": text,
              "quote": "", "root_layer": "ROOT_PROSE", "line": ""}]
    return items, [text], "REJECT"


# ============ 卡9-P4 本地规则质检（easy-writing 哲学移植：只拦明显写坏的硬伤） ============
# 误拦比漏报更伤——拦=停机等人。三规则：断流(blocking 信号)/复读(blocking)/敏感词(advisory)。

COLLAPSE_RATIO = 0.55   # 55% 断流闸阈值（原型坑②：与 90% 质量闸语义不同，绝不合并）

_SENSITIVE_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "assets", "sensitive_words.txt")


def check_collapse(text: str, target: int, ratio: float = None) -> tuple:
    """55% 断流闸：实际字数 < 目标×ratio(缺省 55%) → (True, actual)——「这章写崩了」信号。

    与 check_words / word_count_precheck 的 90% 质量闸语义分离：90% 闸触发
    扩写微循环（质量目标），55% 闸判定生成中断（故障，停机待确认）。
    两闸并存互不联动：60% 稿不触发断流闸但过不了质量闸，属正常扩写对象。
    """
    actual = project.count_chars(text)
    r = COLLAPSE_RATIO if ratio is None else ratio
    return actual < int(target * r), actual


def repeat_findings(text: str) -> list:
    """整段复读检测（P4 R2）：≥16 字段落（去空白归一）重复出现 → blocking，
    附 ≤3 条 60 字引文。返回 deslop.Finding（可并入既有 blocking 通道消费）。
    """
    seen, order = {}, []
    for p in re.split(r"\n\s*\n", text or ""):
        norm = re.sub(r"\s+", "", p)
        if len(norm) >= 16:
            if norm not in seen:
                order.append(norm)
            seen[norm] = seen.get(norm, 0) + 1
    dups = sorted(((p, seen[p]) for p in order if seen[p] > 1),
                  key=lambda t: -t[1])[:3]
    return [deslop.Finding(
        rule="paragraph-repeat", level="blocking",
        message="整段复读 ×%d（疑似生成循环）" % c,
        text=p[:60], start=0, end=0,
        fix_hint="删除重复段，保留信息量最全的一处；复读常伴字数不足，先查断流闸")
        for p, c in dups]


def load_sensitive_words(path: str = None) -> list:
    """assets/sensitive_words.txt → [(word, category)]；行格式「词条｜分类」或「词条」，
    # 开头为注释。文件缺失/损坏 → 空表（advisory 关闭，fail-open）。"""
    out = []
    try:
        with open(path or _SENSITIVE_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                t = line.strip()
                if not t or t.startswith("#"):
                    continue
                for sep in ("｜", "|"):
                    if sep in t:
                        w, cat = t.split(sep, 1)
                        break
                else:
                    w, cat = t, ""
                w = w.strip()
                if w:
                    out.append((w, cat.strip()))
    except OSError:
        return []
    return out


def sensitive_findings(text: str, words: list = None) -> list:
    """敏感词扫描：只提示不停机（advisory，发布前自检向）。

    悬疑修仙文「血/杀」高频是已知误报源——本族永远 advisory，绝不 blocking、
    绝不进停机裁决；词库按平台规则维护（assets/sensitive_words.txt）。
    """
    body = text or ""
    out = []
    for w, cat in (words if words is not None else load_sensitive_words()):
        n = body.count(w)
        if not n:
            continue
        i = body.find(w)
        ctx = re.sub(r"\s+", "", body[max(0, i - 12):i + len(w) + 12])
        out.append(deslop.Finding(
            rule="sensitive-word", level="advisory",
            message="敏感词[%s]「%s」×%d，首处上下文：…%s…（发布前自检，按平台规则人工取舍）"
                    % (cat or "未分类", w, n, ctx),
            text=w, start=i, end=i + len(w),
            fix_hint="平台雷区词：确认情节必需后保留，或换同义白描"))
    return out


def collapse_report(text: str, target: int) -> dict:
    """P4 质检单聚合入口：断流闸 + 整段复读 + 敏感词一次出全（draft 相位后调用）。

    collapsed=True 是独立于 word_ok 的 crash 信号——触发走 strict 停机待确认，
    不进 mark_continue 的标待修通道（接线点见 TODO，本批不接 stages）。
    """
    collapsed, actual = check_collapse(text, target)
    return {"collapsed": collapsed, "actual": actual, "target": target,
            "repeat": repeat_findings(text), "sensitive": sensitive_findings(text)}


# ============ C4 生成退化检测（0.23.0；oh-story check-degeneration.js 思想移植，t2 §5-Top4）============
# 检测对象是「生成过程退化」（复读膨胀/词汇坍缩/句式固化/截断/占位/元泄漏），与
# deslop 的「AI 文风痕迹」正交：退化是模型循环/断流的故障信号，deslop 是读感问题。
# 全部 advisory——先观测真机稿分布，绝不 blocking、绝不进停机裁决（误拦=停机等人，
# 与 P4 质检同纪律）。TODO(接线)：collapse_report/stages 消费点归后续批次，本批只
# 出独立检测函数。
#
# 阈值依据（qianbi 校准样本实测，smoke_tmp 校准脚本）：正常中文 charbigram_ttr
# 0.32-0.56、zlib_ratio 0.33-0.39；模型循环稿 bigram_ttr <0.10、zlib <0.10。

DEGEN_MIN_CHARS = 400          # 词汇坍缩/句式固化的最小样本（短文 n-gram 噪声大）
DEGEN_BIGRAM_TTR_FLOOR = 0.15  # 正常 0.32-0.56 / 循环 <0.10——取 0.15 留双侧余量
DEGEN_ADJ_MIN_LEN = 8          # 紧邻近同整行的最短归一长度（oh-story ADJACENT_MIN_LEN）
DEGEN_LINE_MIN_LEN = 12        # 全文复现通道的最短行长（oh-story 长句 ≥12 字）
DEGEN_LINE_REPEAT = 3          # ≥12 字整行全文出现 ≥3 次（oh-story 复读通道）
DEGEN_OPEN_MAX = 4             # 同段首 4 字开头的段落 ≥4 个（句式固化）
DEGEN_TRUNC_MIN_CHARS = 200    # 截断判定的最小正文长度
_TRUNC_TAIL_OK = set("。！？!?…”』」】)）…—")
_DEGEN_PLACEHOLDER_RE = re.compile(
    r"【待补】|【待填】|【待写】|【占位】|（待补）|（待填）|此处省略|TODO|FIXME")
_DEGEN_META_RE = re.compile(
    r"作为(?:一个)?AI|身为AI|人工智能助手|AI助手|语言模型|无法生成"
    r"|无法完成[^。！？!?\n]{0,12}(?:请求|任务|创作)|内容政策|该到下一章了"
    r"|以下是本章|以上是本章正文|本次生成|希望这段[^。！？!?\n]{0,12}符合")


def degeneration_findings(text: str) -> list:
    """生成退化检测（C4）：advisory 级 Finding 列表，规则 id 前缀 degeneration-*。

    六通道（oh-story check-degeneration.js 的 findRepetition/findTruncation/
    findPlaceholders/findMetaLeak 四通道 + 词汇坍缩/句式固化两个量化信号）：
    1. degeneration-repeat       复读膨胀：紧邻近同整行（≥8 字）连现 ≥2 处 /
                                 ≥12 字整行全文复现 ≥3 次
    2. degeneration-lexcollapse  词汇坍缩：字符 bigram TTR <0.15（正常 0.32-0.56）
    3. degeneration-pattern-fix  句式固化：同段首 4 字开头段落 ≥4 个
    4. degeneration-truncation   截断：正文 ≥200 字却无句末终止符收尾
    5. degeneration-placeholder  占位残留：【待补】/此处省略/TODO 类（raw 扫——
                                 台词内的占位同样是未完成信号）
    6. degeneration-metaleak     元泄漏：「作为AI/该到下一章了/以下是本章」类
                                 工程语（掩码后扫——台词内「作为AI」可能是角色设定）
    """
    body = text or ""
    out = []
    chars = deslop_metrics.visible_chars(body)
    # 1) 复读膨胀（oh-story findRepetition 双通道直译：紧邻整行 + 全文复现）
    lines = [re.sub(r"\s+", "", ln) for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    adjacent = sum(1 for a, b in zip(lines, lines[1:])
                   if len(a) >= DEGEN_ADJ_MIN_LEN and a == b)
    line_counts = Counter(ln for ln in lines if len(ln) >= DEGEN_LINE_MIN_LEN)
    multi = sum(c - 1 for c in line_counts.values() if c >= DEGEN_LINE_REPEAT)
    if adjacent >= 2 or multi >= 1:
        out.append(deslop.Finding(
            rule="degeneration-repeat", level="advisory",
            message=f"复读膨胀：紧邻整行重复 ×{adjacent}、长行全文复现 ×{multi}"
                    f"（生成循环信号）",
            text="", start=0, end=0,
            fix_hint="先查断流/重试链路；稿面删除重复段，保留信息量最全的一处"))
    # 2) 词汇坍缩 + 3) 句式固化（量化信号，大样本才判）
    if chars >= DEGEN_MIN_CHARS:
        ttr = deslop_metrics.charbigram_ttr(body)
        if 0 < ttr < DEGEN_BIGRAM_TTR_FLOOR:
            out.append(deslop.Finding(
                rule="degeneration-lexcollapse", level="advisory",
                message=f"词汇坍缩：字符 bigram TTR {ttr}（正常中文 0.32-0.56），"
                        f"用词面收窄到循环",
                text="", start=0, end=0,
                fix_hint="整章重写比逐句修补有效；先查是否同一场景/动作在原地打转"))
        open_max = deslop_metrics.opening_ngram_max(body)
        if open_max >= DEGEN_OPEN_MAX:
            out.append(deslop.Finding(
                rule="degeneration-pattern-fix", level="advisory",
                message=f"句式固化：{open_max} 个段落以同 4 字开头（模板复用）",
                text="", start=0, end=0,
                fix_hint="变化段落进入方式：动作/对话/物件/环境轮换开场"))
    # 4) 截断（oh-story findTruncation：正文收在非终止符上）
    stripped = body.rstrip()
    if chars >= DEGEN_TRUNC_MIN_CHARS and stripped \
            and stripped[-1] not in _TRUNC_TAIL_OK:
        out.append(deslop.Finding(
            rule="degeneration-truncation", level="advisory",
            message=f"疑似截断：正文 {chars} 字以「{stripped[-1]}」收尾，无句末终止符",
            text="", start=0, end=0,
            fix_hint="补完最后一句或截到最后完整句；截断常伴 token 上限/断流"))
    # 5) 占位残留（raw 扫）+ 6) 元泄漏（掩码后扫，台词豁免）
    ph = _DEGEN_PLACEHOLDER_RE.findall(body)
    if ph:
        out.append(deslop.Finding(
            rule="degeneration-placeholder", level="advisory",
            message=f"占位残留：「{'」「'.join(sorted(set(ph))[:4])}」"
                    f"（生成未完成/模板占位）",
            text=ph[0], start=body.find(ph[0]),
            end=body.find(ph[0]) + len(ph[0]),
            fix_hint="占位处补写实内容；成稿不得带【待补】类标记"))
    masked = deslop_metrics.mask_quoted(body)
    leaks = _DEGEN_META_RE.findall(masked)
    if leaks:
        out.append(deslop.Finding(
            rule="degeneration-metaleak", level="advisory",
            message=f"元泄漏：「{'」「'.join(sorted(set(leaks))[:4])}」"
                    f"（模型工程语进入正文）",
            text=leaks[0],
            start=masked.find(leaks[0]), end=masked.find(leaks[0]) + len(leaks[0]),
            fix_hint="删除元话语；叙述只写故事内世界，不写生成过程"))
    return out


# ============ C5 字数双带（oh-story wordcount_core.compute_wordcount_bands 实证参数，t2 §12.2）============
# 常规带（internal）±12% / 硬带（user）±15%：常规带内=绿；常规带外硬带内=advisory
# （作者带容忍）；出硬带=blocking。gates 侧纯判定函数——TODO(D-stages)：
# stages._mc_word_gate 的消费接线归 D-stages 领地；word_count_precheck 维持 90%
# 质量闸现状语义不动（消费面在 stages，双带是新增观测层不是替换）。
# 口径 TODO：qianbi project.count_chars 含标点，oh-story visibleLength 只数汉字/
# 字母数字（差约 2-5%，t2 §5 js→py 注意事项）——未来直移 storyctl 常数前需先统一。
WORD_BAND_INNER = 0.12
WORD_BAND_OUTER = 0.15


def word_double_band(actual: int, target: int, inner: float = None,
                     outer: float = None) -> dict:
    """字数双带判定（C5）：返回 {status, direction, actual, target, inner_low/high,
    outer_low/high, message}。

    status：ok（常规带内）/ advisory（常规带外、硬带内）/ blocking（出硬带）。
    边界含端点：actual==inner_low/inner_high → ok；==outer_low/outer_high →
    advisory；带界随 target 用 int 截断（与 check_word_bounds 同款取整口径）。
    """
    i = WORD_BAND_INNER if inner is None else float(inner)
    o = WORD_BAND_OUTER if outer is None else float(outer)
    t = max(int(target), 1)
    a = int(actual)
    il, ih = int(t * (1 - i)), int(t * (1 + i))
    ol, oh = int(t * (1 - o)), int(t * (1 + o))
    if il <= a <= ih:
        status = "ok"
    elif ol <= a <= oh:
        status = "advisory"
    else:
        status = "blocking"
    direction = "" if status == "ok" else ("low" if a < t else "high")
    band_txt = {"ok": "常规带内",
                "advisory": "越出常规带（作者带容忍）",
                "blocking": "越出硬带"}[status]
    message = (f"{a} 字 / 目标 {t}：{band_txt}"
               f"（常规带 [{il}, {ih}]，硬带 [{ol}, {oh}]）")
    return {"status": status, "direction": direction, "actual": a, "target": t,
            "inner_low": il, "inner_high": ih, "outer_low": ol, "outer_high": oh,
            "message": message}


def check_word_double_band(text: str, target: int, inner: float = None,
                           outer: float = None) -> dict:
    """C5 判定入口（正文文本版）：count_chars 口径与 word 闸门族一致"""
    return word_double_band(project.count_chars(text or ""), target, inner, outer)
