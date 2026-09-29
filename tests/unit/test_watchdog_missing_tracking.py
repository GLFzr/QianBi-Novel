# -*- coding: utf-8 -*-
"""C35 G4/G5 回放式断言：相位看门狗 + usage 台账准实时告警

回放口径：构造模拟台账序列（顶格稿 / 缺 tracking 行 / 正常章混合），全部经
usage.record() 真实记录路径逐条重放（不凭空造异常对象），断言：
  - G5 三规则（①prose 顶格 ②单章成本越限 ③缺记账行）触发的位置与次数逐章对号，
    正常章零误报；
  - 渠道不报 max_tokens/usage 时降级为 debug、不告警不落账（降级口径写明）；
  - G4 看门狗对账判定（台账记账相位行 ∪ 章节摘要链条目）与 auto_pause 连续性
    （连续 2 章缺失才停；恢复即清零；同章重跑不计连续）；
  - 跨进程：内存清零后从盘上台账回放，chapter_accounted 成立、只对尾部未愈合
    断档翻页告警（T3 v1 的 30 章停摆在重启续跑的第一章就被点名）。

背景事实（w2_t31_rootcause.md）：T3 v1 台账 1705 行里 ch41-44 prose 精确顶格
16384、ch41-46 记账相位真空、ch1-40 正常——G5 回放必须恰好命中异常章、正常章
零误报；G4 在「正文已落库而记账产物缺失」连续 2 章时 auto_pause。
"""
import importlib
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app import project as pj
from app.core import state as st
from app.core import stages
from app.core.orchestrator import Orchestrator

_MAXTOK = 16384          # T3 服务端钳位值（顶格指纹）
_MT = {"max_tokens": _MAXTOK}
_MODEL = "deepseek-v4-flash"   # 含 "flash" → 费率表 (1.0, 2.0) 元/百万 tok


# ---------- 假件与夹具 ----------

def _isolate(m, tmp_path, monkeypatch):
    """usage 落盘路径指到 tmp（不污染真实 ~/.qianbi_novel/usage/usage.jsonl）"""
    udir = tmp_path / "usage_home"
    monkeypatch.setattr(m, "DIR", str(udir))
    monkeypatch.setattr(m, "FILE", str(udir / "usage.jsonl"))
    m.reset_watch_state()


@pytest.fixture
def um(tmp_path, monkeypatch):
    """每例重载 app.usage：模块级告警状态（章相位/成本/去重/项目登记）全部归零"""
    import app.usage as m
    m = importlib.reload(m)
    _isolate(m, tmp_path, monkeypatch)
    yield m
    m.set_project("")          # 摘下项目登记，防泄漏进后续用例
    m.reset_watch_state()


def _mk_proj(tmp_path, name="台账书"):
    proj = str(tmp_path / name)
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    return proj


def _ch(um, num, calls):
    """按真实记录路径重放一章：calls = [(phase, tin, tout, sent|None), ...]"""
    um.set_chapter(num)
    for phase, tin, tout, sent in calls:
        um.record(None, _MODEL, "writing", tin, tout, 1.0, phase=phase, sent=sent)


def _pairs(container):
    """异常镜像/state 列表 → (rule, ch) 序列（保发射顺序）"""
    return [(a["rule"], a["ch"]) for a in container]


_ACCT = [("tracking", 5000, 100, None), ("chapter_summary", 6000, 120, None)]


def _mk_proj_cfg():
    return {"connections": [{"id": "t1", "name": "fake", "provider": "custom",
                             "base_url": "http://fake.invalid", "api_key": "sk-t",
                             "model": "fake-model"}],
            "slots": {"writing": "t1", "helper": "t1", "review": "t1"},
            "writing": {"chapter_word_target": 600},
            "gates": {"review_enabled": False},
            "llm": {"max_retries": 0}}


def _mk_orch(proj):
    orch = Orchestrator(proj, _mk_proj_cfg())
    paused = []
    orch.sig_auto_paused.connect(paused.append)
    return orch, paused


