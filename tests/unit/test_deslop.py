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
