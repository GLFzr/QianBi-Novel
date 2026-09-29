# -*- coding: utf-8 -*-
"""C39 成本面板单测：usage 三层聚合（纯读台账）+ CostPanelController 数据形状
+ append_history 章级成本落行 + 「盲区优先于 0」（验收②）。

口径（docs/落地计划附录A 卡 C39 / w4_model_orch §3 方案 B）：
- today = ymd==今天、month = ymd 前缀==本月（全部行）；book = ch>0（台账无
  project 列，章级行是唯一诚实的本书代理，多书共台账时为合计——面板文案写明）；
- 范围内没有任何行 → known=False → UI 显示「盲区」，不许伪装成 ¥0.00；
- 费率线性 ⇒ 逐行累计与 summary 的按模型聚合同值（flash 档 1.0/2.0 元每百万）；
- append_history 章级成本与台账逐章求和对账 ±1 分（验收③）。
"""
import datetime
import importlib
import json
import os

import pytest

from app import project
from app.core import state as st


TODAY = datetime.date.today().strftime("%Y-%m-%d")
MONTH_PREFIX = TODAY[:7]
# 当月里必不等于今天的一天（今天 1 号时用 2 号，其余用 1 号）
MONTH_OTHER = MONTH_PREFIX + ("-02" if TODAY.endswith("-01") else "-01")


def _fresh_usage(tmp_path, monkeypatch):
    """重载 app.usage 并把落盘路径指到 tmp_path（隔离真实 ~/.qianbi_novel）"""
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    return um


def _row(ymd, ts, ch=0, model="deepseek-v4-flash", tin=0, tout=0,
         hit=0, miss=0, phase="prose"):
    return {"ts": ts, "ymd": ymd, "model": model, "slot": "writing",
            "in": tin, "out": tout, "latency": 0.5, "hit": hit, "miss": miss,
            "phase": phase, "ch": ch}


def _write_ledger(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# 台账样本：A=今天章级行（全盲输入），B=今天章外行（也未报缓存），
# C=当月他日章外行，D=2020 年章级行（mini 档、命中可算），E=2020 年章外行。
# flash/mini 档费率都是进 1.0、出 2.0（元/百万）。
def _sample_rows():
    return [
        _row(TODAY, TODAY + " 10:00:00", ch=1, tin=1_000_000, tout=500_000),          # 2.0 元
        _row(TODAY, TODAY + " 10:01:00", ch=0, tin=100_000),                          # 0.1 元
        _row(MONTH_OTHER, MONTH_OTHER + " 09:00:00", ch=0, tin=200_000),              # 0.2 元
        _row("2020-01-02", "2020-01-02 09:00:00", ch=2, model="m-mini",
             tin=2_000_000, tout=1_000_000, hit=1_500_000, miss=500_000),             # 4.0 元
        _row("2020-01-03", "2020-01-03 09:00:00", ch=0, tin=999_999),
    ]


# ---------- 验收①口径：三层聚合正确性 ----------

def test_three_layer_aggregation(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, _sample_rows())
    s = um.book_scope_summary({})
    today, book, month = s["today"], s["book"], s["month"]
    # today：A+B 两行，2.0+0.1；全盲输入 → 命中率 None（不许伪装 0%）
    assert today["known"] and today["calls"] == 2
    assert today["cost"] == pytest.approx(2.1, abs=1e-4)
    assert today["in"] == 1_100_000 and today["out"] == 500_000
    assert today["hit_rate"] is None and today["blind"] == 1_100_000
    # book：A+D 两章级行（E 章外不入），2.0+4.0；命中率只算已知行 1.5M/(1.5M+0.5M)
    assert book["known"] and book["calls"] == 2
    assert book["cost"] == pytest.approx(6.0, abs=1e-4)
    assert book["in"] == 3_000_000 and book["out"] == 1_500_000
    assert book["hit"] == 1_500_000 and book["miss"] == 500_000
    assert book["hit_rate"] == pytest.approx(0.75, abs=1e-4)
    assert book["blind"] == 1_000_000
    # month：A+B+C 三行（2020 年不进本月）
    assert month["known"] and month["calls"] == 3
    assert month["cost"] == pytest.approx(2.3, abs=1e-4)
    # 费率线性：book 逐行累计 == 按模型聚合同值（与 summary() 口径对得上）
    assert book["cost"] == pytest.approx(2.0 + 4.0, abs=1e-6)


def test_since_ts_windows_book_layer(tmp_path, monkeypatch):
    """since_ts 是 book 层的会话窗口（w4 §3 B 原始口径）：卡掉历史章级行"""
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, _sample_rows())
    s = um.book_scope_summary({}, since_ts="2026-01-01")
    assert s["book"]["calls"] == 1 and s["book"]["cost"] == pytest.approx(2.0, abs=1e-4)
    s2 = um.book_scope_summary({}, since_ts="2099-01-01")
    assert s2["book"]["known"] is False, "窗口内无行必须是盲区，不是 0"
    # today/month 不受会话窗口约束
    assert s["today"]["calls"] == 2 and s["month"]["calls"] == 3


