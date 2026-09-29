# -*- coding: utf-8 -*-
"""质量闸门：字数校验 + 本地 AI 味扫描 → 裁决微循环走向

策略（config.gates.strategy）：
- mark_continue（默认）：修复失败 → 标待修继续写
- strict：修复失败 → 自动暂停等人（auto_pause）
"""
import logging
import os
import re

from .. import deslop, project
from ..slots import GATE_MARK_CONTINUE, GATE_STRICT


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


def scan_deslop(text: str) -> tuple:
    """返回 (blocking_findings, advisory_findings)"""
    findings = deslop.scan_text(text)
    blocking = [f for f in findings if f.level == "blocking"]
    advisory = [f for f in findings if f.level == "advisory"]
    return blocking, advisory


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
