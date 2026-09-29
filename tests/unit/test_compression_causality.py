# -*- coding: utf-8 -*-
"""WA5 保险丝⑥：因果链保链断言（app/core/history_compaction.py）单元测试

覆盖卡 WA5/B1+B8（FlawedFictions 缺口，arXiv 2504.11900「摘要丢因果链 = 连续性
错误率 +50%」）的四条验收：
  ① 含因果对样本 → 现有压缩函数 → 断言清单校验触发（提取条数 / 在场 / 逐级归属）；
  ② 无因果对样本 → 零开销直通（断言 0 条，块文本与纯装配逐字节一致）；
  ③ 断言失败 → 保链降级（失败句原文保底附加成第五节）；保底追加破保险丝①
     （不再显著小于被替换历史）→ 整笔拒绝、保留原稿；
  ④ 归一化命中（引号/全半角/空白差仍判在场——normalize 与 C42 fact_ledger
     是同一函数）。
另钉：伏笔承诺/钩子应答两源断言、读侧复验（opening_block 复用前按「块+本章
常驻」复核断言，失败转现场重装配）。全部 tmp_path 真实项目树，零 LLM、零网络
（夹具风格对齐 test_history_compaction.py）。
"""
import json
import os

import pytest

from app import project as pj
from app.core import history_compaction as hc
from app.core import memory as mem
from app.core.volume_session import session_events_path

CFG_ON = {"writing": {"compaction": True}}

# 「毒句」：因果对样板——赤蝎粉/酒坛/副将/当夜/倒地 这些锚词只在本句出现，
# 不进近程尾巴（放第 1 章中段）、不进任何摘要与台账 → 断言必失败。
POISON = "赤蝎粉混入了酒坛，于是副将当夜腹痛倒地。"
# 「良句」：同样的因果结构，但作为第 2 章结尾（近程尾巴逐字保留）→ 断言在场。
GOOD_TAIL = "青铜铃在井底发烫，于是守夜人彻夜难眠。"


@pytest.fixture(autouse=True)
def _isolate_real_usage(tmp_path, monkeypatch):
    """红线：单测绝不读/写用户真实 usage.jsonl"""
    from app import usage as usage_mod
    monkeypatch.setattr(usage_mod, "FILE", str(tmp_path / "_no_real_usage.jsonl"))


# ---------------- 假项目家目录（真实文件名 + 真实落盘路径） ----------------

def _plain_body(n: int, extra: str = "") -> str:
    return ("# 第%d章 章节%d\n\n夜色沉，守夜人照例巡街，灯火依次点起。\n"
            "巷子深处一片安静，梆子敲过三巡。\n%s\n"
            % (n, n, ("\n" + extra) if extra else ""))


