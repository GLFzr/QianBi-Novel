# -*- coding: utf-8 -*-
"""deslop 规则集：确定性毒句式拦截 + 密度型建议 + 破折号阈值策略"""
from app import deslop


def _rules(findings, level=None):
    return {f.rule for f in findings if level is None or f.level == level}


def test_clean_text_has_no_blocking():
    text = "他推开门，屋里的灯还亮着。桌上放着一碗没动过的面。"
    findings = deslop.scan_text(text)
    assert _rules(findings, "blocking") == set()


def test_not_is_comparison_blocking():
    findings = deslop.scan_text("这不是结束，而是开始。")
    assert "not-is-comparison" in _rules(findings, "blocking")


def test_trailer_ending_blocking():
    findings = deslop.scan_text("他不知道的是，门后还站着另一个人。")
    assert "trailer-ending" in _rules(findings, "blocking")


def test_cliche_word_blocking():
    findings = deslop.scan_text("她深吸一口气，推开了门。")
    assert "cliche-word" in _rules(findings, "blocking")


def test_em_dash_low_density_is_advisory():
    # 千字级文本里 2 处破折号 → 低于 6/千字阈值，仅建议
    text = "他沿着河边走。" * 100 + "远处传来汽笛——很长的一声——然后安静下来。"
    findings = deslop.scan_text(text)
    em = [f for f in findings if f.rule == "em-dash"]
    assert em and all(f.level == "advisory" for f in em)


def test_em_dash_high_density_is_blocking():
    # 短文本 7 处破折号 → 远超 6/千字阈值，阻断
    text = "他走了——又停——回头——看她——笑了笑——挥手——离开。"
    findings = deslop.scan_text(text)
    assert "em-dash" in _rules(findings, "blocking")


def test_findings_carry_span_and_hint():
    findings = deslop.scan_text("语气毫无波澜。")
    flat = [f for f in findings if f.rule == "flat-voice"]
    assert flat
    f = flat[0]
    assert f.text == "语气毫无波澜"
    assert f.fix_hint


# ---- 结构层 AI 味规则（2026-08 真机语料分析新增，守住防线）----

def test_gaze_density_advisory_on_heavy():
    # 视线词族 >1.5/千字 → 凝视循环 advisory；>5/千字 → blocking
    text = "他盯着她。她看向窗外。目光相遇。他注视地面。她望向远处。" * 4
    findings = deslop.scan_text(text)
    gaze = [f for f in findings if f.rule == "gaze-density"]
    assert gaze and gaze[0].level == "blocking"


def test_gaze_density_silent_on_clean():
    text = ("老周把烟头摁灭在铁皮罐里，起身去拉卷帘门。卷帘门卡了一半，"
            "他从底下钻出去，招呼街口下棋的张婶帮着扶一把。两人合力把门拉到底。") * 6
    findings = deslop.scan_text(text)
    assert not [f for f in findings if f.rule == "gaze-density"]


def test_brake_standalone_para():
    # 「没有×」短句独立成段 ≥2 → 结构型 advisory
    text = "他推门进去，屋里没人。\n\n他没有动。\n\n桌上摆着一封拆过的信。\n\n他没有说话。\n\n窗外在下雨。" * 1
    # 需要足够长度触发扫描：补一段无关正文
    text += "楼道的声控灯亮了一下又灭了。他站在原地听了一会儿，只有雨点砸在遮阳棚上的闷响。" * 3
    findings = deslop.scan_text(text)
    assert [f for f in findings if f.rule == "brake-standalone-para"]


def test_one_line_para_ratio():
    # 单句短段 >45% → 节奏模板化 advisory
    paras = ["\n".join([
        "门外有脚步声。",
        "他抬起头。",
        "灯闪了一下。",
        "没人说话。",
        "风停了。",
        "狗叫了两声。",
        "楼梯响了很久，来的人却在三楼拐弯走了，他等的那个人始终没有出现，桌上的茶已经凉透了，烟灰缸里堆着七个烟头。",
    ] * 1)]  # 6 短段 + 1 长段 → 6/7 = 86%
    text = "# 标题\n\n" + paras[0]
    # 保证字数过 1500：重复长段
    text += "\n\n" + ("他把这一段又从头理了一遍，从下午的传呼到巷口的陌生人，每一处对不上的细节都写在纸上，写完再划掉，划掉再写，最后把纸折成四折塞进外套内袋，起身时带倒了空茶杯也没回头。" * 20)
    findings = deslop.scan_text(text)
    assert [f for f in findings if f.rule == "one-line-para"]


def test_mengdi_density():
    text = "他猛地回头。她猛地站起来。门猛地开了。灯猛地灭了。他猛地握拳。"
    findings = deslop.scan_text(text)
    assert [f for f in findings if f.rule == "mengdi-density"]
