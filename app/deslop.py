# -*- coding: utf-8 -*-
"""去 AI 味扫描器：本地正则规则集，检测网文 AI 写作痕迹

检测级别：
- blocking（阻断级）：确定性毒句式，必须修
- advisory（建议级）：密度型问题，提示人工复核
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
# 否定排比 "没有X，没有Y，只是Z" / "他没X，也没有Y。他只是Z"
NEGATION_PARADE = re.compile(r"没(?:有)?[^。！？!?\n]{1,20}[，,]没(?:有)?[^。！？!?\n]{1,20}")
# 音量反差腔 "声音不大/不高…却…"
VOICE_CONTRAST = re.compile(r"声音(?:不大|不高|很轻|低)[，,]?却")
# 无情绪声线
FLAT_VOICE = re.compile(r"语气毫无波澜|平静无波|声音平直|声音平平|听不出(?:任何)?情绪")
# "，带着……" 万能状语
DAIZHE_ADVERB = re.compile(r"[，,]带着[^。！？!?\n]{1,30}")
# 章末预告 "他不知道的是……"
TRAILER_ENDING = re.compile(r"(?:他|她|我)不知道的是")
# 预告式总结收尾
TRAILER_SUMMARY = re.compile(
    r"(?:没人知道|没有人知道)[^。！？!?\n]{0,30}|"
    r"(?:反击|复仇|战争|较量|故事|命运|一切)[^。！？!?\n]{0,12}才刚刚开始|"
    r"正朝着[^。！？!?\n]{0,20}压了过去|"
    r"即将拉开序幕"
)
# 抽象命运总结
FATE_SUMMARY = re.compile(
    r"(?:命运|宿命)[^。！？!?\n]{0,28}(?:齿轮|棋局|獠牙|改写|安排)|"
    r"这一刻[，,]?[^。！？!?\n]{0,24}(?:终于|才)(?:明白|意识到)|"
    r"从这一刻开始"
)
# 破折号（正文禁用）
EM_DASH = re.compile(r"——|—(?!-)")

# 模板化微表情（一级禁用词）
CLICHE_PATTERNS = [
    re.compile(r"仿佛|犹如|宛若|如同"),
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

# 抽象总结复读（密度型）
ABSTRACT_SUMMARY = [
    re.compile(r"这一刻[，,]?[^。！？!?\n]{0,24}(?:终于|才)(?:明白|意识到)"),
    re.compile(r"从这一刻开始"),
    re.compile(r"(?:命运|宿命)[^。！？!?\n]{0,28}(?:齿轮|棋局|獠牙|改写|推向|安排)"),
    re.compile(r"(?:反击|复仇|战争|较量|故事|命运)[^。！？!?\n]{0,12}才刚刚开始"),
]

# 解释链（密度型）
REASONING_CONNECTOR = re.compile(r"这意味着|也就是说|换句话说|问题在于|关键在于|想到这里")

# 引号强调滥用（叙述里短词加引号）
QUOTE_EMPHASIS = re.compile(r'[“"][^“”"\n]{1,4}[”"]')


def _in_dialogue(text: str, pos: int) -> bool:
    """判断位置是否在对话引号内（粗略：统计前面中文引号的开合）"""
    before = text[:pos]
    opens = before.count("“") + before.count("「")
    closes = before.count("”") + before.count("」")
    return opens > closes


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

    def add(rule, level, msg, m, hint=""):
        findings.append(Finding(
            rule=rule, level=level, message=msg,
            text=m.group(0), start=m.start() + body_offset, end=m.end() + body_offset,
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
    for m in NEGATION_PARADE.finditer(body):
        add("negation-parade", "blocking", "「没有X，没有Y」否定排比", m, "保留一项或改白描")
    for m in VOICE_CONTRAST.finditer(body):
        add("voice-contrast", "blocking", "「声音不大，却……」音量反差腔", m, "直接写台词内容或动作")
    for m in FLAT_VOICE.finditer(body):
        add("flat-voice", "blocking", "无情绪声线（毫无波澜/平静无波）", m, "写具体声音特征或动作")
    for m in TRAILER_ENDING.finditer(body):
        add("trailer-ending", "blocking", "「他不知道的是……」章末预告", m, "用具体钩子物件/事件收束")
    for m in TRAILER_SUMMARY.finditer(body):
        add("trailer-summary", "blocking", "预告式总结收尾（才刚刚开始/没人知道…）", m, "用未解决问题或具体动作收束")
    for m in FATE_SUMMARY.finditer(body):
        add("fate-summary", "blocking", "抽象命运总结（齿轮/棋局/这一刻终于明白）", m, "回到角色当下可见的动作/对话/物件")
    for m in EM_DASH.finditer(body):
        add("em-dash", "blocking", "正文禁用破折号", m, "用句号、逗号或动作断句")

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

    return findings


def summarize_findings(findings: list) -> dict:
    """按规则聚合统计"""
    stats = {}
    for f in findings:
        key = (f.rule, f.level)
        if key not in stats:
            stats[key] = {"rule": f.rule, "level": f.level, "count": 0,
                          "message": f.message, "fix_hint": f.fix_hint}
        stats[key]["count"] += 1
    return stats


def findings_to_prompt_text(findings: list) -> str:
    """把扫描结果转成给 LLM 的文本"""
    lines = []
    for f in findings:
        if f.text:
            lines.append(f"- [{f.level}] {f.message}：「{f.text}」→ 修法：{f.fix_hint}")
        else:
            lines.append(f"- [{f.level}] {f.message} → 修法：{f.fix_hint}")
    return "\n".join(lines)
