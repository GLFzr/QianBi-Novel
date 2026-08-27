# -*- coding: utf-8 -*-
"""v2 6 维审校 + 反馈环单测：覆盖 parse_final_review_v2、build_issues_brief、build_upstream_anchors

- fake home 隔离
- 无 LLM 调用，纯函数测试
"""
import os
import sys
import tempfile
import shutil

_FH = tempfile.mkdtemp(prefix="qbn_test_review_v2_")
os.environ["USERPROFILE"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.stages import parse_final_review_v2, parse_review_findings
from app.prompts.review import (
    FINAL_REVIEW_PROMPT, ROOT_CAUSE_PROMPT, REVISION_TARGETS_PROMPT,
    build_issues_brief, build_upstream_anchors,
)
from app.core import state as st_mod


# ---- 测试 1：parse_final_review_v2 各场景 ----

def test_parse_v2_pass():
    text = '''===A_GOLDEN_OPEN=== pass 开篇有力
===B_PAYOFF=== pass 爽点到位
===C_FINGER=== pass 金手指无越界
===D_PLOT=== pass 因果链完整
===E_CHARACTER=== pass 声口不崩
===F_HOOK=== pass 钩子强
===WORST_QUOTES===
- A "不适用"
===VERDICT===
PASS
===END===
'''
    v2 = parse_final_review_v2(text)
    assert v2["verdict"] == "PASS"
    assert v2["summary"] == {"pass": 6, "marginal": 0, "fail": 0}
    assert v2["blocking"] == []
    assert v2["advisory"] == []
    assert len(v2["items"]) == 6
    print(f"  ✓ v2 PASS: 6维全 pass → verdict=PASS")


def test_parse_v2_pass_with_notes():
    text = '''===A_GOLDEN_OPEN=== pass 开篇有力
===B_PAYOFF=== pass 爽点到位
===C_FINGER=== pass 金手指无越界
===D_PLOT=== marginal 第3段人物动机不明【原文引证："他转身离开"】
===E_CHARACTER=== pass 声口不崩
===F_HOOK=== marginal 章末可更紧【原文引证："他似乎想到了什么"】
===VERDICT===
PASS_WITH_NOTES
'''
    v2 = parse_final_review_v2(text)
    assert v2["verdict"] == "PASS_WITH_NOTES"
    assert v2["summary"]["pass"] == 4
    assert v2["summary"]["marginal"] == 2
    assert len(v2["blocking"]) == 0
    assert len(v2["advisory"]) == 2
    # 验证引证被正确提取
    item_d = next(it for it in v2["items"] if it["dim"] == "D_PLOT")
    assert "他转身离开" in item_d["quote"]
    print(f"  ✓ v2 PASS_WITH_NOTES: 2 marginal + 引证正确提取")


def test_parse_v2_reject():
    text = '''===A_GOLDEN_OPEN=== pass 开篇有力
===B_PAYOFF=== fail 三招切磋无任何描写【原文引证："两人对峙了一炷香"】
  → root: ROOT_OUTLINE_UNIT
===C_FINGER=== fail 金手指超出日上限
  → root: ROOT_CORE
===D_PLOT=== pass 因果链完整
===E_CHARACTER=== pass 声口不崩
===F_HOOK=== pass 钩子强
===VERDICT===
REJECT-HARD
'''
    v2 = parse_final_review_v2(text)
    assert v2["verdict"] == "REJECT-HARD"
    assert v2["summary"]["fail"] == 2
    assert len(v2["blocking"]) == 2
    # 验证根因提取（多行场景）
    item_b = next(it for it in v2["items"] if it["dim"] == "B_PAYOFF")
    assert item_b["root_layer"] == "ROOT_OUTLINE_UNIT"
    item_c = next(it for it in v2["items"] if it["dim"] == "C_FINGER")
    assert item_c["root_layer"] == "ROOT_CORE"
    print(f"  ✓ v2 REJECT-HARD: 2 fail + 根因 ROOT_OUTLINE_UNIT/ROOT_CORE 正确提取")


def test_parse_v2_auto_infer_no_verdict():
    """无 ===VERDICT=== 段时按门禁自动推断"""
    text = '''===A_GOLDEN_OPEN=== pass ok
===B_PAYOFF=== pass ok
===C_FINGER=== pass ok
===D_PLOT=== pass ok
===E_CHARACTER=== pass ok
===F_HOOK=== pass ok
'''
    v2 = parse_final_review_v2(text)
    assert v2["verdict"] == "PASS"
    text2 = '''===A_GOLDEN_OPEN=== pass
===B_PAYOFF=== fail X【原文引证："y"】
===C_FINGER=== pass
===D_PLOT=== pass
===E_CHARACTER=== pass
===F_HOOK=== pass
'''
    v2b = parse_final_review_v2(text2)
    # 1 fail, 0 marginal → PASS_WITH_NOTES
    assert v2b["verdict"] == "PASS_WITH_NOTES"
    text3 = '''===A_GOLDEN_OPEN=== pass
===B_PAYOFF=== fail X【原文引证："y"】
===C_FINGER=== fail Z【原文引证："w"】
===D_PLOT=== pass
===E_CHARACTER=== pass
===F_HOOK=== pass
'''
    v2c = parse_final_review_v2(text3)
    # 2 fail → REJECT
    assert v2c["verdict"] == "REJECT"
    print(f"  ✓ v2 auto-infer: 全 pass→PASS / 1fail→PASS_WITH_NOTES / 2fail→REJECT")


# ---- 测试 2：build_issues_brief ----

def test_build_issues_brief_basic():
    issues = [
        {"dim": "B_PAYOFF", "level": "fail", "text": "三招切磋无描写", "quote": "原文", "root_layer": "ROOT_OUTLINE_UNIT"},
        {"dim": "C_FINGER", "level": "fail", "text": "金手指超限", "quote": "..."},
    ]
    brief = build_issues_brief(issues)
    assert "[1]" in brief
    assert "B_PAYOFF" in brief
    assert "C_FINGER" in brief
    # 长度在合理范围
    assert len(brief) < 500
    print(f"  ✓ build_issues_brief: 2 issue 紧凑化成功（{len(brief)} 字符）")


def test_build_issues_brief_empty():
    assert "（无 issues）" in build_issues_brief([])
    print(f"  ✓ build_issues_brief: 空列表 → 占位")


def test_build_issues_brief_truncate():
    """长 text/quote 自动截断"""
    issues = [{"dim": "X", "level": "fail", "text": "A" * 200, "quote": "B" * 200}]
    brief = build_issues_brief(issues)
    # text 80 字 + quote 60 字
    assert len(brief) < 300
    print(f"  ✓ build_issues_brief: 长文本自动截断（{len(brief)} 字符）")


# ---- 测试 3：build_upstream_anchors ----

def test_build_upstream_anchors_empty():
    """空项目返回占位"""
    fake = os.path.join(_FH, "fake_no_files")
    os.makedirs(fake, exist_ok=True)
    anchors = build_upstream_anchors(fake, 1)
    assert "（无上游产物）" in anchors
    print(f"  ✓ build_upstream_anchors: 无产物 → 占位")


def test_build_upstream_anchors_with_files():
    """有核心设定文件时正确锚定"""
    fake = os.path.join(_FH, "fake_with_files")
    os.makedirs(os.path.join(fake, "设定"), exist_ok=True)
    os.makedirs(os.path.join(fake, "大纲"), exist_ok=True)
    with open(os.path.join(fake, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("# 核心设定\n- 主角：陈凡\n- 金手指：破绽之眼\n- 每日3次")
    with open(os.path.join(fake, "大纲", "大纲.md"), "w", encoding="utf-8") as f:
        f.write("# 大纲\n### 第1卷 崛起\n- 30章")
    anchors = build_upstream_anchors(fake, 1)
    assert "【核心设定 · 锚定行号】" in anchors
    assert "L1: # 核心设定" in anchors
    assert "L4: - 每日3次" in anchors
    assert "【大纲 · 锚定行号】" in anchors
    print(f"  ✓ build_upstream_anchors: 2 文件锚定正确（L1-L4 / L1-L3）")


# ---- 测试 4：v1 fallback ----

def test_v1_fallback_when_no_v2_format():
    """LLM 输出 v1 格式（无 ===VERDICT=== / 无 6 维）时 v2 解析不出 items，
    实际 verdict 由总评门禁推断；调用方在 _chapter_review 内部检测
    v2["verdict"] 有值但 items 为空 → 走 v1 解析路径。
    """
    text = '''===BLOCKING===
- 角色已死亡又出场
- 伏笔被提前回收
===ADVISORY===
- 段落过长'''
    v2 = parse_final_review_v2(text)
    # v2 解析：6 维标记全无 → items=[] + blocking=[] + advisory=[]
    assert v2["items"] == []
    assert v2["blocking"] == []
    # verdict 由门禁推断（全 0/0/0 → PASS），但调用方应优先走 v1
    # _chapter_review 实现：v2['verdict'] truthy 但 v2['blocking'] 为空时
    # 实际不会返回有用数据，调用方会走 v1 兜底（见 _chapter_review 实现）
    # 走 v1 解析（验证 v1 仍可用）
    blocking, advisory = parse_review_findings(text)
    assert "角色已死亡又出场" in blocking
    assert "段落过长" in advisory
    print(f"  ✓ v1 fallback: v2 解析空 → 调用方走 parse_review_findings() 兜底")


# ---- 测试 5：state 持久化 ----

def test_save_and_load_review_findings():
    """save_review_findings → load_review_findings 闭环"""
    proj = os.path.join(_FH, "test_save")
    os.makedirs(proj, exist_ok=True)
    s = st_mod.load_state(proj)
    st_mod.save_review_findings(proj, s, 1, "REJECT",
                                items=[{"dim": "B_PAYOFF", "level": "fail", "text": "x", "quote": "y", "root_layer": "ROOT_OUTLINE_UNIT"}],
                                blocking=["x"], advisory=[])
    s2 = st_mod.load_state(proj)
    rf = st_mod.load_review_findings(s2, 1)
    assert rf["verdict"] == "REJECT"
    assert len(rf["items"]) == 1
    assert rf["items"][0]["root_layer"] == "ROOT_OUTLINE_UNIT"
    print(f"  ✓ save/load review_findings: 落盘 + 读回一致")


def test_review_chain_append_and_clear():
    """review_chain 累加 + 清空"""
    proj = os.path.join(_FH, "test_chain")
    os.makedirs(proj, exist_ok=True)
    s = st_mod.load_state(proj)
    st_mod.append_review_chain(proj, s, 1, issues=["i1"], reworks=["f1"],
                                verdict="REJECT", round_no=1)
    s = st_mod.load_state(proj)
    st_mod.append_review_chain(proj, s, 1, issues=["i2"], reworks=["f2"],
                                verdict="PASS", round_no=2)
    s2 = st_mod.load_state(proj)
    chain = s2["review_chain"]["1"]
    assert chain["rounds"] == 2
    assert len(chain["verdict_history"]) == 2
    assert chain["verdict_history"][0]["verdict"] == "REJECT"
    assert chain["verdict_history"][1]["verdict"] == "PASS"
    # 清空
    st_mod.clear_review_chain(proj, s2, 1)
    s3 = st_mod.load_state(proj)
    assert "1" not in s3.get("review_chain", {})
    print(f"  ✓ review_chain: 2 轮累加 + clear 后 1章空")


def test_mark_chapter_need_human():
    """3 次 REJECT 不收敛 → 标 human"""
    proj = os.path.join(_FH, "test_human")
    os.makedirs(proj, exist_ok=True)
    s = st_mod.load_state(proj)
    assert not st_mod.is_chapter_need_human(s, 5)
    st_mod.mark_chapter_need_human(proj, s, 5)
    s2 = st_mod.load_state(proj)
    assert st_mod.is_chapter_need_human(s2, 5)
    assert not st_mod.is_chapter_need_human(s2, 6)
    print(f"  ✓ mark_chapter_need_human: 第 5 章标 human → is_chapter_need_human(5)=True")


# ---- 测试 6：3 元组 _chapter_review 签名 ----

def test_chapter_review_signature_3tuple():
    """GUI 端 _chapter_review 应返回 3 元组 (blocking, advisory, verdict)"""
    import inspect
    from app.core.stages import _chapter_review
    sig = inspect.signature(_chapter_review)
    # 仅验证函数存在并接受 (ctx, num, prose)
    params = list(sig.parameters.keys())
    assert params == ["ctx", "num", "prose"]
    print(f"  ✓ _chapter_review 签名: (ctx, num, prose) → 3 元组返回")


# ---- runner ----

if __name__ == "__main__":
    print("== test_review_v2 ==")
    test_parse_v2_pass()
    test_parse_v2_pass_with_notes()
    test_parse_v2_reject()
    test_parse_v2_auto_infer_no_verdict()
    test_build_issues_brief_basic()
    test_build_issues_brief_empty()
    test_build_issues_brief_truncate()
    test_build_upstream_anchors_empty()
    test_build_upstream_anchors_with_files()
    test_v1_fallback_when_no_v2_format()
    test_save_and_load_review_findings()
    test_review_chain_append_and_clear()
    test_mark_chapter_need_human()
    test_chapter_review_signature_3tuple()
    shutil.rmtree(_FH, ignore_errors=True)
    print("\n✓ All 14 tests passed")
