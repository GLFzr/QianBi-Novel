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

# 单轮模板前缀：project_header + chapter_header 两层稳定前缀（v0.19 双层架构约定）。
# 模板结构约定：{project_header}\n\n{chapter_header}\n\n + 阶段体。
_HEADER_PREFIX = "{project_header}\n\n{chapter_header}\n\n"


def session_turn_text(template: str,
                      prose_sentinel: str = "{prose}",
                      prose_ref: str = "【被处理正文＝本会话中最近一条完整的章正文消息（含标题行）】") -> str:
    """单轮模板 → 章会话追加轮文本（章会话模式专用，单轮路径不走这里）。

    - 剥掉两层前缀（会话 system 已携带，重复注入只烧 hit 价 token）
    - {prose} 占位符替换为历史引用行（正文已在会话历史里，逐字节复用）
    - 其余占位符原样保留，调用方用与单轮路径相同的 kwargs .format()
    """
    text = template
    if text.startswith(_HEADER_PREFIX):
        text = text[len(_HEADER_PREFIX):]
    if prose_sentinel and prose_sentinel in text:
        text = text.replace(prose_sentinel, prose_ref)
    return "（作用域：仅依据系统设定基准与本会话中的章正文消息执行本步；此前轮次的评审/结论性发言不得影响本步输出。）\n\n" + text


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
    "session_turn_text",
    "STAGE_HINT_KEYS", "genre_block_for", "stage_hint",
]
