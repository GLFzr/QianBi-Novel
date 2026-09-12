# -*- coding: utf-8 -*-
"""v16 P3 修复批次单测：A6 快速道判据 / A11 合并摘要解析 / A10 上下文增量合并。

零 API：A6 走抽出的纯函数；A11 走切分纯函数；A10 走临时项目文件读写。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v16p3_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402

from app.core.stages import (  # noqa: E402
    _review_fast_path_eligible, _split_merged_summary)


# ---------- A6：PASS 快速道判据（5.2 定案：判据链本身正确，bench 是旗标被关） ----------

def _pass_vote(verdict="PASS_WITH_NOTES", **kw):
    v = {"verdict": verdict, "unstructured": False,
         "summary": {"fail": 0}, "blocking": []}
    v.update(kw)
    return v


def test_fast_path_fires_on_clean_first_vote():
    """A6 正向钉：PASS_WITH_NOTES + fail=0 + blocking=[] → 快速道应触发
    （v15 24/24 章满投是 gates 被关，不是判据失效）。"""
    assert _review_fast_path_eligible({"review_pass_fast": True}, 2, _pass_vote()) is True
    assert _review_fast_path_eligible({}, 2, _pass_vote("PASS")) is True   # 产品缺省开


def test_fast_path_holds_on_any_blocking_condition():
    assert _review_fast_path_eligible({"review_pass_fast": True}, 2,
                                      _pass_vote(blocking=["引文不实"])) is False
    assert _review_fast_path_eligible({"review_pass_fast": True}, 2,
                                      _pass_vote(summary={"fail": 1})) is False
    assert _review_fast_path_eligible({"review_pass_fast": True}, 2,
                                      _pass_vote(verdict="FAIL")) is False
    assert _review_fast_path_eligible({"review_pass_fast": True}, 2,
                                      _pass_vote(unstructured=True)) is False


def test_fast_path_needs_two_remaining_and_flag():
    assert _review_fast_path_eligible({"review_pass_fast": True}, 1, _pass_vote()) is False
    assert _review_fast_path_eligible({"review_pass_fast": False}, 2, _pass_vote()) is False


# ---------- A11：合并摘要切分 ----------

def test_split_merged_summary_two_sections():
    raw = ("【章摘要】\n陈默用种子书救下老赵，左腿被撞骨折。\n"
           "【全局摘要】\n陈默获知种子书规则转向自偿，周师傅被袭入	end of 。")
    ch, g = _split_merged_summary(raw)
    assert ch.startswith("陈默用种子书救下老赵")
    assert g.startswith("陈默获知种子书规则")


def test_split_merged_summary_rejects_missing_or_swapped_markers():
    assert _split_merged_summary("没有标记的普通输出") == ("", "")
    assert _split_merged_summary("【全局摘要】\n先出现全局\n【章摘要】\n后出现章") == ("", "")
    assert _split_merged_summary("【章摘要】\n只有一节") == ("", "")


def test_merged_prompt_has_markers_and_session_variant():
    from app import prompts
    assert "【章摘要】" in prompts.CHAPTER_AND_GLOBAL_SUMMARY_PROMPT
    assert "【全局摘要】" in prompts.CHAPTER_AND_GLOBAL_SUMMARY_PROMPT
    assert "{prose_excerpt}" in prompts.CHAPTER_AND_GLOBAL_SUMMARY_PROMPT
    assert "{old_summary}" in prompts.CHAPTER_AND_GLOBAL_SUMMARY_PROMPT


# ---------- A10：上下文增量合并 ----------

def test_tracking_prompt_has_delta_fields():
    from app.prompts.memory import TRACKING_PATCH_PROTOCOL_STATIC, tracking_patch_static_head
    for txt in (TRACKING_PATCH_PROTOCOL_STATIC, tracking_patch_static_head()):
        assert "context_adds" in txt and "context_updates" in txt
        assert '"context": "更新后的写作上下文全文' not in txt


def test_context_delta_merge_applies_adds_and_updates():
    """A10 真函数：match 定位整行替换、adds 追加去重、既有行不丢、标题行不参与。"""
    from app.core.stages import _merge_context_delta
    existing = "# 写作上下文\n\n待处理线索：老周的钥匙下落\n名场面：ch3 天台对峙\n"
    merged = _merge_context_delta(existing, {
        "context_adds": ["名场面：ch9 巷口对视"],
        "context_updates": [{"match": "老周的钥匙下落",
                             "new_line": "待处理线索：老周的钥匙已交给阿莲"}]})
    assert merged is not None
    assert "钥匙已交给阿莲" in merged
    assert "ch9 巷口对视" in merged
    assert "天台对峙" in merged
    assert "钥匙下落" not in merged


def test_context_delta_merge_none_without_delta_fields():
    from app.core.stages import _merge_context_delta
    assert _merge_context_delta("# 写作上下文\n\n旧内容", {}) is None
    assert _merge_context_delta("# 写作上下文\n\n旧内容",
                                {"context": "全量旧字段"}) is None


def test_context_delta_merge_dedups_adds():
    from app.core.stages import _merge_context_delta
    existing = "# 写作上下文\n\n名场面：ch3 天台对峙\n"
    merged = _merge_context_delta(existing, {"context_adds": ["名场面：ch3 天台对峙"]})
    assert merged.count("天台对峙") == 1
