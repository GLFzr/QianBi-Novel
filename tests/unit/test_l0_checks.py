# -*- coding: utf-8 -*-
"""V5 · L0 账本对照（app/core/l0_checks.py）回归

T4a 召回 0/2 的直接补位：爽点推迟 / 禁止释放 / 钟点复现 / 状态在场清单。
纯正则零 API；全部 fail-open。用 T4a 真实注入语式（B01）做金标。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.l0_checks import (build_v5_block, clock_findings, payoff_findings,
                                state_checklist, taboo_findings)

OUTLINE_PROMISE = """### 第 2 章：单号
- 爽点：陈默当众揭穿中介压价套路，押金全额到账，围观房客态度反转。
- 本章禁止提前释放：禁止出现「收账人」「案卷编号累加」等未来关键词。
- 结尾：夜里2点17分，陈默拨出电话。
"""

OUTLINE_NO_PROMISE = """### 第 3 章：过场
- 爽点：无显性爽点。本章功能是铺垫。
"""

PROSE_DEFER = ("陈默盯着中介的账单，心里憋着火。他捏紧了拳头，最终却松开了。"
               "「算了吧，」他对自己说，「这笔账改日再算也不迟。」他转身回了屋。")
PROSE_CLEAN = "陈默把押金单拍在桌上，中介的脸色变了，围观房客窃窃私语，态度明显反转。"


def test_deferred_payoff_is_flagged_b01_style():
    """B01 金标：承诺爽点 + 推迟语式 → fail候选（T4a 召回 0/2 的补位）"""
    fs = payoff_findings(OUTLINE_PROMISE, PROSE_DEFER)
    assert fs and fs[0]["level"] == "fail候选"
    assert "改日再算" in fs[0]["text"] or "算了吧" in fs[0]["text"]
    assert "改日再算" in fs[0]["quote"]


def test_fulfilled_payoff_not_flagged():
    assert payoff_findings(OUTLINE_PROMISE, PROSE_CLEAN) == []


def test_no_promise_means_no_check():
    """细纲写明无显性爽点 → 不评不判（与审校维 B 的纪律一致）"""
    assert payoff_findings(OUTLINE_NO_PROMISE, PROSE_DEFER) == []


def test_taboo_keyword_deterministic_hit():
    prose = "他想起江湖传闻里的收账人，背脊一凉。"
    fs = taboo_findings(OUTLINE_PROMISE, prose)
    assert fs and fs[0]["level"] == "fail候选" and "收账人" in fs[0]["quote"]


def test_taboo_clean_passes():
    assert taboo_findings(OUTLINE_PROMISE, PROSE_CLEAN) == []


def test_clock_cn_numeral_normalized():
    """中文钟点归一：细纲「夜里2点17分」vs 正文「夜里两点十七分」必须对上（不误报）"""
    prose = "夜里两点十七分，他拨出了那个号码。"
    assert clock_findings(OUTLINE_PROMISE, prose) == []
    # 正文换成别的钟点 → 核对项触发
    fs = clock_findings(OUTLINE_PROMISE, "凌晨四点整，他拨出了那个号码。")
    assert fs and "2点17分" in fs[0]["text"]


def test_state_checklist_extracts_open_injury():
    states = """## 阿蓟
- **当前身份**：拾骨人
- **状态变更记录**：（第4章：左踝扭伤未愈）（第5章：白翳又添一道）
"""
    items = state_checklist(states)
    assert items and any("阿蓟" in c for c in items)


def test_build_v5_block_fail_open_on_garbage():
    """细纲/状态全空 → 空块；解析异常不外抛（fail-open 纪律）"""
    assert build_v5_block(None, 1, "正文", read_outline=lambda: "",
                          read_states=lambda: "") == ""
    assert build_v5_block(None, 1, "正文", read_outline=lambda: None,
                          read_states=lambda: None) == ""


def test_build_v5_block_assembles_sections():
    states = "## 阿蓟\n- **状态变更记录**：（第4章：左踝扭伤未愈）\n"
    block = build_v5_block(None, 2, PROSE_DEFER,
                           read_outline=lambda: OUTLINE_PROMISE,
                           read_states=lambda: states)
    assert "V5 账本对照" in block
    assert "fail候选" in block or "核对" in block
    assert len(block) <= 1200