def test_bad_rows_tolerated(tmp_path, monkeypatch):
    """坏行跳过、脏数字按 0 兜底、脏章号按章外计——整表扫描绝不炸（与 _load 同容忍度）"""
    um = _fresh_usage(tmp_path, monkeypatch)
    rows = [
        "not-json-at-all",
        json.dumps(_row(TODAY, TODAY + " 10:00:00", ch="bad", tin=50_000)),
        json.dumps({"ts": TODAY + " 10:01:00", "ymd": TODAY, "model": "x",
                    "slot": "s", "in": "oops", "out": 1, "ch": 3}),
        json.dumps(_row(TODAY, TODAY + " 10:02:00", ch=4, tin=10_000, tout=1_000)),
    ]
    with open(um.FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    s = um.book_scope_summary({})
    assert s["today"]["calls"] == 3          # 坏 JSON 跳过，三条好行入账（脏数字按 0）
    assert s["book"]["calls"] == 2           # ch="bad" 按章外计，ch=3/ch=4 入书层
    assert s["book"]["cost"] == pytest.approx(0.012002, abs=1e-5)
    assert [c["ch"] for c in um.chapter_costs({})] == [4, 3]


# ---------- 验收②：断网/空台账 → 盲区而非 0 ----------

def test_missing_ledger_is_blind_not_zero(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    s = um.book_scope_summary({}, path=str(tmp_path / "nope.jsonl"))
    for key in ("today", "book", "month"):
        assert s[key]["known"] is False
        assert s[key]["hit_rate"] is None
        assert s[key]["cost"] == 0.0 and s[key]["calls"] == 0
    assert um.chapter_costs({}, path=str(tmp_path / "nope.jsonl")) == []


def test_empty_ledger_is_blind_not_zero(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    open(um.FILE, "w").close()
    s = um.book_scope_summary({})
    assert all(s[k]["known"] is False for k in ("today", "book", "month"))
    assert um.chapter_costs({}) == []


def test_chapter_cost_unknown_returns_none_not_zero(tmp_path, monkeypatch):
    """没记账的章返回 None——「缺字段」语义，append_history 据此不落 cost 键"""
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, _sample_rows())
    assert um.chapter_cost(1) == pytest.approx(2.0, abs=1e-4)
    assert um.chapter_cost(99) is None


# ---------- 章级成本列表 ----------

def test_chapter_costs_desc_order_and_limit(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    rows = [_row(TODAY, f"{TODAY} 10:{i:02d}:00", ch=i, tin=1_000_000, tout=0)
            for i in range(1, 13)]                      # 每章 1.0 元
    _write_ledger(um.FILE, rows)
    chs = um.chapter_costs({}, limit=10)
    assert [c["ch"] for c in chs] == list(range(12, 2, -1))   # 最近十章，号降序
    for c in chs:
        assert c["cost"] == pytest.approx(1.0, abs=1e-4)
        assert c["calls"] == 1 and c["in"] == 1_000_000
    assert len(um.chapter_costs({}, limit=3)) == 3


def test_chapter_costs_skips_non_chapter_rows(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, _sample_rows())
    chs = um.chapter_costs({})
    assert [c["ch"] for c in chs] == [2, 1]
    assert chs[0]["cost"] == pytest.approx(4.0, abs=1e-4)     # 2020 年的 ch2 也算章级行


# ---------- append_history 章级成本落行（验收③ ±1 分）----------

def _sandbox_proj(tmp_path, monkeypatch, name="成本书"):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return project.create_project(os.path.join(str(tmp_path), "books"), name)


def test_append_history_carries_chapter_cost(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, [
        _row(TODAY, TODAY + " 10:00:00", ch=3, tin=1_500_000, tout=250_000,
             hit=1_200_000, miss=300_000),              # 1.5 + 0.5 = 2.0 元
        _row(TODAY, TODAY + " 10:01:00", ch=3, tin=100_000, tout=25_000,
             hit=80_000, miss=20_000),                  # 0.1 + 0.05 = 0.15 元
    ])
    proj = _sandbox_proj(tmp_path, monkeypatch)
    st.append_history(proj, {"history": []}, {"num": 3, "title": "第三章"})
    row = next(h for h in st.load_state(proj)["history"] if h["num"] == 3)
    assert "cost" in row, "有台账行的章必须带 cost"
    assert abs(row["cost"] - 2.15) <= 0.01, "章列成本与台账求和对账 ±1 分"


def test_append_history_omits_cost_when_unaccounted(tmp_path, monkeypatch):
    """台账无该章任何行 → 不落 cost 键（「没记账」≠ 0）"""
    um = _fresh_usage(tmp_path, monkeypatch)
    proj = _sandbox_proj(tmp_path, monkeypatch, "盲章书")
    st.append_history(proj, {"history": []}, {"num": 7, "title": "第七章"})
    row = next(h for h in st.load_state(proj)["history"] if h["num"] == 7)
    assert "cost" not in row


def test_append_history_keeps_caller_cost(tmp_path, monkeypatch):
    """调用方已带 cost（如回填/重放路径）时不覆盖"""
    um = _fresh_usage(tmp_path, monkeypatch)
    _write_ledger(um.FILE, [_row(TODAY, TODAY + " 10:00:00", ch=3,
                                 tin=1_000_000, tout=0)])
    proj = _sandbox_proj(tmp_path, monkeypatch, "保产书")
    st.append_history(proj, {"history": []}, {"num": 3, "title": "x", "cost": 9.99})
    row = next(h for h in st.load_state(proj)["history"] if h["num"] == 3)
    assert row["cost"] == 9.99


# ---------- controller：数据形状 + 盲区文案 + 告警来源 ----------

class _FakeBridge:
    """controller 只吃 cfg/proj 两个属性（照 test_model_policy 先例，不起 Qt 应用）"""
    def __init__(self, cfg=None, proj=""):
        self.cfg = cfg if cfg is not None else {}
        self.proj = proj


def _ctl(tmp_path, monkeypatch, ledger_rows=None, cfg=None, proj=""):
    um = _fresh_usage(tmp_path, monkeypatch)
    if ledger_rows is not None:
        _write_ledger(um.FILE, ledger_rows)
    from app.ui.bridge import CostPanelController
    return CostPanelController(_FakeBridge(cfg, proj)), um


def test_controller_data_shapes(tmp_path, monkeypatch):
    ctl, _um = _ctl(tmp_path, monkeypatch, _sample_rows())
    ctl.refresh()
    cards = {c["key"]: c for c in ctl.layerCards}
    assert set(cards) == {"today", "book", "month"}
    assert cards["today"]["label"] == "今日" and cards["book"]["label"] == "本书" \
        and cards["month"]["label"] == "本月"
    assert cards["today"]["cost"] == "¥2.1000"
    assert "命中" in cards["book"]["detail"] and "盲区" in cards["book"]["detail"]
    assert "命中率盲区" in cards["today"]["detail"], "命中率不可知不许伪装成 0%"
    chs = ctl.chapterList
    assert [c["ch"] for c in chs] == [2, 1]
    assert chs[1]["cost"] == "¥2.0000" and "笔" in chs[1]["detail"]
    assert ctl.generated, "刷新时间戳非空（UI 可显示更新于）"


def test_controller_blind_display_on_empty_ledger(tmp_path, monkeypatch):
    """验收②：空台账 → 三层数字与章列都落「盲区」，绝不显示 ¥0.00"""
    ctl, _um = _ctl(tmp_path, monkeypatch, ledger_rows=[])
    ctl.refresh()
    for card in ctl.layerCards:
        assert card["cost"] == "盲区"
        assert "盲区" in card["detail"]
        assert "¥" not in card["cost"]
    assert ctl.chapterList == []


def test_controller_blind_display_on_missing_file(tmp_path, monkeypatch):
    ctl, _um = _ctl(tmp_path, monkeypatch, ledger_rows=None)   # 文件压根不存在
    ctl.refresh()
    assert all(c["cost"] == "盲区" for c in ctl.layerCards)
    assert ctl.chapterList == []


def test_controller_anomalies_prefers_project_state(tmp_path, monkeypatch):
    ctl, _um = _ctl(tmp_path, monkeypatch, _sample_rows(), proj="某书")
    from app.ui import bridge as bmod
    entry = {"ts": "2026-09-29 10:00:00", "rule": "prose_maxed_out", "ch": 41,
             "level": "error", "msg": "顶格"}
    monkeypatch.setattr(bmod.st, "load_state", lambda proj: {"anomalies": [entry]})
    ctl.refresh()
    a = ctl.anomalyList
    assert len(a) == 1 and a[0]["rule"] == "prose_maxed_out"
    assert a[0]["ch"] == 41 and a[0]["level"] == "error"


def test_controller_anomalies_falls_back_to_mirror(tmp_path, monkeypatch):
    """无项目（共写/未登记）时退回台账内存镜像——进程内告警也该看得见"""
    ctl, um = _ctl(tmp_path, monkeypatch, _sample_rows(), proj="")
    um.report_anomaly("chapter_cost_over", "warn", ch=7, msg="越限")
    ctl.refresh()
    a = ctl.anomalyList
    assert a and a[-1]["rule"] == "chapter_cost_over" and a[-1]["ch"] == 7


def test_controller_anomaly_list_is_copy(tmp_path, monkeypatch):
    """只读契约：面板拿到的是副本，改它不许污染账本"""
    ctl, um = _ctl(tmp_path, monkeypatch, _sample_rows(), proj="")
    um.report_anomaly("r", "warn", ch=1, msg="m")
    ctl.refresh()
    before = len(um.anomalies_snapshot(100))
    lst = ctl.anomalyList
    if isinstance(lst, list):
        lst.append("junk")
    assert len(um.anomalies_snapshot(100)) == before


# ---------- 文案函数（staticmethod，无 Qt 依赖）----------

def test_cost_text_and_detail_text_formats():
    from app.ui.bridge import CostPanelController as C
    assert C.cost_text(None) == "盲区"
    assert C.cost_text({}) == "盲区"
    assert C.cost_text({"known": False, "cost": 3.0}) == "盲区"
    assert C.cost_text({"known": True, "cost": 0.0312}) == "¥0.0312"
    assert C.cost_text({"known": True, "cost": 0}) == "¥0.0000"
    assert "盲区" in C.detail_text(None)
    d = C.detail_text({"known": True, "in": 1_500_000, "out": 45_000,
                       "hit_rate": 0.755, "blind": 100, "calls": 12})
    assert d == "入 1.50M · 出 45.0k · 命中 75.5% · 盲区 100 · 12 笔"
    d2 = C.detail_text({"known": True, "in": 800, "out": 0,
                        "hit_rate": None, "blind": 0, "calls": 1})
    assert "命中率盲区" in d2 and "800" in d2
    assert C.chapter_text({"calls": 0}) == "盲区"
    assert C.chapter_text(None) == "盲区"


def test_chapter_text_known_row():
    from app.ui.bridge import CostPanelController as C
    t = C.chapter_text({"known": True, "cost": 0.5, "in": 1_000_000, "out": 250_000,
                        "hit_rate": 0.5, "blind": 0, "calls": 9})
    assert t.startswith("¥0.5000 ·") and "9 笔" in t
