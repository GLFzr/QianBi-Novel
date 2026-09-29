# -*- coding: utf-8 -*-
"""B10 盲评防偏差三件套 + 审校「先叙情节后判决」——prompt 侧钉测

覆盖：
1. 位置置换确定性：同种子同序；种子扫描两序都出现（真随机而非恒等）。
2. 长度配平：25% 阈值边界（24% 平衡 / 30% 失衡）、缺长度按未配平、提示行文本。
3. 构造器字段：三件套纪律齐备、两稿正文按 order 摆位、变体身份不泄露、
   order 与正文摆位一致、dim_block/extra_rules 注入、输出协议含先叙后判。
4. 审校主审校升级钉测：FINAL_REVIEW_PROMPT/COMPACT 的 ===情节重述=== 段在
   六维之前、硬纪律第 8 条在 system 尾段、紧凑票 plot_restatement 字段；
   stages 解析端不受新增段影响（长文解析忽略前置段、紧凑票容忍新键）。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.prompts import review as rv  # noqa: E402
from app.prompts.blind_eval import (  # noqa: E402
    LENGTH_IMBALANCE_RATIO, build_blind_eval_prompt, length_balance_hint,
    length_imbalance, narrative_first_block, permute_positions,
)

PROSE_A = "陈更推开当铺的门，柜上第三枚指印在灯下发亮。"
PROSE_B = "当铺子时清账。陈更把账本摊开，指尖停在没人认领的那一页。"


# ---------------- 1. 位置置换确定性 ----------------

def test_permute_deterministic_same_seed_same_order():
    assert permute_positions(42) == permute_positions(42)
    assert permute_positions(42, 3) == permute_positions(42, 3)
    assert sorted(permute_positions(7, 3)) == [0, 1, 2]      # 是排列
    assert permute_positions(0, 1) == [0] and permute_positions(0, 0) == []


def test_permute_both_orders_occur_across_seeds():
    """种子扫描 [0,64)：[0,1] 与 [1,0] 都出现——是真置换而非恒等/恒反"""
    orders = {tuple(permute_positions(s)) for s in range(64)}
    assert (0, 1) in orders and (1, 0) in orders


# ---------------- 2. 长度配平 ----------------

def test_length_imbalance_threshold():
    assert LENGTH_IMBALANCE_RATIO == 0.25
    assert not length_imbalance(1000, 1249)     # 差 24.9% → 配平
    assert length_imbalance(1000, 1251)         # 差 25.1% → 失衡
    assert length_imbalance(1000, 1000) is False
    assert length_imbalance(0, 500) is True     # 缺长度信息按未配平
    assert length_imbalance(None, 500) is True


def test_length_balance_hint_text():
    hint = length_balance_hint(1000, 1100)
    assert "不得以长度为据" in hint and "已配平" in hint and "1000/1100" in hint
    bad = length_balance_hint(1000, 2000)
    assert "未配平" in bad and "长度差≥25%" in bad
    assert "格外警惕" in length_balance_hint()          # 无字数也有纪律行


# ---------------- 3. 构造器 ----------------

def test_builder_contains_three_disciplines_and_output_contract():
    prompt, order = build_blind_eval_prompt(PROSE_A, PROSE_B, seed=1)
    assert narrative_first_block() in prompt               # 件套3：先叙情节
    assert length_balance_hint() in prompt                 # 件套2：长度配平（无字数版）
    assert "位置盲评" in prompt and "呈现顺序与质量无关" in prompt   # 件套1：位置置换
    assert "===情节重述===" in prompt and "===判定===" in prompt
    assert "稿一胜|稿二胜|平局" in prompt
    assert "禁止猜测或提及稿件来源" in prompt              # 盲评匿名性


def test_builder_places_proses_by_order():
    seen = set()
    for seed in range(32):
        prompt, order = build_blind_eval_prompt(PROSE_A, PROSE_B, seed=seed)
        first_prose = PROSE_A if order[0] == 0 else PROSE_B
        second_prose = PROSE_B if order[0] == 0 else PROSE_A
        assert prompt.index(first_prose) < prompt.index(second_prose)
        assert prompt.index("## 稿一") < prompt.index("## 稿二")
        seen.add(tuple(order))
    assert seen == {(0, 1), (1, 0)}                        # 两序都被构造过


def test_builder_hides_variant_identity():
    """变体身份不进 prompt：prose 本体之外不得出现 A/B 变体标记词"""
    prompt, _o = build_blind_eval_prompt(PROSE_A, PROSE_B, seed=3)
    body = prompt.replace(PROSE_A, "").replace(PROSE_B, "")
    assert "稿A" not in body and "稿B" not in body
    assert "variant" not in body.lower()


def test_builder_dim_block_and_extra_rules_and_lengths():
    dims = "- D1 开章钩（权重12）\n- D2 爽点闭环（权重12）"
    prompt, _o = build_blind_eval_prompt(PROSE_A, PROSE_B, seed=5,
                                         dim_block=dims,
                                         extra_rules="题材：都市悬疑。",
                                         len_a=2400, len_b=2600)
    assert "===评分===" in prompt and dims in prompt
    assert "题材：都市悬疑。" in prompt
    assert "2400/2600" in prompt and "已配平" in prompt


# ---------------- 4. 审校主审校升级钉测（先叙情节后判决） ----------------

def test_final_review_restatemest_before_verdict_dims():
    """===情节重述=== 在输出协议内、位于六维之前；硬纪律第 8 条在场"""
    assert "===情节重述===" in rv.FINAL_REVIEW_PROMPT
    assert "先叙情节后判决" in rv.FINAL_REVIEW_PROMPT
    assert rv.FINAL_REVIEW_PROMPT.index("===情节重述===") < \
        rv.FINAL_REVIEW_PROMPT.index("===A_GOLDEN_OPEN===")
    # 协议段必须近场（重述小节行不能被切进 system 尾段；纪律条目提及标记词无妨）
    assert "===情节重述===（≤120 字" in rv.review_output_protocol()
    assert "===情节重述===（≤120 字" not in rv.review_static_tail()
    # 纪律条目进 system 尾段（rubric 前缀）
    assert "先叙情节后判决" in rv.review_static_tail()
    # +14.8% 判准出处标注
    assert "+14.8%" in rv.FINAL_REVIEW_PROMPT


def test_compact_protocol_has_plot_restatement_field():
    """紧凑票 JSON 协议带 plot_restatement 字段且在 dimensions 之前"""
    proto = rv.REVIEW_COMPACT_PROTOCOL
    assert '"plot_restatement"' in proto
    assert proto.index('"plot_restatement"') < proto.index('"dimensions"')
    assert "plot_restatement 必填" in proto
    # 紧凑票由前缀派生：纪律第 8 条与 plot_restatement 同票在场
    assert "先叙情节后判决" in rv.FINAL_REVIEW_COMPACT
    assert '"plot_restatement"' in rv.FINAL_REVIEW_COMPACT


def test_stages_parsers_immune_to_restatement_section():
    """stages 解析端零改动仍然工作：长文解析忽略前置重述段；紧凑票容忍新键"""
    from app.core.stages import parse_compact_review_json, parse_final_review_v2
    prose = "第一段。第二段。第三段。"

    long_vote = ("===情节重述===\n陈更发现指印，起疑，查账。\n"
                 "===A_GOLDEN_OPEN=== pass 开章有钩\n"
                 "===B_PAYOFF=== fail 无爽点【原文引证：" + prose[:6] + "】\n"
                 "===VERDICT===\nREJECT\n===END===\n")
    parsed = parse_final_review_v2(long_vote)
    assert parsed["verdict"] in ("REJECT", "REJECT-HARD")
    assert [i["dim"] for i in parsed["items"]] == ["A_GOLDEN_OPEN", "B_PAYOFF"]
    assert not any("情节重述" in (i.get("text") or "") for i in parsed["items"])

    import json as _json
    compact = {"plot_restatement": "他查账，发现指印。", "confidence": "high",
               "dimensions": [{"dim": d, "score": "pass", "quote_ref": "段1句1",
                               "one_line": "无问题"} for d in
                              ("A_GOLDEN_OPEN", "B_PAYOFF", "C_FINGER",
                               "D_PLOT", "E_CHARACTER", "F_HOOK")],
               "verdict": "PASS"}
    got = parse_compact_review_json("```json\n" + _json.dumps(compact, ensure_ascii=False) + "\n```", prose)
    assert got is not None and got["verdict"] == "PASS" and got.get("compact") is True
