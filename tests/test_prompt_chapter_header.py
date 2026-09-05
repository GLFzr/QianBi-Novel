# -*- coding: utf-8 -*-
"""双层缓存前缀接线护栏：产文/记忆模板必须各带恰好一个 {project_header} 与 {chapter_header}，
且被双层前缀覆盖的旧占位符（core_setting/genre_block/outline_brief 等）不得残留。

chapter_header 由 app/core/shared_prefix.py 组装（同章字节稳定段），本文件只验证
模板接线，不验证其内容组成。
"""

import string

import pytest

from app.prompts.memory import (CHAPTER_SUMMARY_PROMPT, GLOBAL_SUMMARY_PROMPT,
                                TRACKING_UPDATE_PROMPT)
from app.prompts.writing import (DESLOP_REWRITE_PROMPT, ENRICH_PROMPT,
                                 PROSE_WRITING_PROMPT, TRIM_PROMPT,
                                 _PROSE_BODY)

PROJECT_MARK = "PROJECT_HEADER_MARK"
CHAPTER_MARK = "CHAPTER_HEADER_MARK"

TEMPLATES = {
    "PROSE_WRITING_PROMPT": PROSE_WRITING_PROMPT,
    "ENRICH_PROMPT": ENRICH_PROMPT,
    "TRIM_PROMPT": TRIM_PROMPT,
    "DESLOP_REWRITE_PROMPT": DESLOP_REWRITE_PROMPT,
    "TRACKING_UPDATE_PROMPT": TRACKING_UPDATE_PROMPT,
    "CHAPTER_SUMMARY_PROMPT": CHAPTER_SUMMARY_PROMPT,
    "GLOBAL_SUMMARY_PROMPT": GLOBAL_SUMMARY_PROMPT,
}

# 手术单定稿的最小 kwargs 集（.format 用这些就必须成功——被删字段不再是必需）
FORMAT_KWARGS = {
    "PROSE_WRITING_PROMPT": dict(
        chapter_num="7", next_chapter_brief="NEXT_BRIEF_MARK", user_guidance="GUIDANCE_MARK",
        user_ideas="IDEAS_MARK", word_target="3000", tic_blacklist="TICS_MARK",
        used_setpieces="SETPIECES_MARK", style_discipline="STYLE_MARK",
        worldbook_block="WORLDBOOK_MARK", regex_block="REGEX_MARK",
        craft_block="CRAFT_MARK", author_note="AUTHOR_MARK",
    ),
    "ENRICH_PROMPT": dict(
        chapter_num="7", actual="2000", target="3000", must_block="MUST_MARK",
        prose="PROSE_MARK", tic_blacklist="TICS_MARK",
    ),
    "TRIM_PROMPT": dict(
        chapter_num="7", actual="4000", target="3000", cut_pct="25",
        must_block="MUST_MARK", prose="PROSE_MARK", tic_blacklist="TICS_MARK",
    ),
    "DESLOP_REWRITE_PROMPT": dict(
        findings="FINDINGS_MARK", must_block="MUST_MARK", prose="PROSE_MARK",
        tic_blacklist="TICS_MARK",
    ),
    "TRACKING_UPDATE_PROMPT": dict(
        chapter_num="7", roster="ROSTER_MARK", prose="PROSE_MARK",
        character_state="CSTATE_MARK", foreshadow_table="FORESHADOW_MARK",
        timeline="TIMELINE_MARK", old_context="OLDCONTEXT_MARK",
        worldbook="WORLDBOOK_MARK",
    ),
    "CHAPTER_SUMMARY_PROMPT": dict(
        chapter_num="7", title="TITLE_MARK", prose_excerpt="EXCERPT_MARK",
    ),
    "GLOBAL_SUMMARY_PROMPT": dict(
        old_summary="OLDSUM_MARK", chapter_num="7", chapter_summary="CHSUM_MARK",
    ),
}


def _render(name):
    """只喂手术单列出的 kwargs（+ 统一双层前缀），format 抛错即失败。"""
    kwargs = dict(FORMAT_KWARGS[name])
    kwargs["project_header"] = PROJECT_MARK
    kwargs["chapter_header"] = CHAPTER_MARK
    return TEMPLATES[name].format(**kwargs)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_header_placeholders_exactly_once_and_ordered(name):
    t = TEMPLATES[name]
    assert t.count("{project_header}") == 1, name
    assert t.count("{chapter_header}") == 1, name
    assert t.index("{project_header}") < t.index("{chapter_header}"), name
    # chapter_header 之后还有实质内容（不是模板结尾）
    tail = t[t.index("{chapter_header}") + len("{chapter_header}"):]
    assert tail.strip(), name


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_format_with_minimal_kwargs_and_marks(name):
    result = _render(name)
    assert result.count(PROJECT_MARK) == 1, name
    assert result.count(CHAPTER_MARK) == 1, name
    assert result.index(PROJECT_MARK) < result.index(CHAPTER_MARK), name


def test_prose_removed_placeholders_and_sections():
    t = PROSE_WRITING_PROMPT
    for ph in ("{core_setting}", "{genre_block}", "{outline}", "{global_summary}",
               "{recent_summaries}", "{character_states}", "{foreshadows}",
               "{timeline}", "{previous_excerpt}", "{style_sample}"):
        assert ph not in t, ph
    for section in ("## 全书核心设定", "## 题材预设", "## 本章细纲（必须严格遵守",
                    "## 全书剧情锚点", "## 最近三章摘要", "## 本节速记",
                    "### 上一章结尾", "### 上一章开头"):
        assert section not in t, section
    # 保留段抽样：世界书/正则/工艺路线/口头禅黑名单/作者按仍在
    for ph in ("{worldbook_block}", "{regex_block}", "{next_chapter_brief}",
               "{user_guidance}", "{user_ideas}", "{style_discipline}",
               "{used_setpieces}", "{craft_block}", "{tic_blacklist}",
               "{author_note}", "{word_target}", "{chapter_num}"):
        assert ph in t, ph


@pytest.mark.parametrize("name", ["ENRICH_PROMPT", "TRIM_PROMPT", "DESLOP_REWRITE_PROMPT"])
def test_rewrite_templates_dropped_outline_brief(name):
    t = TEMPLATES[name]
    assert "{outline_brief}" not in t
    assert "## 本章细纲" not in t
    # 其余字段保留（DESLOP 原本就没有 {chapter_num}，以 findings 为其特征字段）
    kept = ("{tic_blacklist}", "{must_block}", "{prose}", "{chapter_num}"
            if name != "DESLOP_REWRITE_PROMPT" else "{findings}")
    for ph in kept:
        assert ph in t, (name, ph)


def test_tracking_keeps_full_fields():
    """数据完整性红线：追踪模板的全量字段一个不许丢（chapter_header 的过滤视图/短截断不能替代）"""
    for ph in ("{prose}", "{character_state}", "{foreshadow_table}", "{timeline}",
               "{old_context}", "{roster}", "{worldbook}", "{chapter_num}"):
        assert ph in TRACKING_UPDATE_PROMPT, ph


def test_prose_body_constant():
    assert "{project_header}" not in _PROSE_BODY
    assert "{chapter_header}" not in _PROSE_BODY
    assert PROSE_WRITING_PROMPT == "{project_header}\n\n{chapter_header}\n\n" + _PROSE_BODY


def test_prose_literal_braces_survive_format():
    """输出格式段的 {{章名}} 字面大括号在 format 后应保持单层字面量"""
    result = _render("PROSE_WRITING_PROMPT")
    assert "{{章名}}" not in result
    assert "{章名}" in result
