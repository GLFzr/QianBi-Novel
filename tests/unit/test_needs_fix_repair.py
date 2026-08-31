# -*- coding: utf-8 -*-
"""待修章节汇总 + 一键修复回归：聚合逻辑 / 状态翻转 / 修复环守卫 / prompt 别名防回归"""
import os

from app import prompts
from app.core import state as st
from app.ui import bridge as bmod


# ---- REVIEW_FIX_PROMPT 别名防回归（曾误别名到 REVISION_TARGETS_PROMPT，
#      导致流水线内修复环永远被「修订计划」守卫丢弃，自动修复失效）----

def test_review_fix_prompt_is_real_fix_prompt():
    assert "直接输出修改后的完整正文" in prompts.REVIEW_FIX_PROMPT
    assert "===REVISIONS===" not in prompts.REVIEW_FIX_PROMPT
    # stages.py 修复环用 {chapter_num}/{findings}/{prose}/{outline_brief}/{core_setting_brief} 组装，必须可 format
    out = prompts.REVIEW_FIX_PROMPT.format(chapter_num=3, findings="- x", prose="正文",
                                           outline_brief="细纲", core_setting_brief="设定")
    assert "第 3 章" in out and "- x" in out and "正文" in out


def test_revision_targets_prompt_still_available():
    assert "===REVISIONS===" in prompts.REVISION_TARGETS_PROMPT


# ---- collect_needs_fix 聚合 ----

def test_collect_needs_fix_pass_only_empty():
    state = {"history": [{"num": 1, "status": "pass"}]}
    assert bmod.collect_needs_fix(state) == []


def test_collect_needs_fix_history_and_findings_merge():
    state = {
        "history": [
            {"num": 1, "title": "甲", "words": 100, "status": "pass"},
            {"num": 2, "title": "乙", "words": 200, "status": "needs_fix"},
        ],
        "review_findings": {
            "2": {"verdict": "REJECT", "blocking": ["x", "y"], "advisory": ["z"], "ts": "T"},
        },
        "chapter_need_human": {"2": "T"},
    }
    r = bmod.collect_needs_fix(state)
    assert len(r) == 1
    e = r[0]
    assert e["num"] == 2 and e["title"] == "乙" and e["blocking"] == 2
    assert e["advisory"] == 1 and e["verdict"] == "REJECT" and e["needHuman"] is True


def test_collect_needs_fix_items_fallback_and_sort():
    # 无 blocking 字段时从 items 的 fail 级兜底；仅 findings（无 history）也入列
    state = {
        "history": [{"num": 5, "title": "戊", "words": 1, "status": "needs_fix"}],
        "review_findings": {
            "3": {"verdict": "REJECT-HARD", "blocking": [], "advisory": [], "ts": "T",
                  "items": [{"dim": "C_FINGER", "level": "fail", "text": "硬伤"},
                            {"dim": "F_HOOK", "level": "marginal", "text": "弱钩"}]},
        },
    }
    r = bmod.collect_needs_fix(state)
    assert [e["num"] for e in r] == [3, 5]
    assert r[0]["blocking"] == 1 and r[0]["verdict"] == "REJECT-HARD"
    assert r[1]["blocking"] == 0   # history 有状态但无登记问题


def test_collect_needs_fix_empty_blocking_skipped():
    state = {"review_findings": {"7": {"verdict": "PASS", "blocking": [], "items": []}}}
    assert bmod.collect_needs_fix(state) == []


# ---- st.update_history_status ----

def test_update_history_status_flips(tmp_path):
    proj = str(tmp_path)
    state = {"history": [{"num": 2, "status": "needs_fix", "title": "乙"}]}
    st.save_state(proj, state)
    s = st.load_state(proj)
    assert st.update_history_status(proj, s, 2, "pass") is True
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_update_history_status_missing_noop(tmp_path):
    proj = str(tmp_path)
    state = {"history": [{"num": 1, "status": "pass"}]}
    st.save_state(proj, state)
    s = st.load_state(proj)
    assert st.update_history_status(proj, s, 9, "pass") is False
    assert st.load_state(proj)["history"][0]["status"] == "pass"


# ---- ChapterRepairWorker._repair_one（假 LLM，不发请求）----

class _FakeClient:
    def __init__(self, answers):
        self.answers = answers   # [(marker, reply), ...] 按顺序匹配 prompt

    def chat_stream(self, prompt, on_chunk=None, **kw):
        for marker, reply in self.answers:
            if marker in prompt:
                return reply
        return ""


class _FakeRouter:
    def __init__(self, answers):
        self._client = _FakeClient(answers)

    def client(self, slot):
        return self._client


def _mk_proj(tmp_path, prose):
    proj = str(tmp_path)
    prose_dir = os.path.join(proj, "正文")
    os.makedirs(prose_dir, exist_ok=True)
    path = os.path.join(prose_dir, "第002章_乙.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prose)
    state = {
        "history": [{"num": 2, "title": "乙", "words": len(prose), "status": "needs_fix"}],
        "review_findings": {"2": {"verdict": "REJECT", "blocking": ["金手指越界"],
                                  "advisory": [], "items": [], "ts": "T"}},
    }
    st.save_state(proj, state)
    return proj, path


FIX_PROMPT_MARK = "阻塞级一致性问题"       # REVIEW_FIX_PROMPT 特有
REVIEW_PROMPT_MARK = "最终审核 Agent"       # FINAL_REVIEW_PROMPT 特有


def test_repair_one_success_flips_status(tmp_path, monkeypatch):
    prose = "# 第2章 乙\n" + "原文内容。" * 120
    fixed = "# 第2章 乙（修）\n" + "修正后内容。" * 120
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, "===VERDICT===\nPASS\n===END==="),
    ]))
    worker = bmod.ChapterRepairWorker({}, "", [2])
    proj, path = _mk_proj(tmp_path, prose)
    worker.proj = proj
    ok, detail = worker._repair_one(2)
    assert ok, detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == fixed
    s = st.load_state(proj)
    assert s["history"][0]["status"] == "pass"
    assert s["review_findings"]["2"]["verdict"] == "PASS"
    from app.core import versions
    assert versions.list_versions(proj, 2), "修复前备份快照应存在"


def test_repair_one_rejects_revision_plan(tmp_path, monkeypatch):
    prose = "# 第2章 乙\n" + "原文内容。" * 120
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg: _FakeRouter([
        (FIX_PROMPT_MARK, "===REVISIONS===\n- [第3段] → 改法"),
    ]))
    worker = bmod.ChapterRepairWorker({}, "", [2])
    proj, path = _mk_proj(tmp_path, prose)
    worker.proj = proj
    ok, detail = worker._repair_one(2)
    assert not ok and "非正文" in detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == prose   # 原稿保留
    assert st.load_state(proj)["history"][0]["status"] == "needs_fix"


def test_repair_one_rollback_when_not_improved(tmp_path, monkeypatch):
    prose = "# 第2章 乙\n" + "原文内容。" * 120
    fixed = "# 第2章 乙（改）\n" + "另一版内容。" * 120
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        # 复扫仍 fail：阻塞不减 → 保留原稿
        (REVIEW_PROMPT_MARK,
         "===C_FINGER=== fail 仍有硬伤【原文引证：\"x\"】\n===VERDICT===\nREJECT\n===END==="),
    ]))
    worker = bmod.ChapterRepairWorker({}, "", [2])
    proj, path = _mk_proj(tmp_path, prose)
    worker.proj = proj
    ok, detail = worker._repair_one(2)
    assert not ok and "未改善" in detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == prose
    assert st.load_state(proj)["history"][0]["status"] == "needs_fix"
