# -*- coding: utf-8 -*-
"""卡6S deslop 度量层（app/core/deslop_metrics.py，S6a 下沉 + deslop.py 复活/GateResult 扩展）

- ≥10 类合成毒文本被 scan_text 命中（本套种了 20+ 类，断言 ≥10 稳过）
- compute_metrics 与手算一致：AID=Σ(命中×权重)/千字、分规则 count/per_kilo/review
- trailer 收窄文末 600 可见字窗口：中段「没人知道」不报、文末仍报
- 节奏/连接度指标在可心算的小文本上逐值核对
全部纯本地零 API。
"""
import os
import re
import sys
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import deslop
from app.core import deslop_metrics
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
    "这意味着危险。也就是说他输了。问题在于没人信。",                # reasoning connector
    # reasoning 四桶密度（C16b/B6 四重门：无主语 mental + connector + modal + abstract，
    # 密度过 ≥18/千字——不带人称前缀避免改 telling-cognition 计数）
    "知道任务。这意味着风险。必须维持局面。任务与规则与责任。" * 6,  # reasoning ×42
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
    assert c["reasoning-chain"] == 1         # 聚合型（C16b/B6 四桶四重门起报一条）
    assert c["mengdi-density"] == 4
    assert c["em-dash"] == 2
    assert c["daizhe-adverb"] == 1
    assert c["quote-emphasis"] == 4
    assert c["metaphor-density"] == 11      # 好像 ×7 + 仿佛 ×4
    assert c["simile-marker-density"] == 4
    assert c["trailer-ending"] == 1
    assert c["trailer-summary"] == 1
    assert c["abstract-summary-tic"] == 7   # 这一刻…明白 ×2 + 从这一刻开始 ×2 + 命运齿轮 ×2
    #                                        + 新的开始 ×1（C16b/A9 并入 oh-story 增补分支）
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
    # C2 起 special/connectivity 为增量块：存量四键保留，新增读数键共存（M6/M9-M13）
    assert {"dialog_tag_ratio", "gaze_per_kilo", "brake_per_kilo",
            "quote_emphasis"} <= set(m["special"])


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


# ============ C2 指标扩展（M1-M14，t8_deslop_research §8.1；逐值手算对照）============

def _mk_finding(rule, start, end, level="advisory"):
    return deslop.Finding(rule=rule, level=level, message="", text="",
                          start=start, end=end)


def test_m1_escalate_cooccurrence_hotspots():
    es = deslop_metrics.escalate_cooccurrence
    # 3 类不同 rule 的 advisory 在 1000 字窗内 → 1 个热点（span 首尾 = 命中首尾）
    hs = es([_mk_finding("a", 10, 20), _mk_finding("b", 30, 40), _mk_finding("c", 50, 60)])
    assert len(hs) == 1
    assert hs[0]["start"] == 10 and hs[0]["end"] == 60
    assert hs[0]["rules"] == ["a", "b", "c"]
    # 同 rule ×3 不算共现（要不同 rule）
    assert es([_mk_finding("a", 10, 20), _mk_finding("a", 30, 40),
               _mk_finding("a", 50, 60)]) == []
    # 窗口边界：第三 rule 起点 = 首命中起点+1000 收进（<=）；+1002 排除
    assert len(es([_mk_finding("a", 0, 1), _mk_finding("b", 500, 501),
                   _mk_finding("c", 1000, 1001)])) == 1
    assert es([_mk_finding("a", 0, 1), _mk_finding("b", 500, 501),
               _mk_finding("c", 1002, 1003)]) == []
    # 聚合型（start==end 章级）与 blocking 不参与
    assert es([_mk_finding("a", 0, 0), _mk_finding("blk", 5, 8, "blocking"),
               _mk_finding("b", 10, 20), _mk_finding("c", 30, 40)]) == []


