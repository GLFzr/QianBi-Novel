# -*- coding: utf-8 -*-
"""A14 槽位绑定语义（用户裁决 2026-09-13「绝对符合用户选的」）单测

原则：槽位绑定**原样生效**——选了 Flash 一定是 Flash（无静默升级），选了 Pro
就用 Pro（无静默降级/过滤）；「没选 Pro 就绝不是 Pro」由出厂默认（Flash 行）
与清算升级独立开关（audit_strict_tier 缺省关）两道显式闸门保证，而非槽位层的
模型过滤。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v18c_slotlock_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import DEFAULT_CONFIG, DEFAULT_CONNECTIONS, slot_connection  # noqa: E402

PRO_ROW = {"id": "ds-v4-pro", "model": "deepseek-v4-pro", "api_key": "sk"}
FLASH_ROW = {"id": "ds-official-flash", "model": "deepseek-flash", "api_key": "sk"}


def _is_pro_row(row):
    m = str(row.get("model", "")).strip().lower()
    if m:
        return m.endswith("pro")
    return str(row.get("id", "")).strip().lower().endswith("pro")


def test_factory_default_slots_are_flash_not_pro():
    """出厂替新用户选的是 Flash（推荐项）：默认三槽指向的连接非 Pro，且出厂
    清单里有 Flash 行可选。"""
    slots = DEFAULT_CONFIG["slots"]
    for slot, cid in slots.items():
        row = next(c for c in DEFAULT_CONNECTIONS if c["id"] == cid)
        assert not _is_pro_row(row), "出厂槽位 %s 指向 Pro 连接 %s" % (slot, cid)
    assert any(c["id"] == "ds-official-flash" for c in DEFAULT_CONNECTIONS)


def test_slot_honors_explicit_flash_binding():
    """选了 Flash 就一定是 Flash：原样返回，无任何替换。"""
    cfg = {"gates": {}, "slots": {"writing": "ds-official-flash"},
           "connections": [FLASH_ROW, PRO_ROW]}
    assert slot_connection(cfg, "writing").get("id") == "ds-official-flash"


def test_slot_honors_explicit_pro_binding():
    """选了 Pro 就用 Pro：绑定 Pro 行时原样返回（不过滤、不降级）。"""
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro"},
           "connections": [FLASH_ROW, PRO_ROW]}
    assert slot_connection(cfg, "writing").get("id") == "ds-v4-pro"
    cfg["gates"] = {"audit_strict_tier": True}
    assert slot_connection(cfg, "writing").get("id") == "ds-v4-pro"


def test_unbound_review_inherits_writing():
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro", "review": ""},
           "connections": [FLASH_ROW, PRO_ROW]}
    assert slot_connection(cfg, "review").get("id") == "ds-v4-pro"


def test_unbound_everything_falls_back_to_first():
    cfg = {"gates": {}, "slots": {}, "connections": [FLASH_ROW, PRO_ROW]}
    assert slot_connection(cfg, "review").get("id") == "ds-official-flash"


def test_never_pro_without_selection_holds_via_two_gates():
    """「没选 Pro 就绝不是 Pro」的保障结构：出厂 gates 无 audit_strict_tier 键
    （缺省关=不升级），出厂默认槽位非 Pro。"""
    assert not DEFAULT_CONFIG.get("gates", {}).get("audit_strict_tier", False)
