# -*- coding: utf-8 -*-
"""C43 桥段码账本（卡5 prompts 侧）单测

覆盖：
- 码表完整性：36 码无重复、7 组配额、字段齐备、SJ/SJ2 前缀撞车显式区分、
  反例 5 码 advisory_only 不进路由
- 打法卡→码路由一致：打法卡键 ⊆ 码表非反例码、一码一卡、渲染块字段齐
- 关态逐字不变：bridge_codes_enabled=False 时 chapter_to_cards / craft_block
  输出与改造前逐字节一致（golden 硬编码，含带「- 桥段：」码行的细纲）
- 开关注入：开态码行直路由绕过关键词、craft_block 含打法卡块、无码行回退
  关键词路由；enabled_from_cfg 与 config 出厂键默认 off
- stages 接线钉：_mc_draft 的 craft_block 调用前必须置位开关
"""
import os

import pytest

from app.prompts import bridge_cards as bcd
from app.prompts import bridge_codes as bc
from app.prompts import scene_cards as sc


@pytest.fixture(autouse=True)
def _switch_off():
    """桥段码开关全局复位：本模块每个用例前后都强制回关态，防跨模块污染。"""
    sc.set_bridge_codes_enabled(False)
    yield
    sc.set_bridge_codes_enabled(False)


# ---- 1. 码表完整性 ----

def test_code_table_complete_and_disjoint():
    codes = bc.BRIDGE_CODES
    assert len(codes) == 36
    assert len(set(codes)) == 36                       # 无重复码
    from collections import Counter
    counts = Counter(meta["group"] for meta in codes.values())
    assert dict(counts) == dict(bc.GROUP_EXPECTED)     # 8+5+6+6+4+2+5
    assert sum(bc.GROUP_EXPECTED.values()) == 36
    assert set(bc.GROUP_EXPECTED) == set(bc.GROUP_ORDER)
    for code, meta in codes.items():
        for field in ("name", "group", "rule", "position",
                      "spans", "route_kw", "card", "advisory_only"):
            assert field in meta, (code, field)
        lo, hi = meta["spans"]
        assert 1 <= lo <= hi, (code, meta["spans"])
        assert meta["card"] in sc.SCENE_CARDS or meta["card"] == ""


def test_sj_sj2_prefix_collision_explicit():
    """SJ（收获兑现·爽点）与 SJ2（闭关跳时·过渡）前缀撞车必须显式共存。"""
    assert "SJ" in bc.BRIDGE_CODES and "SJ2" in bc.BRIDGE_CODES
    assert bc.BRIDGE_CODES["SJ"]["name"] != bc.BRIDGE_CODES["SJ2"]["name"]
    assert bc.BRIDGE_CODES["SJ"]["group"] != bc.BRIDGE_CODES["SJ2"]["group"]
    # 整码 token 匹配：SJ2 不许被前缀截断成 SJ
    assert bc.parse_bridge_codes("- 桥段：SJ2(主)+SJ(次)") == ("SJ2", "SJ")
    assert bc.route_to_cards("- 桥段：SJ2(主)") == ("lowkey", [])
    assert bc.route_to_cards("- 桥段：SJ(主)") == ("payoff", ["lowkey"])


def test_counterexample_codes_advisory_only():
    adv = sorted(k for k, meta in bc.BRIDGE_CODES.items() if meta["advisory_only"])
    assert adv == ["BAL", "LOGIC", "OOC", "REP", "WATER"]
    assert all(bc.BRIDGE_CODES[k]["card"] == "" for k in adv)   # 反例码不进路由
    # 位置码（钩子 2 码）同样不路由场景卡
    assert bc.BRIDGE_CODES["YQ"]["card"] == ""
    assert bc.BRIDGE_CODES["KT"]["card"] == ""


# ---- 2. 解析与路由 ----

def test_parse_bridge_codes():
    assert bc.parse_bridge_codes("- 桥段：DL(主)+MX(次)") == ("DL", "MX")
    assert bc.parse_bridge_codes("- 桥段：dl(主)") == ("DL", "")       # 大小写不敏感
    assert bc.parse_bridge_codes("- 桥段：ZZ(主)+DL(次)") == ("DL", "")  # 码表外忽略
    assert bc.parse_bridge_codes("没有码行的细纲") == ("", "")
    assert bc.parse_bridge_codes("") == ("", "")