def test_m1_m8_m14_metrics_wiring():
    """热点内 advisory 加倍 + 规则种类多样性加权 + 分档，aid 本身保持兼容口径"""
    text = "字" * 2000
    findings = [_mk_finding("a", 10, 20), _mk_finding("b", 30, 40),
                _mk_finding("c", 50, 60), _mk_finding("d", 1500, 1510)]
    m = deslop_metrics.compute_metrics(text, findings)
    kilo = 2000 / 1000.0
    # aid 不含升档（存量口径零变更）
    assert m["aid"] == round(4 * 1.0 / kilo, 3)
    # M1：热点 1 个（d 在窗外）；热点内 3 条 advisory 各 ×2 → 额外 +3 权重
    assert m["cooccur"]["count"] == 1
    assert m["cooccur"]["hotspots"][0]["rules"] == ["a", "b", "c"]
    # M8：diversity = 0.7 + 0.3×min(4/10, 1) = 0.82；M1：(4+3)/2 × 0.82 = 2.87
    exp_adj = round((4 + 3) / kilo * (0.7 + 0.3 * min(4 / 10, 1)), 3)
    assert m["aid_adjusted"] == exp_adj == 2.87
    assert m["aid_adjusted"] > m["aid"]
    # M14 分档：2.87 → light
    assert m["aid_band"] == "light" and m["aid_strategy"]
    # 单 rule 无热点：aid_adjusted = aid × 0.73（diversity 下限 0.7+0.3×0.1）
    m2 = deslop_metrics.compute_metrics(text, [_mk_finding("a", 10, 20)])
    assert m2["cooccur"]["count"] == 0
    assert m2["aid_adjusted"] == round(1.0 / kilo * 0.73, 3)
    # M14 分档函数逐值
    assert deslop_metrics.aid_band(2.0)[0] == "clean"
    assert deslop_metrics.aid_band(2.1)[0] == "light"
    assert deslop_metrics.aid_band(10.0)[0] == "mixed"
    assert deslop_metrics.aid_band(10.1) == ("heavy", deslop_metrics.AID_HEAVY_STRATEGY)


def test_m2_lexdiv_block():
    assert deslop_metrics.charbigram_ttr("AABBCCDD") == 1.0       # AA AB BB BC CC CD DD 全不同
    assert deslop_metrics.charbigram_ttr("AAAA") == round(1 / 3, 3)   # AA ×3
    assert deslop_metrics.charbigram_ttr("甲") == 0.0             # 不足 2 字
    assert deslop_metrics.charbigram_ttr("") == 0.0
    assert deslop_metrics.type_token_ratio("AABB") == 0.5
    assert deslop_metrics.type_token_ratio("") == 0.0
    assert deslop_metrics.mono_func_share("的了") == 1.0           # 单字功能词 ×2 / 2 字
    assert deslop_metrics.mono_func_share("甲乙丙丁") == 0.0
    m = deslop_metrics.compute_metrics("AABBCCDD", [])
    assert set(m["lexdiv"]) == {"charbigram_ttr", "type_token_ratio", "mono_func_share"}
    assert m["lexdiv"]["charbigram_ttr"] == 1.0


def test_m3_rhythm_cv_burstiness_equal_run():
    # 与 test_rhythm_and_connectivity_hand_computed 同款文本：句长 [6, 26, 2, 3]
    text = ("第一句话很短。\n\n"
            "第二句话稍稍长一些，多写了几个字，让句子变得更长一点。\n\n"
            "短段。\n\n短段二。")
    m = deslop_metrics.compute_metrics(text, [])
    var, mean = 95.6875, 9.25                     # 既有用例手算值
    assert m["rhythm"]["sent_len_cv"] == round(var ** 0.5 / mean, 3)
    cv2 = var / (mean * mean)
    assert m["rhythm"]["burstiness"] == round((cv2 - 1) / (cv2 + 1), 3)
    assert m["rhythm"]["equal_len_run_max"] == 1   # 逐对长度差均超 15%
    # 完全均匀句长：CV=0、B=-1（规则周期端）
    m2 = deslop_metrics.compute_metrics("十字就是十字。十字就是十字。十字就是十字。", [])
    assert m2["rhythm"]["sent_len_cv"] == 0.0
    assert m2["rhythm"]["burstiness"] == -1.0
    # 近等长游程（手算）：10→11 差 1 < 1.65 收进；10→12 差 2 > 1.8 断开
    assert deslop_metrics.equal_len_run_max([]) == 0
    assert deslop_metrics.equal_len_run_max([10]) == 1
    assert deslop_metrics.equal_len_run_max([10, 11, 12]) == 3
    assert deslop_metrics.equal_len_run_max([10, 12]) == 1
    assert deslop_metrics.equal_len_run_max([10, 10, 26]) == 2


