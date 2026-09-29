# -*- coding: utf-8 -*-
"""任务槽位与闸门策略常量（零依赖基础层）

B2a 拆环（0.22.0 试验版 C10）：这些常量原在 app/config.py，被 core 层
（canon_audit/gates/stages）与 llm 层（router）反向引用，形成 core->app-top
上行边。下沉到本模块后 core/llm 改从 slots 导入，config 保留同名 re-export
兼容旧消费方（bridge/selftest/update_* 等不动）。

本模块不许 import 任何 app 内其他模块（零依赖是它的存在理由）。
"""
# ---- 任务槽位 ----
SLOT_WRITING = "writing"   # 核心设定/大纲/草稿/去味改写/扩写
SLOT_HELPER = "helper"     # 细纲/章节摘要/全局摘要/追踪更新/检索关键词
SLOT_REVIEW = "review"     # 一致性审校
SLOT_ORDER = [SLOT_WRITING, SLOT_HELPER, SLOT_REVIEW]
SLOT_LABELS = {SLOT_WRITING: "写作槽", SLOT_HELPER: "辅助槽", SLOT_REVIEW: "审校槽"}

# ---- 质量闸门策略 ----
GATE_STRICT = "strict"              # 自动修复 1 次仍失败 → 暂停等人
GATE_MARK_CONTINUE = "mark_continue"  # 修复失败 → 标待修继续写（默认）


# ---- 槽位→连接解析（纯函数；原 config.find_connection / config.slot_connection）----

def find_connection(cfg: dict, conn_id: str) -> dict:
    for c in cfg.get("connections", []):
        if c.get("id") == conn_id:
            return c
    return {}


def slot_connection(cfg: dict, slot: str) -> dict:
    """取某槽位当前绑定的连接；未绑定时回退写作槽，再回退第一条。

    A14 语义（用户裁决 2026-09-13「绝对符合用户选的」）：本函数**原样返回用户
    绑定的连接**——选了 Flash 就是 Flash，选了 Pro 就用 Pro，不做任何模型过滤、
    静默换型或降级替换。「没选 Pro 就绝不是 Pro」由两道显式闸门保证：
    ①出厂默认槽位指向 Flash（新用户未做选择时，替选推荐项而非 Pro）；
    ②清算自动升级由 gates.audit_strict_tier 独立把关（缺省关=不升级）。"""
    conn = find_connection(cfg, cfg.get("slots", {}).get(slot, ""))
    if not conn:
        conn = find_connection(cfg, cfg.get("slots", {}).get(SLOT_WRITING, ""))
    if not conn and cfg.get("connections"):
        conn = cfg["connections"][0]
    return conn
