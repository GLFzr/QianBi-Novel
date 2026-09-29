# -*- coding: utf-8 -*-
"""C42/P1 事实账本回归（app/core/fact_ledger.py + stages._mc_finalize /
co_dialogue._run_backflow 挂点）

覆盖：归一化三态（strict/norm/拒收——录入噪声被归一化救回）、逐条拒收不连坐、
三类幻觉对照（改写/跨章拦截、width_variant 救回——卡9 §⑤ 点名的
test_hallucination_triple_blocked）、抽取解析 schema、jsonl append 去重、
freshness 对账（对接 backflow_is_fresh 口径）、挂点钉。全部离线零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import fact_ledger as fl

CH3 = ("# 第3章 叩门\n\n"
       "陈更开门迎客，门槛上的霜还没有化。\n"
       "“灯芯只剩三寸了。”陈更低声说，指尖压住账册。\n"
       "柳三更把铜哨放进袖袋，转身走向灯阵。\n")

GOOD1 = {"claim": "灯芯余量告急", "evidence": "“灯芯只剩三寸了。”陈更低声说，指尖压住账册。"}
GOOD2 = {"claim": "柳三更携带铜哨", "evidence": "柳三更把铜哨放进袖袋，转身走向灯阵。"}
# 幻觉a：改写（语序对调——凭记忆重排）
PARAPHRASE = {"claim": "灯芯余量告急（改写）",
              "evidence": "指尖压住账册，“灯芯只剩三寸了。”陈更低声说"}
# 幻觉b：跨章错绑（真实存在但属第1章的句子）
CROSS_CH = {"claim": "第3章新事件", "evidence": "陈更在灯阵前守夜，柳三更送来一枚铜哨。"}
# 幻觉c：录入噪声（全角引号→直引号 + 塞空格——归一化应救回）
NOISY = {"claim": "灯芯余量告急（噪声）",
         "evidence": '灯芯 只剩三寸  了。"陈更低声说，指尖压住账册。'}


def _proj(tmp_path):
    proj = tmp_path / "p"
    os.makedirs(os.path.join(str(proj), "正文"))
    with open(os.path.join(str(proj), "正文", "第3章_叩门.md"), "w", encoding="utf-8") as f:
        f.write(CH3)
    return str(proj)


# ---------------- 归一化与两级锚定 ----------------

def test_normalize_unifies_quotes_width_and_whitespace():
    """NFKC+去空白+引号统一：全半角引号互换、插空格、全角字母——归一化后同串"""
    assert fl.normalize("“灯 芯”") == fl.normalize("灯芯") == "灯芯"
    assert fl.normalize('灯芯') == "灯芯"                     # 直引号剥除
    assert fl.normalize("「灯芯」") == "灯芯"                  # 方头引号剥除
    assert fl.normalize("ＡＢＣ") == "ABC"                     # NFKC 全角→半角
    assert fl.normalize("") == "" and fl.normalize(None) == ""


def test_anchor_two_level_three_states():
    """三态：原文逐字→strict；引号/空差噪声→norm；改写/跨章→None（拒收）"""
    assert fl.anchor_level(GOOD1["evidence"], CH3) == "strict"
    assert fl.anchor_level(NOISY["evidence"], CH3) == "norm"
    assert fl.anchor_level(PARAPHRASE["evidence"], CH3) is None
    assert fl.anchor_level(CROSS_CH["evidence"], CH3) is None
    assert fl.anchor_level("", CH3) is None and fl.anchor_level(GOOD1["evidence"], "") is None


# ---------------- 抽取解析与 schema ----------------

def test_extract_facts_schema_variants():
    """三形态宽容解析（对象/围栏/裸数组）；缺 evidence 的条目剔除并附原因"""
    payload = [dict(GOOD1), {"claim": "无引文条目"}]
    for raw in (
        json.dumps({"facts": payload}, ensure_ascii=False),
        "说明文字\n```json\n" + json.dumps({"facts": payload}, ensure_ascii=False) + "\n```",
        json.dumps(payload, ensure_ascii=False),
    ):
        facts, rej = fl.extract_facts(3, raw)
        assert [f["evidence"] for f in facts] == [GOOD1["evidence"]]
        assert facts[0]["chapter"] == 3
        assert len(rej) == 1 and "evidence" in rej[0]["reason"]
    assert fl.extract_facts(3, None)[0] == []
    facts, _ = fl.extract_facts(3, "")
    assert facts == []


def test_extract_facts_overlength_evidence_rejected():
    """超长 evidence（>500）剔除——防御超长垃圾引文"""
    bad = {"claim": "x", "evidence": "长" * 600}
    facts, rej = fl.extract_facts(3, {"facts": [bad]})
    assert facts == [] and "超长" in rej[0]["reason"]


# ---------------- 逐条拒收 + 三类幻觉 ----------------

def test_per_fact_rejection_keeps_neighbors(tmp_path):
    """逐条拒收不连坐：坏条目只拒自身，同批好事实照常入账"""
    proj = _proj(tmp_path)
    rep = fl.ingest_facts(proj, 3, [dict(GOOD1), dict(PARAPHRASE), dict(GOOD2)], CH3)
    assert rep["total"] == 3 and rep["kept"] == 2 and rep["rejected"] == 1
    assert rep["strict"] == 2 and rep["norm"] == 0
    assert "不连坐" in rep["rejected_items"][0]["reason"]
    rows = fl.read_ledger(proj)
    assert sorted(r["claim"] for r in rows) == sorted([GOOD1["claim"], GOOD2["claim"]])


def test_hallucination_triple_blocked(tmp_path):
    """卡9 §⑤ 点名：改写/跨章全拦（拒收），width_variant 100% 被归一化救回"""
    proj = _proj(tmp_path)
    rep = fl.ingest_facts(proj, 3, [dict(PARAPHRASE), dict(CROSS_CH), dict(NOISY)], CH3)
    assert rep["rejected"] == 2, "改写+跨章必须拒收"
    assert rep["kept"] == 1 and rep["norm"] == 1, "噪声条目须由归一化锚定救回"
    row = fl.read_ledger(proj)[0]
    assert row["claim"] == NOISY["claim"] and row["anchored"] == "norm"


# ---------------- 账本读写：append 去重 + fail-open + freshness ----------------

def test_ledger_roundtrip_dedup_per_chapter(tmp_path):
    """append-only + 按章去重：同章同事实只记一笔；跨章同文各记一笔；中文直存"""
    proj = _proj(tmp_path)
    r1 = fl.ingest_facts(proj, 3, [dict(GOOD1), dict(GOOD2)], CH3)
    assert r1["kept"] == 2 and r1["duplicates"] == 0
    r2 = fl.ingest_facts(proj, 3, [dict(GOOD1), dict(GOOD2)], CH3)
    assert r2["kept"] == 0 and r2["duplicates"] == 2, "同章重跑必须整批去重"
    r3 = fl.ingest_facts(proj, 4, [dict(GOOD1)], CH3)   # 第4章同文 → 新章新账
    assert r3["kept"] == 1
    rows = fl.read_ledger(proj)
    assert sorted((r["chapter"], r["claim"]) for r in rows) == sorted([
        (3, GOOD1["claim"]), (3, GOOD2["claim"]), (4, GOOD1["claim"])])
    raw = open(fl.ledger_path(proj), encoding="utf-8").read()
    assert GOOD2["claim"] in raw and "\\u" not in raw, "ensure_ascii=False：中文须直存"
    assert raw.endswith("\n") and len(raw.strip().splitlines()) == 3


def test_ledger_read_and_ingest_fail_open(tmp_path):
    """账本缺失→[]；空批次零写入不建文件"""
    assert fl.read_ledger(str(tmp_path / "nope")) == []
    proj = _proj(tmp_path)
    rep = fl.ingest_facts(proj, 3, [], CH3)
    assert rep["kept"] == 0 and not os.path.exists(fl.ledger_path(proj))


def test_ledger_is_fresh_states(tmp_path):
    """freshness 三态：有行且正文未再动→True；正文后改→False；无行→False

    S6a：正文路径改由调用方传入（chapter_path 参数注入）。
    """
    proj = _proj(tmp_path)
    chap = os.path.join(proj, "正文", "第3章_叩门.md")
    assert fl.ledger_is_fresh(proj, 3, chapter_path=chap) is False, "无账本行=不新鲜"
    fl.ingest_facts(proj, 3, [dict(GOOD1)], CH3)
    st = os.stat(chap)
    os.utime(chap, (st.st_atime - 5, st.st_mtime - 5))   # 落账前写成（消除同秒竞态）
    assert fl.ledger_is_fresh(proj, 3, chapter_path=chap) is True
    os.utime(chap, (st.st_atime + 120, st.st_mtime + 120))
    assert fl.ledger_is_fresh(proj, 3, chapter_path=chap) is False, "正文在落账后被改动=账本陈旧"
    assert fl.ledger_is_fresh(proj, 9, chapter_path=chap) is False


def test_ingest_from_extraction_skip_paths(tmp_path):
    """挂点跳过语义：raw 空/垃圾 → None 且不建文件（抽取闸门未接入的常态）"""
    proj = _proj(tmp_path)
    for raw in (None, "", "   ", "模型输出不是 JSON"):
        assert fl.ingest_from_extraction(proj, 3, raw, CH3) is None
    assert not os.path.exists(fl.ledger_path(proj))
    rep = fl.ingest_from_extraction(
        proj, 3, json.dumps({"facts": [GOOD1]}, ensure_ascii=False), CH3)
    assert rep and rep["kept"] == 1


# ---------------- 挂点钉（解线即红） ----------------

def test_wiring_hooks_in_sources():
    """finalize 追踪落账区挂入账（fail-open）；_run_backflow 挂 freshness 对账"""
    import app.core.stages as stages_mod
    import app.core.co_dialogue as co_mod
    stages_src = open(stages_mod.__file__, encoding="utf-8").read()
    co_src = open(co_mod.__file__, encoding="utf-8").read()
    assert stages_src.count("fact_ledger.ingest_from_extraction(") == 1
    assert "fact_ledger.ledger_is_fresh(" in co_src
    assert "st.backflow_is_fresh(" in co_src