def test_m4_repetition_block():
    assert deslop_metrics.fourgram_repeat_ratio("甲乙丙丁甲乙丙丁") == 1.0
    #  甲乙丙丁 ×2 命中 → 4×2/8
    assert deslop_metrics.fourgram_repeat_ratio("甲乙丙丁甲乙丙丁甲乙丙丁") == 3.0
    #  甲乙丙丁×3 + 乙丙丁甲/丙丁甲乙/丁甲乙丙 各×2 → 4×9/12
    assert deslop_metrics.fourgram_repeat_ratio("甲乙丙丁戊") == 0.0
    assert deslop_metrics.fourgram_repeat_ratio("甲乙") == 0.0
    text = "甲乙丙丁甲乙丙丁"
    raw = text.encode("utf-8")
    assert deslop_metrics.zlib_ratio(text) == round(len(zlib.compress(raw)) / len(raw), 3)
    assert deslop_metrics.zlib_ratio("") == 0.0
    m = deslop_metrics.compute_metrics(text, [])
    assert m["repetition"]["fourgram_repeat_ratio"] == 1.0
    assert m["repetition"]["zlib_ratio"] == deslop_metrics.zlib_ratio(text)
    # 校准样本方向断言：循环稿压缩比 <0.2 < 正常文本（正常 0.33-0.39 / 循环 <0.10）
    normal = "\n\n".join([
        "陈默推开茶馆的木门，一股潮气混着旧报纸的味道扑面而来。柜台后的老者抬起眼皮，"
        "目光在他胸前的铜牌上停了半息，又慢慢垂下去。",
        "「客官打尖还是住店？」老者的声音沙哑，像是多年没开过口。陈默把铜牌放在柜面上，"
        "指节在木质台面上敲了两下。",
        "雨还在下。街对面的灯笼被风吹得左右摇晃，光影在积水里碎成一片。"
        "陈默找了靠窗的位置坐下，从怀里摸出一封火漆信，信封上的字迹被水渍晕开了大半。",
        "水开了。跑堂的伙计提着长嘴壶过来，铜壶嘴在桌沿上磕了一下，热气腾起来，"
        "把窗玻璃蒙住了一层白雾。陈默用袖子擦出一块巴掌大的清晰，看着外面。",
        "巷口有两个人在说话，声音压得很低。其中一个的袖口露出半截刺青，青色的鳞片，"
        "尾巴一直缠到手腕。陈默认得那个图案——三天前，在沉船的货箱上。",
        "他把这个念头压下去，端起茶碗吹了吹。茶是粗茶，涩味重，但烫，足够让手指稳定下来。"
        "信在碗底硌着桌面的木纹，边缘的一角翘起来，像一片干枯的叶子。",
    ] * 2)
    loop = "他看着天。他看着地。他看着自己的手。" * 20
    assert deslop_metrics.zlib_ratio(loop) < 0.2 < deslop_metrics.zlib_ratio(normal)


def test_m5_recap_overlap():
    # 本章前 8 字 5 个 4-gram；前章尾含 {甲乙丙丁} → 1/5
    assert deslop_metrics.recap_overlap("甲乙丙丁戊己庚辛", "一二三四甲乙丙丁") == 0.2
    assert deslop_metrics.recap_overlap("", "一二三四") == 0.0
    assert deslop_metrics.recap_overlap("甲乙丙丁", "") == 0.0
    assert deslop_metrics.recap_overlap("甲乙丙", "甲乙丙丁") == 0.0   # 不足 4 字
    tail = "他推开门，看见桌上放着一封信。"
    assert deslop_metrics.recap_overlap(tail + "后续情节另起。", tail * 3) > 0.3


def test_m6_dialog_ratio_and_book_band():
    text = "他说：「你好呀。」\n\n风把灯吹灭了。"
    # 引号内可见字 4（你好呀。）/ 全文可见字 16（他说：3 + 「你好呀。」6 + 风把灯吹灭了。7）
    assert deslop_metrics.dialog_ratio(text) == round(4 / 16, 3)
    assert deslop_metrics.dialog_ratio("") == 0.0
    m = deslop_metrics.compute_metrics(text, [])
    assert m["special"]["dialog_ratio"] == round(4 / 16, 3)
    # 书级带宽越界（题材签名不设全局阈；带参无效不判）
    off = deslop_metrics.dialog_band_offband
    assert off(0.10, 0.15, 0.32) is True     # 低于书级 P10
    assert off(0.20, 0.15, 0.32) is False    # 带内
    assert off(0.35, 0.15, 0.32) is True     # 高于书级 P90
    assert off(0.20, 0.3, 0.3) is False      # p90<=p10 不判
    assert off(0.20, None, 0.32) is False


def test_m7_percentile_and_per_book_threshold():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # 线性插值：pos = 9×0.9 = 8.1 → vs[8]×0.9 + vs[9]×0.1 = 9.1
    assert abs(deslop_metrics.percentile(vals, 0.9) - 9.1) < 1e-9
    assert deslop_metrics.percentile([], 0.9) == 0.0
    assert deslop_metrics.percentile([7], 0.9) == 7.0
    # M7：<3 章不启用（返回 0.0 = 退回全局阈）；≥3 章 = P90×1.2
    assert deslop_metrics.per_book_threshold([1, 2]) == 0.0
    assert deslop_metrics.per_book_threshold([]) == 0.0
    assert deslop_metrics.per_book_threshold(vals) == 10.92   # 9.1×1.2


