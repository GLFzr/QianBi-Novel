# -*- coding: utf-8 -*-
"""B1 爽点引擎回归（app/core/satisfaction.py + l0_checks 节拍扩展 + 装配接线）

台账判据背景（L5-B1，质量线唯一 P0）：33 章无一次完整「压抑→反转→结算」闭环。
- `writing.satisfaction_engine` 缺省 False：细纲/正文/L0 三处装配字节与 0.19.x
  逐字节一致（变量隔离纪律；off 路径由 tests/probe_prompt_baseline.py 兜底）；
- 开启：细纲模板携带「本章爽点节拍」三拍字段指令；正文轮对带节拍章注入兑现
  指令（显式「本章无节拍」空档=空串，不每章强塞）；L0 账本对照加节拍检查
  （复用推迟语式金标形态，fail-open）。
全部离线零 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import config
import app.prompts as prompts
from app.prompts.planning import CHAPTER_OUTLINE_PROMPT
from app.prompts.writing import PROSE_WRITING_PROMPT
from app.core import stages
from app.core.l0_checks import beat_findings, build_v5_block, payoff_findings
from app.core import satisfaction as sat

# ---------------- 夹具 ----------------

OUTLINE_BEAT = """### 第 6 章：反杀
- 爽点：陈默当众揭穿中介压价套路，押金全额到账。
- 本章爽点节拍：压抑（陈默被中介扣押金并当众羞辱）→ 反转（亮出录音当场对峙）→ 结算（押金全额到账，围观房客态度反转）
- 结尾：陈默走出中介门店。
"""

OUTLINE_NO_BEAT = """### 第 7 章：过场
- 爽点：无显性爽点。本章功能是铺垫。
- 本章爽点节拍：本章无节拍（低压承接章，延续上一章余波）
- 结尾：门外有人敲门。
"""

OUTLINE_MALFORMED = """### 第 8 章：起承
- 爽点：应有兑现
- 本章爽点节拍：压抑（被威胁）→ 反转（找到证据）
- 结尾：证据摊在桌上。
"""

OUTLINE_NO_LINE = "### 第 9 章：旧格式\n- 爽点：正常承诺\n- 结尾：收束。\n"

PROSE_DEFER = ("陈默盯着中介的账单，心里憋着火。"
               "「算了吧，」他对自己说，「这笔账改日再算也不迟。」他转身回了屋。")
PROSE_CLEAN = "陈默把押金单拍在桌上，中介脸色发白，押金当场到账，围观房客态度反转。"

PROSE_KW = dict(
    project_header="【项目设定基准】", chapter_header="【第 6 章共享上下文】",
    chapter_num=6, worldbook_block="（世界书）", regex_block="（正则）",
    word_target=3000, next_chapter_brief="（下一章预告）", user_guidance="无特殊指导",
    user_ideas="（无）", style_discipline=prompts.STYLE_DISCIPLINE,
    used_setpieces="（无）", craft_block="（工艺路线）", author_note="（无）",
    tic_blacklist="（黑名单）",
)

OUTLINE_KW = dict(
    project_header="P", volume_outline="V", nearby_outlines="N",
    core_setting_brief="C", global_summary="G", recent_summaries="R",
    character_states="S", start_chapter=6, end_chapter=7, count=2,
    chapter_words=3000, chapter_words_max=3300, previous_ending="E",
    foreshadows="F", unit_contract="U", genre_block="GB",
    worldbook_block="WB", regex_block="RG", user_directive="UD",
)

CFG_ON = {"writing": {"satisfaction_engine": True}}


# ---------------- 开关缺省态 ----------------

def test_default_config_switch_off():
    """出厂缺省关闭；off 时引擎产出必须全为空串（装配字节不变的根）"""
    assert config.DEFAULT_CONFIG["writing"]["satisfaction_engine"] is False
    assert sat.outline_directive({}) == ""
    assert sat.outline_directive({"writing": {}}) == ""
    assert sat.outline_directive({"writing": {"satisfaction_engine": False}}) == ""
    assert stages._satisfaction_outline_directive({"writing": {}}) == ""


# ---------------- 细纲模板：off 逐字节一致 / on 携带节拍字段指令 ----------------

def test_outline_prompt_off_byte_identical():
    """off：真实模板装配 + 空指令块 == 纯基线装配（逐字节）"""
    base = CHAPTER_OUTLINE_PROMPT.format(**OUTLINE_KW)
    assert CHAPTER_OUTLINE_PROMPT.format(**OUTLINE_KW) + \
        stages._satisfaction_outline_directive({"writing": {}}) == base


def test_outline_prompt_on_carries_beat_field():
    """on：真实模板装配追加节拍字段指令——三拍结构、显式空档、连排纪律齐全"""
    text = CHAPTER_OUTLINE_PROMPT.format(**OUTLINE_KW) + \
        stages._satisfaction_outline_directive(CFG_ON)
    assert text != CHAPTER_OUTLINE_PROMPT.format(**OUTLINE_KW)
    assert "本章爽点节拍" in text
    for seg in ("压抑", "反转", "结算"):
        assert seg in text, "三拍字段指令缺段：%s" % seg
    assert "本章无节拍" in text, "必须允许显式空档（不每章强塞）"
    assert "连续不得超过 2 章" in text


# ---------------- 正文 PROSE：off 字节一致 / on 注入兑现指令 / 空档不强塞 ----------------

def test_prose_prompt_off_byte_identical():
    base = PROSE_WRITING_PROMPT.format(**PROSE_KW)
    assert base + "" == base


def test_prose_prompt_on_injects_beat_contract():
    base = PROSE_WRITING_PROMPT.format(**PROSE_KW)
    block = sat.prose_beat_block(OUTLINE_BEAT)
    assert block, "带节拍章必须注入兑现指令"
    assert "细纲节拍：" in block and "压抑" in block and "结算" in block
    assert "改日再算" in block, "兑现指令点名推迟语式（与 L0 金标同源）"
    on = base + block
    assert on != base and on.startswith(base)


def test_prose_prompt_no_beat_chapter_is_byte_identical():
    """「本章无节拍」显式空档与旧格式细纲 → 不注入（空档章不每章强塞，字节与 off 一致）"""
    base = PROSE_WRITING_PROMPT.format(**PROSE_KW)
    assert sat.prose_beat_block(OUTLINE_NO_BEAT) == ""
    assert sat.prose_beat_block(OUTLINE_NO_LINE) == ""
    assert base + sat.prose_beat_block(OUTLINE_NO_BEAT) == base


def test_beat_line_parse_single_source():
    """解析单一事实源：三处消费（细纲指令/正文块/L0）共用 beat_of_outline"""
    assert sat.beat_of_outline(OUTLINE_BEAT).startswith("压抑（")
    assert sat.beat_of_outline(OUTLINE_NO_LINE) == ""
    assert sat.beat_declared(sat.beat_of_outline(OUTLINE_BEAT)) is True
    assert sat.beat_declared(sat.beat_of_outline(OUTLINE_NO_BEAT)) is False
    assert sat.beat_declared("") is False


# ---------------- L0 节拍检查：召回 / 放行 / 结构核对 ----------------

def test_l0_beat_recall_defer_phrase():
    """召回：承诺节拍 + 正文推迟语式 → fail候选（复用 B01 金标形态）"""
    fs = beat_findings(OUTLINE_BEAT, PROSE_DEFER)
    assert fs and fs[0]["level"] == "fail候选"
    assert fs[0]["check"] == "爽点节拍"
    assert "改日再算" in fs[0]["quote"] or "算了吧" in fs[0]["quote"]


def test_l0_beat_pass_clean_prose():
    """放行：节拍兑现、无推迟语式 → 零 finding"""
    assert beat_findings(OUTLINE_BEAT, PROSE_CLEAN) == []


def test_l0_beat_no_beat_no_check():
    """放行：显式空档/无节拍行（含引擎关闭的旧细纲）→ 不评不判"""
    assert beat_findings(OUTLINE_NO_BEAT, PROSE_DEFER) == []
    assert beat_findings(OUTLINE_NO_LINE, PROSE_DEFER) == []


def test_l0_beat_missing_settlement_segment():
    """结构核对：节拍行缺「结算」段 → 核对级证据（不判 fail，审校裁决）"""
    fs = beat_findings(OUTLINE_MALFORMED, PROSE_CLEAN)
    assert fs and fs[0]["level"] == "核对" and "结算" in fs[0]["text"]


def test_l0_beat_fail_open():
    """fail-open：解析异常返回空，绝不阻断流水线"""
    assert beat_findings(None, None) == []


def test_v5_block_without_beat_line_byte_identical():
    """引擎关闭（细纲无节拍行）：节拍机制在账本对照块里完全惰性——
    不出现任何节拍承诺行/节拍 finding（off 路径 V5 字节不变的根；
    与 HEAD 旧实现的逐字节一致性另由 bin 对比取证，见实施报告）"""
    for outline in (OUTLINE_NO_LINE, OUTLINE_NO_BEAT):
        block = build_v5_block("p", 6, PROSE_DEFER,
                               read_outline=lambda o=outline: o, read_states=lambda: "")
        assert "节拍" not in block, "无节拍行的细纲不该触发任何节拍输出"
        assert "[细纲爽点节拍]" not in block


def test_v5_block_with_beat_carries_promise_and_findings():
    """引擎开启（细纲带节拍行）：V5 块新增节拍承诺行与推迟 finding"""
    block = build_v5_block("p", 6, PROSE_DEFER,
                           read_outline=lambda: OUTLINE_BEAT, read_states=lambda: "")
    assert "[细纲爽点节拍]" in block
    assert "爽点节拍" in block and "fail候选" in block


# ---------------- 装配接线护栏（防未来改码悄悄解线） ----------------

def test_wiring_guards_in_stages_source():
    """三个正文分支与两个细纲装配点必须仍挂着 B1 注入——解线即红"""
    import re
    src = open(os.path.join(os.path.dirname(stages.__file__), "stages.py"),
               encoding="utf-8").read()
    assert len(re.findall(r"\+ _beat_block \+", src)) == 3, \
        "正文轮 _beat_block 注入点应为 3 处（S4 分支/会话分支/单轮分支）"
    assert len(re.findall(r"_satisfaction_outline_directive\(ctx\.cfg\)", src)) == 2, \
        "细纲装配 _satisfaction_outline_directive 注入点应为 2 处（批生成/会话内）"