def _make_home(base, *, chapters=3, bodies=None, foreshadow_md="",
               hook_ledger=None, chapter_count=None):
    """造 home/书名/{设定,大纲,正文,追踪,会话} 全树。

    bodies：{章号: 正文全文}；缺省为无因果连接词的平文本。
    foreshadow_md：追加进 追踪/伏笔.md 的表格行（空 = 只有表头，无未回收伏笔）。
    hook_ledger：list → 落 追踪/钩子账本.json；None = 不落文件。
    """
    home = base / "home"
    proj = home / "长夜灯"
    root = str(proj)
    pj.create_project(str(home), "长夜灯")
    pj.write_file(os.path.join(root, "设定", "题材定位.md"),
                  "# 题材定位\n\n## 核心设定\n都市守夜人，单主角。\n\n"
                  "### 金手指约束条款\n- 每夜只能点一次灯。\n\n"
                  "### 全局红线\n- 不出现真实机构名。\n\n"
                  "### 授权自创清单\n- 「长夜灯」为授权自创物。\n")
    pj.write_file(os.path.join(root, "设定", "正则.md"),
                  "# 正则契约\n\n- 每章至少一个钩子。｜level：must｜scope：全局\n")
    pj.write_file(os.path.join(root, "设定", "世界书.md"),
                  "## 条目\n\n- **守夜人**（身份）：掌灯者。\n  [常驻]\n")
    pj.write_file(os.path.join(root, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：边陲（3万字，%d章）\n"
                  % (chapter_count or chapters))
    for n in range(1, chapters + 1):
        pj.write_file(pj.get_outline_path(root, n),
                      "### 第 %d 章：章节%d\n- 核心事件：守夜人巡街\n" % (n, n))
        pj.write_file(pj.get_chapter_path(root, n, "章节%d" % n),
                      (bodies or {}).get(n) or _plain_body(n))
        mem.append_chapter_summary(root, n, "章节%d" % n,
                                   "第%d章摘要：守夜人巡街，灯火如常。" % n)
    mem.write_global_summary(root, "全局：守夜人接掌灯之责，长夜至今无大事。")
    pj.write_file(pj.get_tracking_path(root, "角色状态"),
                  "# 角色状态追踪\n\n- 守夜人：值守如常，灯油充足。\n")
    pj.write_file(pj.get_tracking_path(root, "时间线"),
                  "# 故事时间线\n\n| 故事内时间 | 章节 | 事件 |\n|---|---|---|\n"
                  "| 第1夜 | 第1章 | 巡街，无异常。|\n")
    pj.write_file(pj.get_tracking_path(root, "伏笔"),
                  "# 伏笔追踪\n\n> 状态：未埋 / 已埋 / 已回收\n\n"
                  "| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                  "|------|------|----------|------|----------|------|\n" + foreshadow_md)
    if hook_ledger is not None:
        path = os.path.join(root, "追踪", "钩子账本.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hook_ledger, f, ensure_ascii=False, indent=1)
    return root


def _read_events(root: str) -> list:
    path = session_events_path(root)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


# ==================== ① 含因果对：断言清单校验触发（在场） ====================

def test_causal_pair_in_near_tail_is_checked_and_satisfied(tmp_path):
    """第 2 章结尾的因果句随近程尾巴逐字在块内 → cause_effect 断言被提取、
    逐条核对且全部在场：零降级、零保底附加（保链不打折也不多余）。"""
    bodies = {2: _plain_body(2, extra=GOOD_TAIL)}
    proj = _make_home(tmp_path, chapters=3, bodies=bodies)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, upto=3, write=False,
                               replaced_hint=300_000)
    assert r.ok, r.reason
    assert r.causal_checked >= 1, "含因果句的样本必须产出断言清单"
    assert r.causal_failed == 0 and r.degraded is False
    assert hc.CHAIN_SECTION_TITLE not in r.text
    assert GOOD_TAIL in r.text                       # 近程尾巴本身扛住了因果链
    causal = r.sections["causal"]
    assert causal["checked"] == r.causal_checked
    assert causal["failed"] == 0 and causal["degraded"] is False
    kinds = {a["kind"] for a in causal["assertions"]}
    assert "cause_effect" in kinds


def test_per_level_attribution_records_first_satisfying_level(tmp_path):
    """逐级接入：每一级原料过同一 assert_causal_chain，归属记首个满足的层级；
    全部层级都不满足 → 失败且归属为空串（机读诊断：哪一级扛住哪条链）。"""
    a = hc.CausalAssertion(kind="cause_effect", chapter=1,
                           slots=(("青铜铃",), ("彻夜难眠",)),
                           sentence="青铜铃响，他彻夜难眠。", source="测试")
    rep = hc.assert_causal_chain(
        (("resident", "常驻里没有"), ("near_endings", "夜里青铜铃响，他彻夜难眠。"),
         ("recent_summaries", "")), [a])
    assert rep.ok and rep.checked == 1
    assert rep.levels == {"0": "near_endings"}
    rep2 = hc.assert_causal_chain((("resident", "无关文本"), ("ledger", "也没有")), [a])
    assert not rep2.ok and len(rep2.failed) == 1 and rep2.levels == {"0": ""}


# ==================== ② 无因果对：零开销直通 ====================

def test_no_causal_pairs_zero_overhead_passthrough(tmp_path):
    """无因果连接词、无未回收伏笔、无钩子账本 → 断言清单 0 条 → 直通：
    块文本与「纯装配（render_handoff）」逐字节一致，本保险丝零贡献零干扰。"""
    proj = _make_home(tmp_path, chapters=3)
    upto = 3
    r = hc.build_handoff_block(proj, cfg=CFG_ON, upto=upto, write=False,
                               replaced_hint=300_000)
    assert r.ok and r.causal_checked == 0 and r.causal_failed == 0
    assert r.degraded is False and hc.CHAIN_SECTION_TITLE not in r.text
    # 逐字节一致（用同一批公开原料手工复算装配结果）
    from app.core.shared_prefix import chapter_header, project_header
    endings = hc.near_endings(proj, upto)
    summaries = mem.read_recent_summaries(proj, upto + 1, n=hc.SUMMARY_WINDOW)
    resident = "\n\n".join((project_header(proj),
                            chapter_header(proj, upto + 1, volume_mode=True)))
    ledger = hc.ledger_snapshot(proj, resident)
    assert r.text == hc.render_handoff(1, upto, endings, summaries, ledger)


# ==================== ③a 断言失败 → 保链降级（失败句原文保底附加） ====================

def test_failed_assertion_degrades_to_chain_appendix(tmp_path):
    """毒句在第 1 章中段（不在尾巴/摘要/台账任何一级）→ 断言失败 → 降级
    「保链压缩」：失败句原文整句保底附加成第五节，追加后断言转绿并落告警事件。"""
    bodies = {1: _plain_body(1, extra=POISON)}
    proj = _make_home(tmp_path, chapters=3, bodies=bodies)
    r = hc.build_handoff_block(proj, cfg=CFG_ON, upto=3, write=True,
                               replaced_hint=300_000)
    assert r.ok, r.reason
    assert r.causal_checked >= 1 and r.causal_failed >= 1
    assert r.degraded is True
    assert hc.CHAIN_SECTION_TITLE in r.text
    assert POISON.strip() in r.text, "失败句必须原文保底附加"
    causal = r.sections["causal"]
    assert causal["failed_initial"] >= 1 and causal["failed"] == 0, \
        "降级后复验必须全绿"
    assert causal["degraded"] is True
    events = [e for e in _read_events(proj) if e["event"] == "compaction_causal"]
    assert events and events[-1]["degraded"] == 1 and events[-1]["rejected"] == 0
    assert "cause_effect" in events[-1]["kinds"]


# ==================== ③b 保底追加破保险丝① → 整笔拒绝、保留原稿 ====================

def test_reject_when_appendix_breaks_shrink_fuse(tmp_path):
    """降级追加后不再显著小于被替换历史（> SHRINK_MAX_RATIO）→ 保险丝⑥整笔
    拒绝：ok=False、不落任何交接块产物（保留原稿 = 不压缩），告警事件记 rejected。"""
    clean = _make_home(tmp_path / "a", chapters=3)
    poisoned = _make_home(tmp_path / "b", chapters=3, bodies={1: _plain_body(1, extra=POISON)})
    base = hc.build_handoff_block(clean, cfg=CFG_ON, upto=3, write=False,
                                  replaced_hint=10 ** 9)
    assert base.ok and base.causal_checked == 0
    # 两家的块原料完全相同（毒句在第 1 章中段，不进任何一级）→ 基础块等大；
    # hint 取「2×基础块 + 一点余量」：基础块压线过保险丝①，保底追加必爆。
    hint = 2 * base.tokens + 5
    r = hc.build_handoff_block(poisoned, cfg=CFG_ON, upto=3, write=True,
                               replaced_hint=hint)
    assert r.ok is False and r.text == "" and r.artifacts == ()
    assert r.causal_checked >= 1 and r.causal_failed >= 1
    assert "保险丝⑥" in (r.reason or "") and "因果断言" in r.reason
    assert not os.path.exists(hc.handoff_json_path(poisoned, 1)), "拒绝 = 保留原稿不落盘"
    events = [e for e in _read_events(poisoned) if e["event"] == "compaction_causal"]
    assert events and events[-1]["rejected"] == 1 and events[-1]["degraded"] == 0


# ==================== ④ 归一化命中（同义改写/全半角仍判在场） ====================

def test_normalized_alias_still_counts_as_present(tmp_path):
    """在场判定走 C42 fact_ledger.normalize（同一函数）：全半角、引号差、
    空白差都不假报丢失；真缺席才失败。"""
    import unicodedata
    from app.core import fact_ledger
    assert hc.normalize is fact_ledger.normalize, "归一化必须复用 C42 同一函数"
    a = hc.CausalAssertion(kind="cause_effect", chapter=1,
                           slots=(("ＡＢＣ 港",), ("『赤蝎粉』",)),
                           sentence="ＡＢＣ 港到了赤蝎粉。", source="测试")
    text = "船靠了「ＡＢＣ港」，  赤蝎粉……（引号/全角/空白全变体）"
    rep = hc.assert_causal_chain((("summaries", text),), [a])
    assert rep.ok and rep.levels == {"0": "summaries"}
    rep2 = hc.assert_causal_chain((("summaries", "锚词真缺席的压缩稿"),), [a])
    assert not rep2.ok and len(rep2.failed) == 1
    assert unicodedata.normalize("NFKC", "ＡＢＣ") == "ABC"   # 口径本身钉住


# ==================== 伏笔承诺 / 钩子应答两源 ====================

def test_foreshadow_promise_and_hook_response_assertions(tmp_path):
    """未回收伏笔 = promise_payoff 断言（在场）；事件钩 event_kw =
    hook_response 断言（缺席 → 降级保底）；钩子账本损坏 → 该源静默归零。"""
    foreshadow_md = "| 伏笔未决·青铜古灯 | 道具谜团 | 第1章 | 已埋 | 第8-10章 | 灯芯成灰 |\n"
    hook = [{"num": 2, "position": "章尾", "type": "悬念缺口", "strength": "强",
             "summary": "沉船异响", "event_kw": "夜枭号沉船", "is_event_hook": True}]
    proj = _make_home(tmp_path, chapters=3, foreshadow_md=foreshadow_md,
                      hook_ledger=hook)
    assertions = hc.collect_causal_assertions(proj, hc.chapter_prose(proj, 1, 3))
    kinds = {a.kind for a in assertions}
    assert "promise_payoff" in kinds and "hook_response" in kinds
    r = hc.build_handoff_block(proj, cfg=CFG_ON, upto=3, write=True,
                               replaced_hint=300_000)
    assert r.ok and r.degraded is True, "钩子关键词缺席必须触发保链降级"
    assert r.causal_failed >= 1 and "夜枭号沉船" in r.text
    assert "[hook_response·" in r.text, "保底节只应包含失败的事件钩断言"
    assert "[promise_payoff·" not in r.text, "伏笔承诺由账本/常驻在场，不得误降级"
    promise_ok = [a for a in r.sections["causal"]["assertions"]
                  if a["kind"] == "promise_payoff"]
    assert promise_ok, "伏笔承诺断言必须被提取"
    # 钩子账本损坏 → 该源零断言（fail-open，不影响其他源）
    with open(os.path.join(proj, "追踪", "钩子账本.json"), "w", encoding="utf-8") as f:
        f.write("{这行不是 JSON")
    assertions2 = hc.collect_causal_assertions(proj, hc.chapter_prose(proj, 1, 3))
    assert all(a.kind != "hook_response" for a in assertions2)
    assert any(a.kind == "promise_payoff" for a in assertions2)


# ==================== 读侧复验：opening_block 复用前复核断言 ====================

def test_opening_block_reuse_revalidates_chain(tmp_path):
    """正常复用（断言仍全在场）照旧 reason=handoff_卷1、文本逐字节同产物；
    台账在建档后被清空抽走承诺的唯一载体 → 读侧复验失败 → 不复用旧块，
    转现场重装配（带完整保链管线），并落 handoff_causal_stale 事件。"""
    foreshadow_md = "| 伏笔未决·青铜古灯 | 道具谜团 | 第1章 | 已埋 | 第8-10章 | 灯芯成灰 |\n"
    # 章体加长：重装配路径不带 replaced_hint，走单章正文口径的保险丝①——
    # 小夹具过不去（见 test_compaction_v1_fixes 的兜底语义），这里给足正文。
    filler = "巷子深处一片安静，梆子敲过三巡。" * 200
    bodies = {1: _plain_body(1, extra=filler), 2: _plain_body(2, extra=filler)}
    proj = _make_home(tmp_path, chapters=2, bodies=bodies, foreshadow_md=foreshadow_md)
    built = hc.build_handoff_block(proj, cfg=CFG_ON, upto=2, write=True,
                                   replaced_hint=300_000)
    assert built.ok and built.sections["causal"]["checked"] >= 1
    ob1 = hc.opening_block(proj, 3, cfg=CFG_ON)
    assert ob1.contributed and ob1.reason == "handoff_卷1"
    assert ob1.text == built.text, "断言仍在场 → 复用照旧，逐字节同产物"
    # 台账被清空：承诺的唯一在场载体（建档时的常驻注入）已消失
    pj.write_file(pj.get_tracking_path(proj, "伏笔"),
                  "# 伏笔追踪\n\n| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                  "|------|------|----------|------|----------|------|\n")
    ob2 = hc.opening_block(proj, 3, cfg=CFG_ON)
    assert ob2.contributed and ob2.reason.startswith("assembled"), \
        "读侧断言失败必须放弃复用、现场重装配（ob2=%r）" % ob2.reason
    assert "青铜古灯" not in ob2.text, "重装配后块里也不该再有已被抽走的承诺"
    stale = [e for e in _read_events(proj) if e["event"] == "handoff_causal_stale"]
    assert stale and stale[-1]["failed"] >= 1


# ==================== 提取器纯函数（启发式边界） ====================

def test_extractor_edges_and_determinism():
    """连接词长词优先、两侧过短弃判、别名组顺序确定（产物字节稳定纪律）。"""
    assert hc._split_causal_sentence("所以他走了。") is None      # 连接词在句首
    assert hc._split_causal_sentence("他因为雨。") is None        # 侧过短
    parts = hc._split_causal_sentence("因为闸门崩了，所以洪水灌进城。")
    assert parts and parts[1] in hc.CAUSAL_CONNECTIVES \
        and "闸门" in parts[0] + parts[2] and "洪水" in parts[0] + parts[2]
    t1 = hc.causal_terms("守夜人把青铜铃沉入了井底")
    t2 = hc.causal_terms("守夜人把青铜铃沉入了井底")
    assert t1 == t2 and t1, "别名组必须顺序确定"
    assert hc.causal_terms("的了是在") == (), "纯功能字侧不给锚词"