class _WdOrch(Orchestrator):
    """run 级剧本：看门狗 auto_pause 后的下一个 checkpoint 按「人点继续→停止」放行，

    防同步调用 run() 的测试挂在暂停等待上（真机语义：暂停本来就该等人）。"""

    def __init__(self, proj, cfg):
        super().__init__(proj, cfg)
        self.auto_pauses = []
        self.finished_codes = []
        self.sig_auto_paused.connect(self.auto_pauses.append)
        self.sig_finished.connect(self.finished_codes.append)

    def checkpoint(self):
        if self._pause.is_set() and self.auto_pauses:
            self.resume()
            self.stop()
        super().checkpoint()


# ---------- G5：回放混合台账序列——触发位置与次数逐章对号 ----------

def test_g5_replay_mixed_ledger_positions_and_counts(um, tmp_path):
    proj = _mk_proj(tmp_path)
    um.set_project(proj, {"usage_alerts": {"chapter_cost_cny": 0.15}})

    # ch1 正常章：正常稿 + 记账齐（成本 ~0.05 元）
    _ch(um, 1, [("prose", 30000, 1400, _MT)] + _ACCT)
    # ch2 顶格稿：prose 精确打满 max_tokens（T3 ch41-44 指纹）+ 40 万级审校输入
    # 把单章成本顶过阈值（~0.19 元 ≥ 0.15）——顶格与成本越限同章各报一次
    _ch(um, 2, [("prose", 15776, _MAXTOK, _MT), ("review", 125576, 1230, None)]
        + _ACCT)
    # ch3 正常章
    _ch(um, 3, [("prose", 30000, 1400, _MT)] + _ACCT)
    # ch4/ch5 只有 prose——记账窗口被杀（T3 相位真空）
    _ch(um, 4, [("prose", 30000, 1400, _MT)])
    _ch(um, 5, [("prose", 30000, 1400, _MT)])
    # ch6 恢复正常
    _ch(um, 6, [("prose", 30000, 1400, _MT)] + _ACCT)

    # 位置与次数逐章对号：顶格 ch2 一次、成本越限 ch2 一次、缺记账行在「章页翻过」
    # 时点名上一章（ch4 在 ch5 开写时、ch5 在 ch6 开写时）；正常章 1/3/6 零误报
    assert _pairs(um._anomalies) == [("prose_maxed_out", 2), ("chapter_cost_over", 2),
                                     ("tracking_missing", 4), ("tracking_missing", 5)]

    # 落账：state.anomalies（新键，validate_state 契约内）
    state = st.load_state(proj)
    assert _pairs(state["anomalies"]) == _pairs(um._anomalies)
    by_rule = {a["rule"]: a for a in state["anomalies"]}
    assert by_rule["prose_maxed_out"]["level"] == "error"
    assert by_rule["prose_maxed_out"]["max_tokens"] == _MAXTOK
    assert by_rule["chapter_cost_over"]["level"] == "warn"
    assert by_rule["chapter_cost_over"]["cost"] >= 0.15
    assert by_rule["tracking_missing"]["level"] == "error"
    assert all(a["ts"] and a["msg"] for a in state["anomalies"])

    # 落事件：项目/追踪/session_events.jsonl 每条异常一行 usage_anomaly
    ev_path = os.path.join(proj, "追踪", "session_events.jsonl")
    with open(ev_path, encoding="utf-8") as f:
        events = [json.loads(ln) for ln in f if ln.strip()]
    assert [e["event"] for e in events] == ["usage_anomaly"] * 4
    assert _pairs(events) == _pairs(um._anomalies)

    # 去重：ch2 的顶格稿再记一笔（同 (rule, ch) 已 flagged）→ 不再重复告警
    _ch(um, 2, [("prose", 15776, _MAXTOK, _MT)])
    assert len(um._anomalies) == 4, "同 (rule, ch) 每进程只报一次"


