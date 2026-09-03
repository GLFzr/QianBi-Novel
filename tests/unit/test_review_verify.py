# -*- coding: utf-8 -*-
"""stages：compute_verdict 判决计算 + verify_review_quotes 引证验真降级"""
from app.core import stages


def _sum(pass_=0, marginal=0, fail=0):
    return {"pass": pass_, "marginal": marginal, "fail": fail}


# ---------- compute_verdict ----------

def test_verdict_declared_wins_when_valid():
    assert stages.compute_verdict(_sum(fail=2), [], "PASS") == "PASS"
    assert stages.compute_verdict(_sum(), [], "reject") == "REJECT"


def test_verdict_invalid_declared_falls_back_to_gates():
    assert stages.compute_verdict(_sum(), [], "胡言乱语") == "PASS"
    assert stages.compute_verdict(_sum(marginal=3), [], "") == "PASS_WITH_NOTES"


def test_verdict_count_gates():
    assert stages.compute_verdict(_sum(pass_=6, marginal=1), []) == "PASS"
    assert stages.compute_verdict(_sum(pass_=5, marginal=2), []) == "PASS_WITH_NOTES"
    assert stages.compute_verdict(_sum(pass_=5, fail=1), []) == "PASS_WITH_NOTES"
    assert stages.compute_verdict(_sum(pass_=4, fail=2), []) == "REJECT"


def test_verdict_hard_root_upgrade():
    hard_item = {"level": "fail", "root_layer": "ROOT_OUTLINE_UNIT", "text": "x"}
    prose_item = {"level": "fail", "root_layer": "ROOT_PROSE", "text": "y"}
    # 上游硬根因（大纲层）→ REJECT-HARD
    assert stages.compute_verdict(_sum(fail=2), [hard_item, prose_item], "") == "REJECT-HARD"
    # ROOT_PROSE 不升级
    assert stages.compute_verdict(_sum(fail=2), [prose_item], "") == "REJECT"
    # PASS 不做根因升级
    assert stages.compute_verdict(_sum(), [hard_item], "PASS") == "PASS"


# ---------- verify_review_quotes ----------

_PROSE = "夜色深沉，他推开门走了出去。街上没有一个人。"


def _parsed(items, verdict="REJECT"):
    fail = sum(1 for i in items if i["level"] == "fail")
    marg = sum(1 for i in items if i["level"] == "marginal")
    return {"verdict": verdict, "items": items,
            "summary": {"pass": 6 - fail - marg, "marginal": marg, "fail": fail},
            "blocking": [i["text"] for i in items if i["level"] == "fail"],
            "advisory": [i["text"] for i in items if i["level"] == "marginal"]}


def test_verify_demotes_fake_quote_and_recomputes():
    items = [
        {"dim": "D_PLOT", "level": "fail", "text": "凭空情节",
         "quote": "他掏出手机看了一眼时间", "root_layer": "ROOT_PROSE"},
        {"dim": "B_PAYOFF", "level": "fail", "text": "爽点缺失",
         "quote": "他推开门走了出去", "root_layer": "ROOT_PROSE"},
    ]
    out = stages.verify_review_quotes(_PROSE, _parsed(items))
    fake, real = out["items"]
    assert fake["level"] == "marginal" and fake["quote_verified"] is False
    assert fake["text"].startswith("[引证未验真]")
    assert real["level"] == "fail" and real["quote_verified"] is True
    # 判决按降级后计数重算：2 fail → 1 fail = PASS_WITH_NOTES
    assert out["verdict"] == "PASS_WITH_NOTES"
    assert out["blocking"] == ["爽点缺失"]
    assert len(out["advisory"]) == 1


def test_verify_keeps_real_quote_reject():
    items = [
        {"dim": "D_PLOT", "level": "fail", "text": "问题一",
         "quote": "他推开门走了出去", "root_layer": "ROOT_PROSE"},
        {"dim": "E_CHARACTER", "level": "fail", "text": "问题二",
         "quote": "街上没有一个人", "root_layer": "ROOT_PROSE"},
    ]
    out = stages.verify_review_quotes(_PROSE, _parsed(items))
    assert out["verdict"] == "REJECT"          # 两条真引证保住 REJECT
    assert all(i["quote_verified"] for i in out["items"])


def test_verify_skips_empty_quote_items():
    items = [{"dim": "D_PLOT", "level": "fail", "text": "无引证项",
              "quote": "", "root_layer": "ROOT_PROSE"}]
    out = stages.verify_review_quotes(_PROSE, _parsed(items))
    # 空引证不在验真范围（修复环另有回收策略），判决保持声明值
    assert out["verdict"] == "REJECT"
    assert "quote_verified" not in out["items"][0]
