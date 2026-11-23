# -*- coding: utf-8 -*-
"""记账相位失败必须出声（2026-10-09 深审 断链①）。

现场：49 章长跑书第 8-49 章（42 章）里 `追踪更新失败（不阻断）` 41 次、
`摘要链更新失败` 32 次、`6 维审校调用失败` 61 次（tests_output/long_run_progress.log），
而该书 `pipeline_state.json` 的 84 条 anomalies 里 `tracking_missing` **0 条**——
失败只进日志，既不落异常账也不标待修。这正是 09-26 T3-1 那条「记账静默停摆」链。

两处根因，分别钉住：
  A. `_mc_finalize` 的记账异常出口只 `ctx.log("warn")`，没有任何观测件消费它；
  B. 台账看门狗 `tracking_missing` 的「最近 prose 章」由**跨书全局台账**回放播种
     （`ledger_view.rebuild`），别的书写到第 88 章就把本进程缴械——章号 <88 的书
     永远触发不了。
"""
import pytest

from app.core import ledger_view as lv
from app.core import stages


class _Ctx:
    def __init__(self, proj):
        self.proj = str(proj)
        self.cfg = {"writing": {}}
        self.logs = []

    def log(self, level, msg):
        self.logs.append((level, msg))


def _rules():
    return [a.get("rule") for a in lv.anomalies_snapshot(limit=50)]


# ---------- A. 单次记账失败要落异常账 ----------

def test_tracking_call_failure_is_persisted_as_anomaly(tmp_path, monkeypatch):
    """追踪更新抛错 → 除了日志，还必须经 report_anomaly 这个唯一出口落账。"""
    lv.reset()
    seen = {}
    monkeypatch.setattr(lv, "report_anomaly",
                        lambda rule, level, ch=0, msg="", **f: seen.update(
                            rule=rule, level=level, ch=ch, msg=msg, extra=f) or True)

    stages._report_accounting_failure(_Ctx(tmp_path), 9, "追踪更新", RuntimeError("400"))

    assert seen.get("rule") == "accounting_call_failed", seen
    assert seen.get("ch") == 9 and seen.get("level") == "error", seen
    assert "追踪更新" in seen.get("msg", ""), seen


def test_finalize_failure_sites_all_route_through_the_anomaly_exit(tmp_path):
    """三处记账出口（追踪/摘要链/清算）都必须把失败交给同一个异常出口。

    用 AST 而不是文本计数：把任一 call 删掉或换个名字，本用例就该红。
    """
    import ast
    import inspect

    src = inspect.getsource(stages)
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_mc_finalize")
    calls = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "stages" and node.func.attr == "_report_accounting_failure"):
            calls.append(node)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "_report_accounting_failure"):
            calls.append(node)
    assert len(calls) >= 3, (
        "_mc_finalize 里只有 %d 处记账失败接了异常出口（应≥3：追踪/摘要链/清算）"
        % len(calls))


# ---------- A. 整章记账全失败要标待修 ----------

def test_all_accounting_failed_marks_chapter_need_human(tmp_path):
    """本章所有**尝试过**的记账相位都失败 → 标待修 + error 级异常（不静默定稿）。"""
    from app.core import state as st
    lv.reset()
    ctx = _Ctx(tmp_path)

    stages._accounting_tally(ctx, 9, {"tracking": False, "chapter_summary": False,
                                      "canon_audit": False})

    nh = st.load_state(str(tmp_path)).get("chapter_need_human") or {}
    assert "9" in nh, "全章记账失败却没有标待修：%s" % nh
    assert any("净" in m or "记账" in m for lvl, m in ctx.logs if lvl == "error"), ctx.logs


def test_partial_accounting_success_does_not_mark_need_human(tmp_path):
    """只要有一个记账相位真的写成功，就不 escalate（但失败本身已在 A 里落账）。"""
    from app.core import state as st
    lv.reset()
    ctx = _Ctx(tmp_path)

    stages._accounting_tally(ctx, 9, {"tracking": True, "chapter_summary": False})

    nh = st.load_state(str(tmp_path)).get("chapter_need_human") or {}
    assert "9" not in nh, nh


def test_unattempted_phases_are_not_counted_as_failures(tmp_path):
    """没尝试过的相位（None/缺键）不能算失败——否则关掉某相位就人人待修。"""
    from app.core import state as st
    lv.reset()
    ctx = _Ctx(tmp_path)

    stages._accounting_tally(ctx, 9, {"tracking": None, "chapter_summary": None,
                                      "canon_audit": True})

    nh = st.load_state(str(tmp_path)).get("chapter_need_human") or {}
    assert "9" not in nh, nh
    stages._accounting_tally(ctx, 10, {"tracking": None, "chapter_summary": None})
    nh = st.load_state(str(tmp_path)).get("chapter_need_human") or {}
    assert "10" not in nh, "一个相位都没尝试时也标了待修"


# ---------- B. 看门狗不能被别的书的历史缴械 ----------

def test_page_flip_watchdog_not_disarmed_by_other_books_history():
    """别的书写到第 88 章，不能让我这本从第 5 章起就永远不报「记账缺失」。"""
    lv.reset()
    lv.set_project("")                       # 纯内存：规则照评，不落任何项目状态
    # 盘上台账回放：来自另一本书的高章号历史行（本进程从未写过这些章）
    lv.rebuild({"ch": 88, "phase": "prose", "model": "m", "in": 1000, "out": 500})

    hits0 = lv.observe({"ch": 5, "phase": "prose", "model": "m", "in": 1000, "out": 500})
    hits = lv.observe({"ch": 6, "phase": "prose", "model": "m", "in": 1000, "out": 500})

    assert any(h.get("rule") == "tracking_missing" and h.get("ch") == 5 for h in hits), (
        "第 5 章正文落库后章页翻到第 6 章，仍没有任何一章等到记账相位行，"
        "tracking_missing 却没报（hits=%s）" % hits)
    # 负向：本进程从没写过的章号（这里是别的书回放进来的 88）不许报警——
    # 报警口径只能建立在「本进程真实观测到的章页翻动」上。
    assert not any(h.get("rule") == "tracking_missing" for h in hits0), (
        "第一章开写时就报出记账缺口，且缺口章号来自跨书回放：%s" % hits0)
    assert all(h.get("ch") in (5, 6) for h in list(hits0) + list(hits)), (
        "跨书回放的历史章被当成本进程的记账缺口：%s %s" % (hits0, hits))


def test_page_flip_watchdog_stays_quiet_when_accounting_ran():
    """对照：上一章确实有记账相位行时不误报。"""
    lv.reset()
    lv.set_project("")
    lv.observe({"ch": 5, "phase": "prose", "model": "m", "in": 10, "out": 5})
    lv.observe({"ch": 5, "phase": "tracking", "model": "m", "in": 10, "out": 5})
    hits = lv.observe({"ch": 6, "phase": "prose", "model": "m", "in": 10, "out": 5})
    assert not any(h.get("rule") == "tracking_missing" for h in hits), hits


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
