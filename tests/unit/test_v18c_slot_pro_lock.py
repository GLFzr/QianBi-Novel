# -*- coding: utf-8 -*-
"""A14 全局零 Pro 闸门（slot_connection 层）单测

用户裁决 2026-09-13：开关关（缺省）= 程序**根本不调用** DeepSeek-V4-Pro——
不仅是清算严格档（canon_audit._strict_conn），槽位路由的三条回退路径也必须
拒绝 Pro 连接；无可用非 Pro 连接时返回空（上层报「未绑定」），绝不静默改用 Pro。
出厂默认槽位必须指向非 Pro 行（新装用户开箱即 flash）。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v18c_slotlock_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import (  # noqa: E402
    DEFAULT_CONFIG, DEFAULT_CONNECTIONS, _is_pro_conn, slot_connection)

PRO_ROW = {"id": "ds-v4-pro", "model": "deepseek-v4-pro", "api_key": "sk"}
FLASH_ROW = {"id": "ds-official-flash", "model": "deepseek-flash", "api_key": "sk"}


def test_factory_default_slots_are_not_pro():
    """出厂零 Pro：默认三槽指向的连接不得是 Pro（按 model 或 id 判）。"""
    slots = DEFAULT_CONFIG["slots"]
    for slot, cid in slots.items():
        row = next(c for c in DEFAULT_CONNECTIONS if c["id"] == cid)
        assert not _is_pro_conn(row), "出厂槽位 %s 指向 Pro 连接 %s" % (slot, cid)
    # 出厂连接清单里必须存在 flash 行（新装用户开箱即有非 Pro 可选）
    assert any(c["id"] == "ds-official-flash" for c in DEFAULT_CONNECTIONS)


def test_lock_skips_pro_slot_and_falls_back_to_flash():
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro", "helper": "ds-v4-pro",
                                  "review": "ds-v4-pro"},
           "connections": [PRO_ROW, FLASH_ROW]}
    for slot in ("writing", "helper", "review"):
        got = slot_connection(cfg, slot)
        assert got.get("id") == "ds-official-flash"   # 锁拒绝 Pro，回退 flash


def test_lock_returns_empty_when_only_pro_exists():
    """无可用非 Pro 连接：返回空（上层报未绑定），绝不静默改用 Pro。"""
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro"},
           "connections": [PRO_ROW]}
    assert slot_connection(cfg, "writing") == {}


def test_switch_on_restores_pro_routing():
    cfg = {"gates": {"audit_strict_tier": True},
           "slots": {"writing": "ds-v4-pro"},
           "connections": [PRO_ROW, FLASH_ROW]}
    assert slot_connection(cfg, "writing").get("id") == "ds-v4-pro"


def test_lock_catches_empty_model_pro_id_row():
    """出厂行 model 留空：id 以 pro 结尾同样被锁（新装用户填 Key 即用的形态）。"""
    blank_pro = {"id": "ds-v4-pro", "model": "", "api_key": "sk"}
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro"},
           "connections": [blank_pro, FLASH_ROW]}
    assert slot_connection(cfg, "writing").get("id") == "ds-official-flash"


def test_lock_falls_through_writing_slot_backstop():
    """review 槽未绑定 → 旧逻辑回退写作槽；写作槽也是 Pro 时继续回退到 flash。"""
    cfg = {"gates": {}, "slots": {"writing": "ds-v4-pro", "review": ""},
           "connections": [PRO_ROW, FLASH_ROW]}
    assert slot_connection(cfg, "review").get("id") == "ds-official-flash"