def test_route_to_cards():
    assert bc.route_to_cards("- 桥段：DL(主)+MX(次)") == ("payoff", ["lowkey", "mystery"])
    assert bc.route_to_cards("- 桥段：DB(主)") == ("battle", ["lowkey"])
    assert bc.route_to_cards("- 桥段：YQ(主)") is None       # 位置码回退关键词路由
    assert bc.route_to_cards("- 桥段：WATER(主)") is None    # 反例码不路由
    assert bc.route_to_cards("没有码行") is None


# ---- 3. 打法卡→码路由一致 ----

def test_play_cards_shape_and_routing_consistency():
    cards = bcd.BRIDGE_PLAY_CARDS
    assert 4 <= len(cards) <= 6
    seen = []
    for key, card in cards.items():
        meta = bc.BRIDGE_CODES.get(key)
        assert meta is not None, key                       # 键必须是合法桥段码
        assert meta["advisory_only"] is False              # 不收反例码
        assert meta["card"] in sc.SCENE_CARDS              # 码表侧路由目标合法
        for field in ("name", "trigger", "beats", "joint", "failure"):
            assert card.get(field), (key, field)
        assert len(card["beats"]) >= 3 and len(card["failure"]) >= 1
        seen.append(key)
    assert len(set(seen)) == len(seen)                     # 一码一卡，路由无歧义
    assert bcd.play_codes_ok()
    # 渲染块：字段齐备；无打法卡的码零追加
    blk = bcd.play_block("DB")
    assert blk.startswith("桥段打法·大比（DB）")
    assert "触发：" in blk and "步骤：" in blk and "失败态：" in blk and "章钩衔接：" in blk
    assert bcd.play_block("YQ") == ""                      # 位置码
    assert bcd.play_block("WATER") == ""                   # 反例码
    assert bcd.play_block("") == ""
    assert bcd.play_block("db") == bcd.play_block("DB")    # 大小写归一


# ---- 4. 关态逐字不变（golden 为改造前实现的真实输出，硬编码防回归）----

_GOLDEN = {
    "battle_no_code": (
        (3, 100, "主角与王麻子在比武场三招切磋", ""),
        ("battle", ["lowkey"]),
        "主卡·战斗（本章演法：消耗：6 回合以上，损耗层层加码）\n"
        "- 回合制：目标→试探→交锋→代价→收束\n"
        "- 空间锚点：每回合的地形/光线/距离都不同\n"
        "- 伤害=身体部位+功能丧失，禁止抽象 HP 数字\n"
        "- 可观察代价：体力/位置/掩体/心理，而非单纯扣血\n"
        "叠加·日常\n"
        "- 关系存钱罐：具体物件/承诺，留待后文兑现\n"
        "- 日常细节温度：一餐/一走/一景带 1 个具体小动作"),
    "code_line_payoff": (
        (7, 100, "- 桥段：DL(主)+MX(次)\n本章主角当众揭穿反派谎言", ""),
        ("payoff", ["lowkey"]),
        "主卡·爽点（本章演法：连环：两个爽点前后相接，前一个引出后一个）\n"
        "- 铺垫压力≤爽点长度：可指认的不公/嘲讽/沉默\n"
        "- 反转动作：决定→出手→命中，禁止'他恍然大悟'式宣告\n"
        "- 围观反应≥1/4 长度：盟友/对手/旁观者差异化\n"
        "- 结算镜头：数字/地位符号/旁观者态度，三选一\n"
        "叠加·日常\n"
        "- 关系存钱罐：具体物件/承诺，留待后文兑现\n"
        "- 日常细节温度：一餐/一走/一景带 1 个具体小动作"),
    "code_line_db_falls_lowkey": (
        (5, 100, "- 桥段：DB(主)\n本章按码执行", ""),
        ("lowkey", []),
        "主卡·日常（本章演法：修复：把上一场留下的一道小裂缝补上）\n"
        "- 关系存钱罐：具体物件/承诺，留待后文兑现\n"
        "- 日常细节温度：一餐/一走/一景带 1 个具体小动作\n"
        "- 关系推进：-1 到 +1 的微调，禁止跳表\n"
        "- 留白收尾：氛围/位置/动作定格，不强求钩子"),
    "code_line_sj2": (
        (9, 100, "- 桥段：SJ2(主)\n主角闭关", ""),
        ("lowkey", []),
        "主卡·日常（本章演法：积累：攒下筹码、默契与信息）\n"
        "- 关系存钱罐：具体物件/承诺，留待后文兑现\n"
        "- 日常细节温度：一餐/一走/一景带 1 个具体小动作\n"
        "- 关系推进：-1 到 +1 的微调，禁止跳表\n"
        "- 留白收尾：氛围/位置/动作定格，不强求钩子"),
}