def test_g5_degrades_to_debug_without_max_tokens_or_usage(um, tmp_path, caplog):
    """降级口径（写明）：渠道不报 max_tokens（sent 缺该键/被剥参/旧调用不传）或
    不回 usage（tout=0）→ 无从裁决顶格，只留 debug 痕迹，不告警不落账"""
    proj = _mk_proj(tmp_path)
    um.set_project(proj, None)
    _ch(um, 1, [("prose", 30000, _MAXTOK, {}),                  # sent 空参（剥参渠道）
                ("tracking", 5000, 100, None)])
    _ch(um, 2, [("prose", 30000, _MAXTOK, None),                # 旧调用不传 sent
                ("tracking", 5000, 100, None)])
    with caplog.at_level(logging.DEBUG, logger="qianbi.usage"):
        um.set_chapter(3)
        um.record(None, _MODEL, "writing", 30000, 0, 1.0,       # 渠道不回 usage
                  phase="prose", sent=_MT)
    assert _pairs(um._anomalies) == [], "缺 max_tokens/usage 不得顶格告警"
    assert st.load_state(proj)["anomalies"] == []
    degraded = [r for r in caplog.records
                if r.levelno == logging.DEBUG and "降级" in r.getMessage()]
    assert degraded, "降级路径必须留 debug 痕迹（不伪装成正常也不伪装成异常）"


def test_g5_replay_from_disk_after_restart_trailing_gap_only(tmp_path, monkeypatch):
    """跨进程：内存清零后从盘上台账回放——chapter_accounted 成立；
    续跑下一章 prose 只对「尾部未愈合断档」翻页告警，已记账章不翻旧账"""
    import app.usage as m1
    m1 = importlib.reload(m1)
    _isolate(m1, tmp_path, monkeypatch)
    m1.set_chapter(1)
    m1.record(None, _MODEL, "writing", 30000, 1400, 1.0, phase="prose", sent=_MT)
    m1.record(None, _MODEL, "writing", 5000, 100, 1.0, phase="tracking")
    m1.set_chapter(2)
    m1.record(None, _MODEL, "writing", 30000, 1400, 1.0, phase="prose", sent=_MT)
    # ——进程重启（重载=内存清零）——
    import app.usage as m2
    m2 = importlib.reload(m2)
    _isolate(m2, tmp_path, monkeypatch)
    assert m2.chapter_accounted(1) is True
    assert m2.chapter_accounted(2) is False
    m2.set_chapter(3)
    m2.record(None, _MODEL, "writing", 30000, 1400, 1.0, phase="prose", sent=_MT)
    assert _pairs(m2._anomalies) == [("tracking_missing", 2)]
    assert m2.chapter_accounted(3) is False


# ---------- G4：相位看门狗——对账判定与 auto_pause 连续性 ----------

def test_g4_watchdog_error_then_two_consecutive_auto_pause(um, tmp_path):
    proj = _mk_proj(tmp_path)
    um.set_project(proj, None)
    orch, paused = _mk_orch(proj)

    # ch1 记账齐（台账记账相位行）→ 放行、零告警、计数归零
    _ch(um, 1, [("prose", 30000, 1400, _MT)] + _ACCT)
    orch._watch_phase_products(1)
    assert not orch.paused and paused == [] and orch._g4_missing_run == 0
    assert st.load_state(proj)["anomalies"] == []

    # ch2 缺记账 → error 落账一次；同章重跑（G9 回退重看）不计「连续」
    orch._watch_phase_products(2)
    orch._watch_phase_products(2)
    assert orch._g4_missing_run == 1 and not orch.paused and paused == []
    assert _pairs(st.load_state(proj)["anomalies"]) == [("bookkeeping_missing", 2)]

    # ch3 仍缺 → 连续第 2 章 → auto_pause（复用闸门暂停机制，信号恰好一次）
    orch._watch_phase_products(3)
    assert orch.paused is True and len(paused) == 1
    assert "连续 2 章" in paused[0]
    assert _pairs(st.load_state(proj)["anomalies"]) == [
        ("bookkeeping_missing", 2), ("bookkeeping_missing", 3)]

    # 恢复：ch4 记账齐 → 计数归零；此后偶发单章缺失不再立刻暂停
    _ch(um, 4, [("prose", 30000, 1400, _MT)] + _ACCT)
    orch._watch_phase_products(4)
    assert orch._g4_missing_run == 0
    orch._watch_phase_products(5)
    assert orch._g4_missing_run == 1 and len(paused) == 1


