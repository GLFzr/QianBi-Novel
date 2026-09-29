# -*- coding: utf-8 -*-
"""C4 生成退化检测 + C5 字数双带（gates.degeneration_findings / word_double_band）

- 退化六通道：正例逐通道命中、正常文本零命中（防误拦=防停机等人）
- 台词豁免：引号内的「作为AI」是角色设定，不判元泄漏
- 双带边界：±12% 常规带内绿 / 常规带外硬带内 advisory / 出硬带 blocking（含端点）
全部纯本地零 API；advisory 级（先观测，绝不 blocking、绝不进停机裁决）。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import gates

_NORMAL_PARA = (
    "陈默推开茶馆的木门，一股潮气混着旧报纸的味道扑面而来。柜台后的老者抬起眼皮，"
    "目光在他胸前的铜牌上停了半息，又慢慢垂下去。\n\n"
    "「客官打尖还是住店？」老者的声音沙哑，像是多年没开过口。陈默把铜牌放在柜面上，"
    "指节在木质台面上敲了两下。\n\n"
    "雨还在下。街对面的灯笼被风吹得左右摇晃，光影在积水里碎成一片。"
    "陈默找了靠窗的位置坐下，从怀里摸出一封火漆信，信封上的字迹被水渍晕开了大半。\n\n"
    "水开了。跑堂的伙计提着长嘴壶过来，铜壶嘴在桌沿上磕了一下，热气腾起来，"
    "把窗玻璃蒙住了一层白雾。陈默用袖子擦出一块巴掌大的清晰，看着外面的雨势。\n\n"
    "巷口有两个人在说话，声音压得很低。其中一个的袖口露出半截刺青，青色的鳞片，"
    "尾巴一直缠到手腕。陈默认得那个图案——三天前，在沉船的货箱上见过一模一样的纹样。"
)


def _rules(findings):
    return {f.rule for f in findings}


def _levels(findings):
    return {f.level for f in findings}


# ============ C4 退化检测 ============

def test_normal_text_zero_degeneration():
    """正常文本六通道全静默（advisory 也要防误拦）"""
    assert gates.degeneration_findings(_NORMAL_PARA) == []


def test_degeneration_all_advisory_level():
    """退化检测永远 advisory——绝不 blocking、绝不进停机裁决"""
    loop = "\n\n".join(["他看着天。他看着地。他看着自己的手。" * 4] * 6)
    fs = gates.degeneration_findings(loop + "作为AI，我无法生成该内容。【待补】")
    assert fs and _levels(fs) == {"advisory"}


def test_degeneration_repeat_adjacent_and_multi():
    line = "他站起来，向前走，摸到了一堵冰冷墙壁。"
    # 紧邻整行重复 ≥2 处（3 连行）→ 复读膨胀
    adjacent = "\n\n".join([line] * 3) + "\n\n他终于找到了出口。"
    assert "degeneration-repeat" in _rules(gates.degeneration_findings(adjacent))
    # 非紧邻、≥12 字整行全文复现 ≥3 次 → 同通道
    spread = "\n".join([line, "中间隔了一行别的内容写点别的。", line,
                        "再隔一行写点不同的东西。", line])
    assert "degeneration-repeat" in _rules(gates.degeneration_findings(spread))
    # 单次紧邻重复不报（有意复沓留人工；oh-story 同款：一次是修辞，成才是循环）
    once = line + "\n" + line
    assert "degeneration-repeat" not in _rules(gates.degeneration_findings(once))


def test_degeneration_lexcollapse_and_pattern_fix():
    # 词汇坍缩：模型循环稿（校准样本 bigram TTR≈0.03，正常 0.32-0.56）
    loop = "\n\n".join(["他看着天。他看着地。他看着自己的手。" * 4] * 6)
    rules = _rules(gates.degeneration_findings(loop))
    assert "degeneration-lexcollapse" in rules
    assert "degeneration-pattern-fix" in rules      # 6 段同「他看着天」开头 ≥4
    # 3 段同开头不报（阈值 4；短文 <400 字不判）
    three = "\n\n".join(["陈默推开门走了进去。屋里陈设如旧。"] * 3)
    assert "degeneration-pattern-fix" not in _rules(gates.degeneration_findings(three))


def test_degeneration_truncation():
    # ≥200 字正文收在非终止符上 → 截断
    cut = _NORMAL_PARA + "他忽然想起一件事，"
    assert "degeneration-truncation" in _rules(gates.degeneration_findings(cut))
    # 句末终止符收尾 / 短文不判
    ok = _NORMAL_PARA + "他忽然想起一件事。"
    assert "degeneration-truncation" not in _rules(gates.degeneration_findings(ok))
    assert "degeneration-truncation" not in _rules(gates.degeneration_findings("短文，"))


def test_degeneration_placeholder_and_metaleak():
    ph = _NORMAL_PARA + "\n\n【待补】此处后续再写。"
    assert "degeneration-placeholder" in _rules(gates.degeneration_findings(ph))
    assert "degeneration-metaleak" in _rules(
        gates.degeneration_findings(_NORMAL_PARA + "作为AI，我无法生成该内容。"))
    # 工程语谱系：「该到下一章了」泄漏（DeepSeek 型真机病灶）
    assert "degeneration-metaleak" in _rules(
        gates.degeneration_findings(_NORMAL_PARA + "好，该到下一章了。"))
    # 台词豁免：引号内「作为AI」是角色设定（元泄漏只在叙述层判）
    in_quote = "「作为AI，我当然记得你说过的话。」她答。"
    assert gates.degeneration_findings(in_quote) == []


# ============ C5 字数双带 ============

def test_word_double_band_constants_and_bounds():
    """storyctl 实证参数锚：常规带 ±12% / 硬带 ±15%（wordcount_core 实证）"""
    assert gates.WORD_BAND_INNER == 0.12
    assert gates.WORD_BAND_OUTER == 0.15
    t = 3000
    il, ih = int(t * (1 - 0.12)), int(t * (1 + 0.12))
    ol, oh = int(t * (1 - 0.15)), int(t * (1 + 0.15))
    assert (il, ih) == (2640, 3360)
    d = gates.word_double_band(t, t)
    assert d["inner_low"] == il and d["inner_high"] == ih
    assert d["outer_low"] == ol and d["outer_high"] == oh


def test_word_double_band_boundaries():
    wb = gates.word_double_band
    t = 3000
    il, ih = int(t * (1 - 0.12)), int(t * (1 + 0.12))
    ol, oh = int(t * (1 - 0.15)), int(t * (1 + 0.15))
    # 常规带内（含端点）→ ok
    assert wb(t, t)["status"] == "ok"
    assert wb(il, t)["status"] == "ok"
    assert wb(ih, t)["status"] == "ok"
    # 常规带外、硬带内（含端点）→ advisory + 方向
    d_low = wb(il - 1, t)
    assert d_low["status"] == "advisory" and d_low["direction"] == "low"
    d_high = wb(ih + 1, t)
    assert d_high["status"] == "advisory" and d_high["direction"] == "high"
    assert wb(ol, t)["status"] == "advisory"
    assert wb(oh, t)["status"] == "advisory"
    # 出硬带 → blocking + 方向
    d_blk = wb(ol - 1, t)
    assert d_blk["status"] == "blocking" and d_blk["direction"] == "low"
    d_blk2 = wb(oh + 1, t)
    assert d_blk2["status"] == "blocking" and d_blk2["direction"] == "high"
    # message 带关键数字（申诉时能对上口径）
    assert str(ol - 1) in d_blk["message"] and str(t) in d_blk["message"]
    assert "2640" in d_blk["message"]


def test_word_double_band_text_entry_and_custom():
    """文本入口走 count_chars 口径；自定义带宽可覆写"""
    assert gates.check_word_double_band("字" * 3000, 3000)["status"] == "ok"
    assert gates.check_word_double_band("字" * 2600, 3000)["status"] == "advisory"
    assert gates.check_word_double_band("", 3000)["status"] == "blocking"
    # target=1000 整数界：常规带 [880, 1120] / 硬带 [850, 1150]
    d = gates.check_word_double_band("字" * 1151, 1000)
    assert d["status"] == "blocking" and d["outer_high"] == 1150
    # 自定义带宽
    assert gates.word_double_band(950, 1000, inner=0.05, outer=0.1)["status"] == "ok"
    assert gates.word_double_band(949, 1000, inner=0.05, outer=0.1)["status"] == "advisory"
    assert gates.word_double_band(900, 1000, inner=0.05, outer=0.1)["status"] == "advisory"
    assert gates.word_double_band(899, 1000, inner=0.05, outer=0.1)["status"] == "blocking"