@pytest.mark.parametrize("tag", sorted(_GOLDEN))
def test_off_state_byte_identical(tag):
    (num, total, outline, extra), want_cards, want_block = _GOLDEN[tag]
    assert sc.chapter_to_cards(outline, extra) == want_cards
    assert sc.craft_block(num, total, outline, extra) == want_block


def test_off_state_hint_for_chapter_unchanged():
    assert sc.hint_for_chapter(1, 100, "主角与王麻子比武") == "## 本章主卡：战斗｜子卡：日常"
    assert sc.hint_for_chapter(2, 100, "- 桥段：DB(主)\n本章按码执行") == "## 本章主卡：日常"


# ---- 5. 开关注入 ----

def test_on_state_code_routing_bypasses_keywords():
    sc.set_bridge_codes_enabled(True)
    # 无关键词命中的细纲：码行直路由 DB→battle（关态落 lowkey）
    assert sc.chapter_to_cards("- 桥段：DB(主)\n本章按码执行") == ("battle", ["lowkey"])
    # craft_block 含打法卡块
    blk = sc.craft_block(5, 100, "- 桥段：DB(主)\n本章按码执行", "")
    assert blk.startswith("主卡·战斗")
    assert "桥段打法·大比（DB）" in blk
    assert "触发：" in blk and "失败态：" in blk
    # 码路由叠加次码子卡（关态 golden 只有 lowkey，开态多 mystery）
    assert sc.chapter_to_cards(
        "- 桥段：DL(主)+MX(次)\n本章主角当众揭穿反派谎言") == ("payoff", ["lowkey", "mystery"])
    # 无码行回退关键词路由（与关态一致）
    assert sc.chapter_to_cards("主角与王麻子在比武场三招切磋") == ("battle", ["lowkey"])
    # 位置码/反例码不路由 → 回退关键词（"危机开局"无关键词命中 → lowkey）
    assert sc.chapter_to_cards("- 桥段：YQ(主)\n本章危机开局")[0] == "lowkey"
    # 无打法卡的码：craft_block 与关态逐字一致（零追加）
    assert sc.craft_block(9, 100, "- 桥段：SJ2(主)\n主角闭关", "") == _GOLDEN["code_line_sj2"][2]


def test_switch_restores_off_state():
    sc.set_bridge_codes_enabled(True)
    sc.set_bridge_codes_enabled(False)
    assert sc.chapter_to_cards("- 桥段：DB(主)\n本章按码执行") == ("lowkey", [])


# ---- 6. 开关键位 ----

def test_enabled_from_cfg_and_default_off():
    assert bc.enabled_from_cfg(None) is False
    assert bc.enabled_from_cfg({}) is False
    assert bc.enabled_from_cfg({"writing": {}}) is False
    assert bc.enabled_from_cfg({"writing": {"bridge_codes_enabled": True}}) is True
    assert bc.enabled_from_cfg({"writing": {"bridge_codes_enabled": 1}}) is True
    from app.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["writing"]["bridge_codes_enabled"] is False   # 出厂键默认 off


def test_stages_wiring_pinned():
    """stages._mc_draft 的 craft_block 调用前必须按配置置位开关（接线防拆钉）。"""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "app", "core", "stages.py")
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "set_bridge_codes_enabled" in text
    assert "bridge_codes.enabled_from_cfg" in text
    # 置位行必须出现在 craft_block 调用之前
    assert text.index("set_bridge_codes_enabled") < text.index("scene_cards.craft_block")