def test_g4_summary_chain_fallback_counts_as_accounted(um, tmp_path):
    """对账第二路证据：台账行缺失但章节摘要链有本章条目（记账产物本体在）→ 放行"""
    proj = _mk_proj(tmp_path)
    um.set_project(proj, None)
    orch, paused = _mk_orch(proj)
    with open(os.path.join(proj, "追踪", "章节摘要.md"), "a", encoding="utf-8") as f:
        f.write("- 第7章《试炼》：少年通过试炼。\n")
    orch._watch_phase_products(7)
    assert orch._g4_missing_run == 0 and paused == []
    assert st.load_state(proj)["anomalies"] == []
    # 两路皆无 → 缺失计数（error 落账）
    orch._watch_phase_products(8)
    assert orch._g4_missing_run == 1
    assert _pairs(st.load_state(proj)["anomalies"]) == [("bookkeeping_missing", 8)]


def test_g4_run_level_pause_after_two_unaccounted_chapters(um, tmp_path, monkeypatch):
    """run 级接线：章循环收尾（append_history 后、G9 前）调看门狗——

    ch1 记账齐、ch2/ch3 缺记账 → 第 3 章收尾 auto_pause，下一章开写前停在 checkpoint；
    异常按章落 state.anomalies。"""
    proj = _mk_proj(tmp_path, "看门狗书")
    um.set_project(proj, None)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"),
                  "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(os.path.join(proj, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n")
    pj.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n边陲小城。\n")
    for n in (1, 2, 3, 4):
        pj.write_file(pj.get_outline_path(proj, n), f"### 第 {n} 章：节拍\n- 核心事件：x\n")
    state = st.load_state(proj)
    state["total_chapters"] = 4
    st.save_state(proj, state)

    def fake_micro(ctx, num, guidance="", ideas=None):
        pj.write_file(pj.get_chapter_path(proj, num, f"第{num}章"),
                      f"## 第{num}章\n\n" + "正文内容。" * 100)
        if num == 1:   # 只有 ch1 记账齐；ch2/ch3 的收尾记账窗口被杀（T3 场景）
            _ch(um, 1, [("prose", 30000, 1400, _MT)] + _ACCT)
        return {"num": num, "title": f"第{num}章", "words": 600,
                "review_blocking": 0, "status": "pass"}

    monkeypatch.setattr(stages, "chapter_microcycle", fake_micro, raising=True)
    orch = _WdOrch(proj, _mk_proj_cfg())
    orch.run()
    assert len(orch.auto_pauses) == 1 and "连续 2 章" in orch.auto_pauses[0]
    assert _pairs(st.load_state(proj)["anomalies"]) == [
        ("bookkeeping_missing", 2), ("bookkeeping_missing", 3)]
    # 剧本放行后归一收尾：暂停≠崩溃，进度已保存、可续跑
    assert orch.finished_codes == ["stopped"]


# ---------- state 契约：anomalies 键注册 ----------

def test_anomalies_key_registered_in_state_contract():
    assert st.DEFAULT_STATE["anomalies"] == []
    assert st._STATE_KEY_TYPES["anomalies"] is list
    with pytest.raises(st.StateValidationError, match="anomalies"):
        st.validate_state({"anomalies": "corrupt"})
    assert st.validate_state({"anomalies": None})["anomalies"] == []
