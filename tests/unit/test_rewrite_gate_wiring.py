# -*- coding: utf-8 -*-
"""0.20.4 Q2-b 净增益闸必须管到两条默认开启的新写路径（2026-10-09 深审 V8）。

缺陷：`_rewrite_adopt`（真闸）只接在 `_rewrite_phase` 的三个返回点上，而缺省开启的
①卡片制去味 `_deslop_pinned_rewrite`（writing.deslop_cards=True）与 ②段落级增厚
`_enrich_para_rewrite`（writing.enrich_para=True）都是算完 merged 直接 return——
「改好才收」在最需要它的两个相位上是死代码。

同时定死一条口径：增厚是**增造型**改写（天然加字），不能用「缩减型」的尺寸预算去
判它；它照旧受「阻断不增 / 复现不劣化 / 角色在场」三条质量判据的约束。
"""
import json
import os
import re

import pytest

from app.core import gates, rewrite_gate, stages


class _Ctx:
    def __init__(self, proj):
        self.proj = str(proj)
        self.cfg = {"writing": {}}
        self.logs = []
        self.last_prompt = ""

    def log(self, level, msg):
        self.logs.append((level, msg))


class _Session:
    def __init__(self):
        self.enabled = True
        self.turns = 0

    def turn_count(self):
        return self.turns

    def rollback_to(self, n):
        self.turns = n

    def commit_turn(self, req, out):
        self.turns += 1