def test_m9_ending_mode():
    sendoff = ("他打完了这一仗。\n\n"
               "夜色退去，晨光爬上城头。未来与希望都在前方，命运翻开了新的一页。")
    assert deslop_metrics.ending_mode(sendoff) == "sendoff"   # 末段抽象名词 ≥2 且无台词
    intro = "他打完了这一仗。\n\n夜色沉了下来。\n\n灯火一盏一盏熄了。\n\n他想，或许就这样也好。"
    assert deslop_metrics.ending_mode(intro) == "introspective"  # 末 3 段无台词无动作
    assert deslop_metrics.ending_mode("「走吧。」他说。\n\n夜里落了雪。") == "normal"
    assert deslop_metrics.ending_mode("") == "normal"
    m = deslop_metrics.compute_metrics(sendoff, [])
    assert m["special"]["ending_mode"] == "sendoff"


def test_m10_opening_ngram_max():
    same = "陈默推开大门。他走了进去。\n\n陈默推开屏风。屋里没人。\n\n陈默推开窗。雨声灌进来。"
    assert deslop_metrics.opening_ngram_max(same) == 3
    diff = "陈默推开大门。\n\n风从门缝里灌进来。\n\n灯在桌上晃。"
    assert deslop_metrics.opening_ngram_max(diff) == 1
    assert deslop_metrics.opening_ngram_max("") == 0
    m = deslop_metrics.compute_metrics(same, [])
    assert m["special"]["opening_ngram_max"] == 3


def test_m11_m12_m13_density_readings():
    text = "他走了吧。不过天还早，以及雨来了。他显然累了。他被记忆所淹没。"
    m = deslop_metrics.compute_metrics(text, [])
    narr = deslop_metrics.strip_quoted(text)
    nk = deslop_metrics.visible_chars(narr) / 1000.0
    # M13 语气词（叙述层）：吧 ×1
    exp_mood = round(len(re.findall(r"[啊吧呢嘛呀啦喔呗]", narr)) / nk, 3)
    assert m["connectivity"]["mood_particle_per_kilo"] == exp_mood
    # M13 转折/并列拆表（全文口径）：不过 ×1 / 以及 ×1
    bk = deslop_metrics.visible_chars(text) / 1000.0
    assert m["connectivity"]["turn_conn_per_kilo"] == round(1 / bk, 3)
    assert m["connectivity"]["coord_conn_per_kilo"] == round(1 / bk, 3)
    # M11 绝对化副词：显然 ×1
    exp_abs = round(len(re.findall(r"无疑|显然|必然|注定|毋庸置疑|理所当然|必定|绝对|断然|势必",
                                   narr)) / nk, 3)
    assert m["special"]["abs_assert_per_kilo"] == exp_abs
    # M12 被字结构：被记忆所淹 ×1（被+1-4字）
    exp_bei = round(len(re.findall(r"被[一-鿿]{1,4}", narr)) / nk, 3)
    assert m["special"]["bei_per_kilo"] == exp_bei


def test_c2_shape_additive_and_empty_safe():
    """形状变更登记：存量键零变更，新增键全部就位；空文本全读数安全"""
    m = deslop_metrics.compute_metrics("他走了。她来了。", [])
    for key in ("aid", "chars", "by_rule", "rhythm", "connectivity", "special", "guard"):
        assert key in m                                   # 0.22 存量七键
    for key in ("aid_adjusted", "aid_band", "aid_strategy",
                "lexdiv", "repetition", "cooccur"):
        assert key in m                                   # C2 顶层新增
    for key in ("sent_len_cv", "burstiness", "equal_len_run_max"):
        assert key in m["rhythm"]                         # M3
    for key in ("dialog_ratio", "opening_ngram_max", "ending_mode",
                "abs_assert_per_kilo", "bei_per_kilo"):
        assert key in m["special"]                        # M6/M9/M10/M11/M12
    for key in ("turn_conn_per_kilo", "coord_conn_per_kilo", "mood_particle_per_kilo"):
        assert key in m["connectivity"]                   # M13
    m0 = deslop_metrics.compute_metrics("", [])
    assert m0["lexdiv"] == {"charbigram_ttr": 0.0, "type_token_ratio": 0.0,
                            "mono_func_share": 0.0}
    assert m0["repetition"] == {"fourgram_repeat_ratio": 0.0, "zlib_ratio": 0.0}
    assert m0["cooccur"] == {"count": 0, "hotspots": []}
    assert m0["aid_adjusted"] == 0.0
    assert m0["aid_band"] == "clean"
    assert m0["special"]["ending_mode"] == "normal"
    assert m0["special"]["opening_ngram_max"] == 0
