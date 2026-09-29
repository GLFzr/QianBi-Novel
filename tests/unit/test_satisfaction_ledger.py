# -*- coding: utf-8 -*-
"""C33/T1 爽点节奏账本回归（app/core/satisfaction.py 账本段 + l0_checks.ledger_findings）

三规则（连排/空头支票/类型轮换）各一红一绿；账本读写 roundtrip；B_PAYOFF 裁决
回写 delivered；off 态字节不变（账本开关 off 时 V5 块与现状逐字一致）。账本是
「记录+核对」通道：纯确定性、纯本地零 LLM，不受字节隔离纪律约束（缺省 on），
但 off 态仍须逐字节惰性。全部离线零 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import config
from app.core import satisfaction as sat
from app.core.l0_checks import build_v5_block, ledger_findings

BEAT = "- 本章爽点节拍：压抑（被扣押金）→ 反转（亮出录音）→ 结算（押金到账）\n"


def _outline(beat_line=BEAT, type_line="", intensity=""):
    return ("### 第 N 章：测试\n- 爽点：兑现承诺。\n"
            + beat_line + type_line + intensity + "- 结尾：收束。\n")


def _row(num, t, declared=True, delivered=True):
    segs = ["压抑（…）", "反转（…）", "结算（…）"] if declared else []
    return {"num": num, "beats_declared": list(segs),
            "beats_delivered": (list(segs) if delivered is True
                                else ([] if delivered is False else None)),
            "类型": t, "强度": "中"}


def _tmpdir():
    import tempfile
    return tempfile.mkdtemp(prefix="qbn_ledger_")


# ---------------- 开关缺省态（与引擎开关解耦的语义钉） ----------------

def test_default_config_ledger_on_and_decoupled():
    """账本缺省 on；与 satisfaction_engine（缺省 off）解耦——两开关互不牵动"""
    assert config.DEFAULT_CONFIG["writing"]["satisfaction_ledger_enabled"] is True
    assert config.DEFAULT_CONFIG["writing"]["satisfaction_engine"] is False
    assert sat.ledger_enabled({}) is True
    assert sat.ledger_enabled({"writing": {}}) is True
    assert sat.ledger_enabled({"writing": {"satisfaction_ledger_enabled": False}}) is False


# ---------------- 账本读写 roundtrip ----------------

def test_ledger_roundtrip_upsert_sorted():
    """record_chapter 按 num upsert、保持章序；重写同章覆盖旧值；中文不转义"""
    proj = _tmpdir()
    sat.record_chapter(proj, _row(2, "打脸"))
    sat.record_chapter(proj, _row(1, "收获"))
    sat.record_chapter(proj, _row(2, "突破"))          # 重写第 2 章 → 覆盖
    data = sat.load_ledger(proj)
    assert data["version"] == 1
    assert [r["num"] for r in data["rows"]] == [1, 2]
    assert data["rows"][1]["类型"] == "突破"
    raw = open(sat._ledger_path(proj), encoding="utf-8").read()
    assert "突破" in raw and "\\u" not in raw, "ensure_ascii=False：中文须直存"


def test_ledger_load_fail_open():
    """账本缺失/损坏 → 空账本（fail-open，绝不阻断）"""
    assert sat.load_ledger("G:/__no_such_proj_c33__") == {"version": 1, "rows": []}


# ---------------- ledger_row 立据字段 ----------------

def test_ledger_row_fields_from_cw_outline():
    """cw 细纲字段（节拍行+类型+强度）→ 立据三拍段/类型/强度"""
    ol = _outline(type_line="- 节拍类型：打脸\n", intensity="- 节拍强度：强\n")
    row = sat.ledger_row(6, ol, {"writing": {}})
    assert row["num"] == 6
    assert len(row["beats_declared"]) == 3 and row["beats_declared"][0].startswith("压抑")
    assert row["beats_delivered"] is None, "初值 None=未审，不计欠账"
    assert row["类型"] == "打脸" and row["强度"] == "强"


def test_ledger_row_gap_and_classification():
    """显式空档 → 空声明不参统计；细纲显式类型行优先；无类型行 → 关键词归类"""
    gap = sat.ledger_row(7, _outline("- 本章爽点节拍：本章无节拍（低压承接）\n"
                                     "- 节拍类型：无\n- 节拍强度：无\n"), {"writing": {}})
    assert gap["beats_declared"] == [] and gap["类型"] == "" and gap["强度"] == ""
    explicit = sat.ledger_row(9, _outline(type_line="- 节拍类型：护短\n"), {"writing": {}})
    assert explicit["类型"] == "护短", "细纲显式类型行优先（受控表外照记）"
    kw = sat.classify_type("压抑（被嘲讽）→ 反转（当场反击）→ 结算（围观态度反转）")
    assert kw == "打脸"
    assert sat.classify_type("压抑（被扣押金）→ 反转（亮出录音）→ 结算（押金到账）") == "其他"


def test_ledger_row_off_switch_inert():
    """账本 off → ledger_row 返回 None（stages 立据/落账全链路惰性）"""
    assert sat.ledger_row(6, _outline(),
                          {"writing": {"satisfaction_ledger_enabled": False}}) is None


# ---------------- B_PAYOFF 裁决回写 delivered ----------------

def test_payoff_verdict_fail_breach_and_pass_copies():
    """红：B_PAYOFF fail → delivered=[]（空头支票欠账）；绿：pass/marginal → 拷贝 declared"""
    row = sat.ledger_row(6, _outline(), {"writing": {}})
    sat.apply_payoff_verdict(row, [{"dim": "B_PAYOFF", "level": "fail", "text": "推迟"}])
    assert row["beats_delivered"] == []
    row2 = sat.ledger_row(7, _outline(), {"writing": {}})
    declared = list(row2["beats_declared"])
    sat.apply_payoff_verdict(row2, [{"dim": "B_PAYOFF", "level": "marginal", "text": "略缓"}])
    assert row2["beats_delivered"] == declared


def test_payoff_verdict_no_evidence_stays_none():
    """未审/人工审校/字数预检拦截（无 B_PAYOFF 条目）→ 保持 None，不评不计欠账"""
    row = sat.ledger_row(6, _outline(), {"writing": {}})
    sat.apply_payoff_verdict(row, [{"dim": "D_PLOT", "level": "fail", "text": "无关维"}])
    assert row["beats_delivered"] is None
    sat.apply_payoff_verdict(row, [])
    assert row["beats_delivered"] is None


# ---------------- 规则① 连排（节奏单一）：红/绿 ----------------

def test_rule1_same_type_run3_flags_fail():
    """红：同型节拍连排 ≥3 章且本章在列 → fail候选「节奏单一」"""
    rows = [_row(1, "打脸"), _row(2, "打脸"), _row(3, "打脸")]
    ol = _outline(type_line="- 节拍类型：打脸\n")
    fs = sat.rhythm_findings(rows, 4, ol)
    assert fs and fs[0]["level"] == "fail候选" and fs[0]["check"] == "节奏单一"
    assert "第1、2、3、4章" in fs[0]["text"] and "4 章" in fs[0]["text"]


def test_rule1_varied_types_clean():
    """绿：类型轮换 → 零 finding；历史旧连排（本章已换型/本章空档）不重复追责"""
    rows = [_row(1, "打脸"), _row(2, "收获"), _row(3, "突破")]
    assert sat.rhythm_findings(rows, 4, _outline(type_line="- 节拍类型：打脸\n")) == []
    hist_run = [_row(1, "打脸"), _row(2, "打脸"), _row(3, "打脸")]
    assert sat.rhythm_findings(hist_run, 4, _outline(type_line="- 节拍类型：收获\n")) == []
    gap_break = [_row(1, "打脸"), _row(2, ""), _row(3, "打脸", declared=False)]
    assert sat.rhythm_findings(gap_break, 4, _outline(type_line="- 节拍类型：打脸\n")) == []


# ---------------- 规则② 闭环率（空头支票）：红/绿 ----------------

def test_rule2_two_breaches_flags_fail():
    """红：声明节拍但章末判未兑现累计 ≥2 → fail候选「空头支票」"""
    rows = [_row(5, "打脸", delivered=False), _row(6, "收获", delivered=False),
            _row(7, "突破", delivered=True), _row(8, "揭露", delivered=None)]
    fs = sat.rhythm_findings(rows, 9)
    assert fs and fs[0]["level"] == "fail候选" and fs[0]["check"] == "空头支票"
    assert "第5、6章" in fs[0]["text"], "只计 delivered==[] 的欠账章"


def test_rule2_below_threshold_clean():
    """绿：单张欠账/全部兑现/未审 → 不判（未审 None 不计欠账）"""
    rows = [_row(5, "打脸", delivered=False), _row(6, "收获", delivered=True),
            _row(7, "突破", delivered=None)]
    assert sat.rhythm_findings(rows, 8) == []
    assert sat.rhythm_findings([_row(5, "打脸")], 6) == []


# ---------------- 规则③ 类型轮换（熵）：红/绿 ----------------

def test_rule3_low_entropy_advisory():
    """红：全书类型分布熵过低（≥6 章且 H<1.0 bit）→ advisory「类型轮换」"""
    rows = [_row(i, "打脸") for i in range(1, 6)] + [_row(6, "收获")]
    fs = sat.rhythm_findings(rows, 7)
    assert fs and fs[0]["level"] == "advisory" and fs[0]["check"] == "类型轮换"
    assert "bit" in fs[0]["text"]


def test_rule3_rotated_or_small_sample_clean():
    """绿：均匀轮换（H=1.0 不低于阈值）/样本 <6 章不评 → 零 finding"""
    rows = [_row(1, "打脸"), _row(2, "收获"), _row(3, "突破"),
            _row(4, "打脸"), _row(5, "收获"), _row(6, "突破")]
    assert sat.rhythm_findings(rows, 7) == []
    assert sat.rhythm_findings([_row(1, "打脸"), _row(2, "打脸"), _row(3, "打脸")], 4) == []


def test_rhythm_findings_fail_open_and_window():
    """fail-open：异常输入返回空；cur_num 之后的历史行不参与（未审章不预支追责）"""
    assert sat.rhythm_findings(None, "x") == []
    rows = [_row(1, "打脸"), _row(2, "打脸"), _row(3, "打脸"), _row(9, "打脸")]
    fs = sat.rhythm_findings(rows, 4, _outline(type_line="- 节拍类型：打脸\n"))
    assert fs and "9" not in fs[0]["text"].split("章连续")[0], "第 9 章（≥cur）不入连排窗口"


# ---------------- l0_checks.ledger_findings + V5 块（on 挂进 / off 字节不变） ----------------

def _mk_proj_with_rows(tmp_path, rows):
    sat.save_ledger(str(tmp_path), {"version": 1, "rows": rows})
    return str(tmp_path)


def test_v5_block_carries_ledger_findings(tmp_path, monkeypatch):
    """on：账本欠账 → V5 块出现 [fail候选|空头支票]（挂进 L0 输出，三审校注入点共用）"""
    monkeypatch.setattr(config, "load_config",
                        lambda: {"writing": {"satisfaction_ledger_enabled": True}})
    proj = _mk_proj_with_rows(tmp_path, [_row(5, "打脸", delivered=False),
                                         _row(6, "收获", delivered=False)])
    block = build_v5_block(proj, 7, "", read_outline=lambda: "", read_states=lambda: "")
    assert "[fail候选|空头支票]" in block
    fs = ledger_findings(proj, 7, "")
    assert fs and fs[0]["check"] == "空头支票"


def test_v5_block_off_switch_byte_identical(tmp_path, monkeypatch):
    """off：有账本在盘也不注入——V5 块与「无账本」逐字一致（off 态字节不变）"""
    monkeypatch.setattr(config, "load_config",
                        lambda: {"writing": {"satisfaction_ledger_enabled": False}})
    proj = _mk_proj_with_rows(tmp_path, [_row(1, "打脸"), _row(2, "打脸"), _row(3, "打脸")])
    b1 = build_v5_block(proj, 4, "", read_outline=lambda: "", read_states=lambda: "")
    os.remove(sat._ledger_path(proj))
    b2 = build_v5_block(proj, 4, "", read_outline=lambda: "", read_states=lambda: "")
    assert b1 == b2 and "节奏单一" not in b1 and "账本" not in b1


def test_v5_block_no_evidence_byte_identical(tmp_path, monkeypatch):
    """证据在场才检查：缺省 on 但账本文件缺失 → 恒空（旧书字节不变）"""
    monkeypatch.setattr(config, "load_config", lambda: {})
    block = build_v5_block(str(tmp_path), 4, "", read_outline=lambda: "",
                           read_states=lambda: "")
    assert block == ""


def test_ledger_findings_cfg_gate_direct(tmp_path):
    """ledger_findings 直受 cfg 门控：off → 恒空；on 但无违例 → 恒空"""
    proj = _mk_proj_with_rows(tmp_path, [_row(1, "打脸")])
    assert ledger_findings(proj, 2, "",
                           cfg={"writing": {"satisfaction_ledger_enabled": False}}) == []
    assert ledger_findings(proj, 2, "", cfg={"writing": {}}) == [], \
        "有行但无违例（单章打脸不连排/无欠账/样本不足）→ 恒空"