def _events(proj):
    p = os.path.join(str(proj), "追踪", "session_events.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


# ================= 纯函数：增造型判据集 =================

CLEAN = "陈默推开门，屋里没有人。桌上放着半杯凉透的茶。"
# 四处引号强调（deslop 里是 advisory 级）：不新增阻断，只把规则总量抬上去
GROWTH = ("他听见走廊尽头有水滴声，一下，又一下。"
          "墙上的“值班表”缺了一角，“零三号”那栏被人用指甲抠过。"
          "窗台压着半张“出入单”，落款是“织命司”。"
          "他把茶端起来倒了，水顺着指缝滴回桌面。")


def test_growth_mode_skips_size_budget_but_keeps_quality():
    """增造型改写：尺寸预算（总量容差）不适用，质量判据一条都不能松。"""
    ok_red, reasons_red = rewrite_gate.gate_rewrite(CLEAN, CLEAN + GROWTH)
    assert not ok_red and any("总量" in r for r in reasons_red), reasons_red

    ok_grow, reasons_grow = rewrite_gate.gate_rewrite(
        CLEAN, CLEAN + GROWTH, allow_growth=True)
    assert ok_grow, "干净增厚被尺寸预算误杀：%s" % reasons_grow

    # 新增阻断词：增造型也照样拒
    ok2, reasons2 = rewrite_gate.gate_rewrite(
        CLEAN, CLEAN + "他心中涌起一丝不安，又有一丝迟疑，眼底闪过一抹复杂。",
        allow_growth=True)
    assert not ok2 and any("阻断" in r for r in reasons2), reasons2

    # 复读堆料：增造型也照样拒
    pile = ("他把手账往肩上提了提，决定先离开这一层。") * 6
    ok3, reasons3 = rewrite_gate.gate_rewrite(CLEAN, CLEAN + pile, allow_growth=True)
    assert not ok3 and any("复现" in r for r in reasons3), reasons3


# ================= 卡片去味：merged 必须过闸 =================

# 原段含一个 blocking 词（「不是…而是」），定点卡要把它换掉。
# 篇幅刻意写到千字级以下但几百字：fourgram 复现率在过短文本上是噪声（本底不稳）。
CARD_PROSE = "\n\n".join([
    "# 第 1 章 织命司",
    "他不是恐惧，而是兴奋。陈默把手账按在胸口，指节发白，数到第三遍才松开手。",
    "楼下铁门被风吹得响了三回，他没有回头，走廊尽头的灯管还在闪。",
    "窗台的薄水泛起涟漪，映出半张陌生的脸，很快又被水纹揉散。",
    "他记得三年前那台手术也是这样的灯光，器械碰撞声从很远的地方传过来。",
])


def _card_inputs():
    blocking, advisory = gates.scan_deslop(CARD_PROSE)
    return blocking, advisory


def test_card_deslop_rejects_merged_that_adds_blocking(monkeypatch, tmp_path):
    """坏卡：替换段虽然消掉了原阻断，却塞进更多阻断 → 净增益闸拒收，返回空串。"""
    blocking, advisory = _card_inputs()
    assert blocking, "夹具没造出阻断项，测试失去意义"

    def _ask(ctx, session, slot, req, label="", phase="", stream=True, **kw):
        nums = re.findall(r"⟦P(\d{1,4})⟧", req)
        p = nums[0]
        return ("⟦P%s⟧ 陈默心中涌起一丝不安，又有一丝迟疑，"
                "还有一丝说不清的期待，眼底闪过一抹复杂。" % p)

    monkeypatch.setattr(stages, "_session_ask", _ask)
    ctx, sess = _Ctx(tmp_path), _Session()

    out = stages._deslop_pinned_rewrite(ctx, sess, CARD_PROSE, list(blocking),
                                        list(advisory), num=1)

    assert out == "", "多阻断的卡片稿被直接采纳了（净增益闸没管这条路径）"
    assert any(l == "rewrite_rejected" for l in _events(tmp_path) or []) or \
        any("净增益闸拒收" in m for _, m in ctx.logs), ctx.logs


def test_card_deslop_still_accepts_clean_fix(monkeypatch, tmp_path):
    """对照：真正消掉阻断且不加新问题的卡片稿照常采纳（闸不能把好卡也堵死）。"""
    blocking, advisory = _card_inputs()

    def _ask(ctx, session, slot, req, label="", phase="", stream=True, **kw):
        nums = re.findall(r"⟦P(\d{1,4})⟧", req)
        return "⟦P%s⟧ 陈默的指尖一点点收紧，手账边角硌进掌心。他没有回头。" % nums[0]

    monkeypatch.setattr(stages, "_session_ask", _ask)
    ctx, sess = _Ctx(tmp_path), _Session()

    out = stages._deslop_pinned_rewrite(ctx, sess, CARD_PROSE, list(blocking),
                                        list(advisory), num=1)

    assert out and "一丝" not in out and "不是恐惧" not in out, (out, ctx.logs)
    for keep in ("楼下铁门", "窗台的薄水", "# 第 1 章 织命司"):
        assert keep in out


# ================= 段落级增厚：merged 必须过闸 =================

ENRICH_PROSE = "\n\n".join([
    "# 第 1 章 织命司",
    "甲段：陈默把湿透的手账塞进怀里，转身往二楼走，楼梯口的灯忽明忽暗。",
    "乙段：灯管闪了一下。",
    "丙段：楼下铁门被风吹得响了三回，他没有回头，风把雨丝斜着推进走廊。",
    "丁段：窗台的薄水泛起涟漪，映出半张陌生的脸，很快又被水纹揉散。",
])
_THIN = "乙段：灯管闪了一下。"
# 12 遍同一句短句：不与本章其他段重合（卡级防搬运放行），但整段复读把
# fourgram 复现率抬起来（净增益闸必须拦住）
_PILEUP = "乙段：灯管闪了一下，陈默抬头看了一眼天花板。" * 10


def test_enrich_para_rejects_pileup_merged(monkeypatch, tmp_path):
    """复读式增厚：卡级三查放行（不与别段重合），但整段复读抬高复现率 → 必须拒。"""
    def _ask(ctx, session, slot, req, label="", phase="", stream=True, **kw):
        m = re.search(r"⟦P(\d{1,4})⟧\s*" + re.escape(_THIN), req)
        assert m, "para_block 里没找到待增厚段落"
        return "⟦P%s⟧ %s" % (m.group(1), _PILEUP)

    monkeypatch.setattr(stages, "_session_ask", _ask)
    ctx, sess = _Ctx(tmp_path), _Session()

    out = stages._enrich_para_rewrite(ctx, sess, ENRICH_PROSE, gap=400, num=1,
                                      chapter_words=2000)

    assert out == "", "复读堆料的增厚稿被采纳了"
    assert any("净增益闸拒收" in m for _, m in ctx.logs), ctx.logs


def test_enrich_para_accepts_clean_thickening(monkeypatch, tmp_path):
    """对照：不复读、不加阻断词的增厚照常生效。"""
    thick = ("乙段：灯管闪了一下，又暗下去半秒，惨白的光在潮气里留下断续的影子。"
             "陈默抬头盯着那截忽明忽暗的灯管，听见镇流器发出细碎的嗡鸣，"
             "像有什么东西在天花板夹层里慢慢挪动。他把手账往肩上提了提，"
             "decided 只站三秒就走，可那声音又把他钉在原地半步都挪不开。")

    def _ask(ctx, session, slot, req, label="", phase="", stream=True, **kw):
        m = re.search(r"⟦P(\d{1,4})⟧\s*" + re.escape(_THIN), req)
        return "⟦P%s⟧ %s" % (m.group(1), thick)

    monkeypatch.setattr(stages, "_session_ask", _ask)
    ctx, sess = _Ctx(tmp_path), _Session()

    out = stages._enrich_para_rewrite(ctx, sess, ENRICH_PROSE, gap=200, num=1,
                                      chapter_words=2000)

    assert out and thick in out, (out, ctx.logs)
    for keep in ("甲段：", "丙段：", "丁段："):
        assert keep in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
