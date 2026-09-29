# -*- coding: utf-8 -*-
"""卡6S deslop 度量层（app/deslop_metrics.py + deslop.py 复活/GateResult 扩展）

- ≥10 类合成毒文本被 scan_text 命中（本套种了 20+ 类，断言 ≥10 稳过）
- compute_metrics 与手算一致：AID=Σ(命中×权重)/千字、分规则 count/per_kilo/review
- trailer 收窄文末 600 可见字窗口：中段「没人知道」不报、文末仍报
- 节奏/连接度指标在可心算的小文本上逐值核对
全部纯本地零 API。
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import deslop
from app import deslop_metrics
from app.core import gates

_FILLER = "他沿着河堤慢慢走，水面浮着零星的灯光，远处偶尔传来一声船笛，风把凉意送到领口里。"

_POISON_BLOCKS = [
    _FILLER * 7,                                                   # 长段落（>200 字）
    "这不是结束，而是新的开始。",                                   # not-is-comparison
    "胜利是必然的，不是偶然的。",                                   # reverse-not-is
    "没有人来，没有敲门声。",                                       # negation-parade
    "他的声音不大，却压住了整间屋子。",                             # voice-contrast
    "她的语气毫无波澜。",                                           # flat-voice
    "他深吸一口气，眼中闪过一丝疲惫。",                             # cliche-word ×3
    "他攥紧拳头，带着不肯认输的狠劲。",                             # daizhe-adverb
    "他知道答案。她明白结局。我意识到危险逼近。",                    # telling-cognition ×3
    "他盯着她。她看向窗外。他注视地面。她望向远处。目光相遇又分开。",  # gaze ×5
    "他猛地起身。她猛地回头。门猛地关上。火苗猛地窜起。",            # mengdi ×4
    "脚步声近了——又远了——彻底消失。",                              # em-dash ×2
    ("这好像是一种默契。那好像是巧合。灯好像是暗的。话好像是真是假。"
     "路好像还长。夜好像很深。人好像很多。"),                        # 好像 ×7 → metaphor-density
    "雨丝仿佛帘幕。雾仿佛海。灯仿佛星。记忆仿佛潮水。",              # 仿佛 ×4 → simile-marker-density
    "这意味着危险。也就是说他输了。问题在于没人信。",                # reasoning-chain ×3
    '"自由"和"救赎"之外，还有"代价"与"选择"。',                      # quote-emphasis ×4（ASCII 引号）
    "他没有回头。她没有接话。",                                     # brake-sentence（合计 4 处）
    "他没有动。",                                                   # brake-standalone-para 1/2
    "他没有说话。",                                                 # brake-standalone-para 2/2
    "门开了。他进去。灯亮着。屋里没人。桌上有灰。他坐下。",          # period-stutter（连续 6 短句）
    # —— 文末 600 字窗口内：预告族 ——
    "这一刻，他终于明白。从这一刻开始。命运的齿轮开始转动。",
    "这一刻，她终于明白。从这一刻开始。命运的齿轮开始转动。",        # abstract ×6 + fate ×6
    "他不知道的是，门口站着一个人。",                               # trailer-ending
    "没人知道他去了哪里。",                                         # trailer-summary
]
_POISON_TEXT = "\n\n".join(_POISON_BLOCKS)


def _rules(findings, level=None):
    return {f.rule for f in findings if level is None or f.level == level}


def _counts(metrics):
    return {r: v["count"] for r, v in metrics["by_rule"].items()}


def test_poison_text_hits_at_least_ten_rule_families():
    findings = deslop.scan_text(_POISON_TEXT)
    assert len(_rules(findings)) >= 10
    assert "not-is-comparison" in _rules(findings, "blocking")
    assert "trailer-summary" in _rules(findings, "blocking")
    assert "cliche-word" in _rules(findings, "blocking")


def test_metrics_match_hand_computation():
    text = _POISON_TEXT
    findings = deslop.scan_text(text)
    m = deslop_metrics.compute_metrics(text, findings)

    # 手算口径①：可见字数（与 project.count_chars 同一定义的独立复写）
    expect_chars = len(re.sub(r"[#>*`\-\[\]()]", "", re.sub(r"\s+", "", text)))
    assert m["chars"] == expect_chars
    kilo = expect_chars / 1000.0

    # 手算口径②：AID = Σ(命中数×权重)/千字，权重 blocking=3 / advisory=1
    n_blk = sum(1 for f in findings if f.level == "blocking")
    n_adv = sum(1 for f in findings if f.level == "advisory")
    assert m["aid"] == round((3 * n_blk + n_adv) / kilo, 3)

    # 手算口径③：逐规则 planted 命中数（毒文本按构造精确投放）
    c = _counts(m)
    assert c["not-is-comparison"] == 1
    assert c["reverse-not-is"] == 1
    assert c["negation-parade"] == 1
    assert c["voice-contrast"] == 1
    assert c["flat-voice"] == 1
    assert c["cliche-word"] == 3            # 深吸一口气 / 眼中闪过 / 一丝
    assert c["telling-cognition"] == 3
    assert c["reasoning-chain"] == 3
    assert c["mengdi-density"] == 4
    assert c["em-dash"] == 2
    assert c["daizhe-adverb"] == 1
    assert c["quote-emphasis"] == 4
    assert c["metaphor-density"] == 11      # 好像 ×7 + 仿佛 ×4
    assert c["simile-marker-density"] == 4
    assert c["trailer-ending"] == 1
    assert c["trailer-summary"] == 1
    assert c["abstract-summary-tic"] == 6   # 这一刻…明白 ×2 + 从这一刻开始 ×2 + 命运齿轮 ×2
    assert c["fate-summary"] == 6
    assert c["brake-sentence"] == 1         # 聚合型 finding
    assert c["brake-standalone-para"] == 1
    assert c["period-stutter"] == 1
    assert c["long-paragraph"] == 1
    # per_kilo 与手算一致
    assert m["by_rule"]["cliche-word"]["per_kilo"] == round(3 / kilo, 3)
    # review 二轴登记
    assert m["by_rule"]["not-is-comparison"]["review"] == "semantic"
    assert m["by_rule"]["cliche-word"]["review"] == "mechanical"


def test_aid_weights_configurable():
    findings = deslop.scan_text("这不是结束，而是新的开始。")
    m = deslop_metrics.compute_metrics("这不是结束，而是新的开始。" * 10, findings,
                                       weights={"blocking": 2.0, "advisory": 0.5})
    kilo = deslop_metrics.visible_chars("这不是结束，而是新的开始。" * 10) / 1000.0
    assert m["aid"] == round(2.0 * len(findings) / kilo, 3)


def test_trailer_window_narrowed():
    """中段「没人知道」不报（trailer 是章末病），文末 600 可见字内仍报"""
    filler = _FILLER * 30                       # ≈1170 字 > 600 窗口
    mid = filler + "没人知道他去了哪里。" + filler
    assert not [f for f in deslop.scan_text(mid) if f.rule == "trailer-summary"]
    end = filler + "没人知道他去了哪里。"
    hits = [f for f in deslop.scan_text(end) if f.rule == "trailer-summary"]
    assert hits and hits[0].text.startswith("没人知道")
    # 窗口边界内全文 <600 字时行为不变（既有回归：短文本 trailer-ending 仍报）
    assert "trailer-ending" in _rules(deslop.scan_text("他不知道的是，门后还站着另一个人。"),
                                      "blocking")


def test_rhythm_and_connectivity_hand_computed():
    text = ("第一句话很短。\n\n"
            "第二句话稍稍长一些，多写了几个字，让句子变得更长一点。\n\n"
            "短段。\n\n短段二。")
    m = deslop_metrics.compute_metrics(text, [])
    # 可见字：第一句话很短。(7) + 第二…一点。(27) + 短段。(3) + 短段二。(4) = 41
    assert m["chars"] == 41
    # 句长（句号切分，丢弃空尾）：[6, 26, 2, 3] → mean 9.25；总体方差 382.75/4 = 95.69
    assert m["rhythm"]["sent_len_mean"] == 9.25
    assert m["rhythm"]["sent_len_var"] == 95.69
    # 段长：[7, 27, 3, 4] → mean 10.25，方差同为 95.69；短段(≤15)占比 3/4；最长连短游程 2
    assert m["rhythm"]["para_len_mean"] == 10.25
    assert m["rhythm"]["para_len_var"] == 95.69
    assert m["rhythm"]["short_para_ratio"] == 0.75
    assert m["rhythm"]["max_short_run"] == 2
    # 连接度：无白话连接词；功能词 = 很 ×1 + 了 ×1 + 让 ×1 + 得 ×1 = 4；无 ≥30 字承接句
    assert m["connectivity"]["conn_per_kilo"] == 0.0
    assert m["connectivity"]["func_per_kilo"] == round(4 / 0.041, 3)
    assert m["connectivity"]["long_bridge_ratio"] == 0.0
    assert m["special"] and set(m["special"]) == {
        "dialog_tag_ratio", "gaze_per_kilo", "brake_per_kilo", "quote_emphasis"}


def test_long_bridge_ratio_and_dialog_tag():
    text = ("「你到底想说什么。」他说。\n\n"
            "她把那份按着红手印的契约推过桌面，一字一句地把当年的旧账从头到尾数了一遍给他听。")
    m = deslop_metrics.compute_metrics(text, [])
    # 句号切分出 3 句（「…说」「」他说、长句），其中长句 ≥30 可见字 → 1/3
    assert m["connectivity"]["long_bridge_ratio"] == round(1 / 3, 3)
    # 1 个对话引号跨度、命中 1 个对话标签 → 比 1.0
    assert m["special"]["dialog_tag_ratio"] == 1.0


def test_empty_text_and_empty_findings_safe():
    m = deslop_metrics.compute_metrics("", [])
    assert m["aid"] == 0.0 and m["by_rule"] == {}
    assert m["rhythm"]["sent_len_mean"] == 0.0 and m["rhythm"]["max_short_run"] == 0


def test_compute_guard_ratios():
    before = "第一段。\n\n第二段。\n\n第三段。"
    after = "第一段改了。\n\n第二段。"
    g = deslop_metrics.compute_guard(before, after, new_must_violations=2)
    assert g["chars_kept_ratio"] == round(
        deslop_metrics.visible_chars(after) / deslop_metrics.visible_chars(before), 3)
    assert g["para_delta"] == -1
    assert g["new_must_violations"] == 2


def test_gate_result_carries_metrics_field():
    gr = gates.GateResult()
    assert gr.to_record()["metrics"] == {}
    gr.metrics = {"aid": 3.2, "by_rule": {"cliche-word": {"count": 2}}}
    rec = gr.to_record()
    assert rec["metrics"]["aid"] == 3.2
    assert rec["deslop_blocking"] == 0 and rec["status"] == "pass"


def test_summarize_findings_revived_as_by_rule_base():
    """B1 死函数复活的直证：summarize_findings 聚合 (rule, level) 计数"""
    findings = deslop.scan_text("他深吸一口气。这不是结束，而是新的开始。深吸一口气之后他后退半步。")
    stats = deslop.summarize_findings(findings)
    assert stats[("cliche-word", "blocking")]["count"] == 2
    assert stats[("not-is-comparison", "blocking")]["count"] == 1
    m = deslop_metrics.compute_metrics("他深吸一口气。", findings)
    assert m["by_rule"]["cliche-word"]["count"] == 2
