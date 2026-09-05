# -*- coding: utf-8 -*-
"""Prompt 库：核心写作方法论（情绪套路 + 细纲契约）与摘要链提示词"""
from .planning import (
    CORE_SETTING_PROMPT,
    VOLUME_OUTLINE_PROMPT,
    CHAPTER_OUTLINE_PROMPT,
    IDEA_EXPAND_PROMPT,
    BLURB_AND_TAGS_PROMPT,
)
from .writing import (
    PROSE_WRITING_PROMPT,
    ENRICH_PROMPT,
    DESLOP_REWRITE_PROMPT,
    TRIM_PROMPT,
    SELECTION_REWRITE_PROMPT,
    SELECTION_CORE_SETTING_BLOCK,
)
from .memory import (
    TRACKING_UPDATE_PROMPT,
    CHAPTER_SUMMARY_PROMPT,
    GLOBAL_SUMMARY_PROMPT,
    MEMORY_BACKFLOW_PROMPT,
    WORLDBOOK_GEN_PROMPT,
)
from .review import (
    REVIEW_PROMPT,            # v1: 一致性审校
    REVIEW_FIX_PROMPT,
    FINAL_REVIEW_PROMPT,      # v2: 6 维最终审核
    ROOT_CAUSE_PROMPT,        # v2: 根因溯源
    REVISION_TARGETS_PROMPT,  # v2: 定向改稿
    build_upstream_anchors,   # 辅助：行号锚定块
    build_issues_brief,       # 辅助：issues 紧凑化
)
from .co_writing import (
    CO_ROLES,
    CO_DIALOGUE_PROMPT,
    CO_SUMMARIZE_PROMPT,
    CO_PRODUCT_STRUCTURES,
    HANDOFF_MARKER,
    unit_text,
    mode_block_for,
    CW_DRAFT_REQUESTS,
    STYLE_DISCIPLINE,
    CO_UNIT_OUTLINE_PROMPT,
    CO_OUTLINE_REVIEW_PROMPT,
    CO_READBACK_PROMPT,
    CO_SUPERVISOR_PROMPT,
)
from app.presets import (
    STAGE_HINT_KEYS,          # v2: 6 阶段键
    genre_block_for,          # v2: 按环节组装题材预设块
    stage_hint,               # v2: 单环节 hint
)

__all__ = [
    "CORE_SETTING_PROMPT", "VOLUME_OUTLINE_PROMPT", "CHAPTER_OUTLINE_PROMPT",
    "IDEA_EXPAND_PROMPT", "BLURB_AND_TAGS_PROMPT",
    "PROSE_WRITING_PROMPT", "ENRICH_PROMPT", "DESLOP_REWRITE_PROMPT", "TRIM_PROMPT",
    "SELECTION_REWRITE_PROMPT", "SELECTION_CORE_SETTING_BLOCK",
    "TRACKING_UPDATE_PROMPT", "CHAPTER_SUMMARY_PROMPT", "GLOBAL_SUMMARY_PROMPT",
    "MEMORY_BACKFLOW_PROMPT", "WORLDBOOK_GEN_PROMPT",
    "REVIEW_PROMPT", "REVIEW_FIX_PROMPT",
    "FINAL_REVIEW_PROMPT", "ROOT_CAUSE_PROMPT", "REVISION_TARGETS_PROMPT",
    "build_upstream_anchors", "build_issues_brief",
    "CO_ROLES", "CO_DIALOGUE_PROMPT", "CO_SUMMARIZE_PROMPT",
    "CO_PRODUCT_STRUCTURES", "HANDOFF_MARKER",
    "unit_text", "mode_block_for", "CW_DRAFT_REQUESTS", "STYLE_DISCIPLINE",
    "CO_UNIT_OUTLINE_PROMPT", "CO_OUTLINE_REVIEW_PROMPT",
    "CO_READBACK_PROMPT", "CO_SUPERVISOR_PROMPT",
    "STAGE_HINT_KEYS", "genre_block_for", "stage_hint",
]
