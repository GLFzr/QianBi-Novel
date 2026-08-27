# -*- coding: utf-8 -*-
"""v2 题材预设单测：覆盖 10 套 v2 加载、stage_hints、genre_block_for 6 阶段注入、v1→v2 自动迁移

- fake home 隔离用户配置（不污染 ~/.qianbi_novel/）
- 无 LLM 调用，纯函数 + JSON 加载
"""
import os
import sys
import json
import tempfile
import shutil

# 隔离用户配置
_FH = tempfile.mkdtemp(prefix="qbn_test_preset_v2_")
os.environ["USERPROFILE"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.presets import (
    list_presets, load_preset, genre_block, genre_block_for,
    stage_hint, STAGE_HINT_KEYS, _STAGE_SHARED_FIELDS,
    _migrate_v1_to_v2,
)

# ---- 测试 1：10 套 v2 预设都能加载 ----

def test_list_presets_count():
    """应至少有 11 项：1 通用占位 + 10 内置 v2 预设"""
    ps = list_presets()
    assert len(ps) >= 11, f"expect ≥11 presets, got {len(ps)}"
    ids = [p["id"] for p in ps]
    assert "" in ids, "missing 通用占位"
    for pid in ("cosmic_horror", "fairy_tale_lite", "game_esports",
                "historical_intrigue", "infinite_flow", "mystery_horror",
                "scifi_apocalypse", "urban_destiny", "urban_superpower",
                "cultivation"):
        assert pid in ids, f"missing preset: {pid}"
    print(f"  ✓ list_presets: {len(ps)} presets (1 通用 + 10 内置)")


def test_each_v2_preset_has_stage_hints():
    """每个内置预设必须有 stage_hints（6 键全）"""
    for pid in ("cosmic_horror", "fairy_tale_lite", "game_esports",
                "historical_intrigue", "infinite_flow", "mystery_horror",
                "scifi_apocalypse", "urban_destiny", "urban_superpower",
                "cultivation"):
        p = load_preset(pid)
        assert p, f"{pid} load failed"
        assert p.get("version", 1) >= 2, f"{pid} not v2: {p.get('version')}"
        hints = p.get("stage_hints") or {}
        for stage_key in dict(STAGE_HINT_KEYS):
            assert stage_key in hints, f"{pid} missing stage_hints[{stage_key}]"
            val = hints[stage_key]
            assert isinstance(val, str) and len(val) > 50, \
                f"{pid}.{stage_key} too short: {len(val)} chars"
    print(f"  ✓ all 10 v2 presets have complete stage_hints (6 keys each)")


def test_each_v2_preset_has_genre():
    """v2 预设必须有 genre 字段"""
    for pid in ("cosmic_horror", "cultivation", "urban_destiny"):
        p = load_preset(pid)
        assert p.get("genre"), f"{pid} missing genre"
    print(f"  ✓ v2 presets have genre field")


# ---- 测试 2：stage_hint 单环节 ----

def test_stage_hint_returns_hints():
    """stage_hint 返回非空字符串"""
    h = stage_hint("urban_destiny", "prose")
    assert h and "正文环节特化" in h
    assert len(h) > 100
    print(f"  ✓ stage_hint(urban_destiny, prose) length={len(h)}")


def test_stage_hint_empty_for_invalid():
    """无效 stage / 空 preset_id 返回空串"""
    assert stage_hint("", "prose") == ""
    assert stage_hint("urban_destiny", "invalid_stage") == ""
    assert stage_hint("nonexistent_id", "prose") == ""
    print(f"  ✓ stage_hint returns '' for invalid input")


# ---- 测试 3：genre_block_for 6 阶段注入 ----

def test_genre_block_for_all_stages():
    """6 阶段都能注入非空字符串"""
    for stage in dict(STAGE_HINT_KEYS):
        gb = genre_block_for("urban_destiny", stage)
        assert gb, f"empty genre_block for stage={stage}"
        assert "都市悬疑·改命流" in gb, f"preset name not in block: {gb[:80]}"
    print(f"  ✓ genre_block_for: 6 阶段全部注入成功")


def test_genre_block_for_includes_shared_fields():
    """prose 阶段应包含 style_hint + world_rules + taboos"""
    gb = genre_block_for("urban_destiny", "prose")
    assert "文风补充" in gb, f"missing style_hint label: {gb[:200]}"
    assert "题材世界规则" in gb, f"missing world_rules label"
    assert "题材禁忌" in gb, f"missing taboos label"
    print(f"  ✓ genre_block_for(prose) 包含 style_hint/world_rules/taboos")


def test_genre_block_for_review_no_shared():
    """review 阶段 _STAGE_SHARED_FIELDS == []，应只含 stage hint"""
    gb = genre_block_for("urban_destiny", "review")
    assert "审校环节特化" in gb
    # review 阶段无共享字段，只有 hint
    shared = _STAGE_SHARED_FIELDS["review"]
    assert shared == []
    print(f"  ✓ genre_block_for(review) 只含 stage hint，无共享字段")


# ---- 测试 4：v1 → v2 自动迁移 ----

def test_v1_migration():
    """v1 预设（无 stage_hints）自动迁移到 v2"""
    v1 = {
        "id": "test_v1_preset",
        "name": "测试 v1 预设",
        "description": "test",
        "version": 1,
        "style_hint": "冷峻克制短句",
        "world_rules": "金手指遵守对等代价",
    }
    migrated = _migrate_v1_to_v2(v1)
    assert migrated.get("version") == 2
    assert "stage_hints" in migrated
    assert "prose" in migrated["stage_hints"]
    assert "冷峻克制短句" in migrated["stage_hints"]["prose"]
    assert migrated.get("_v2_migrated") is True
    print(f"  ✓ _migrate_v1_to_v2: 正确把 style_hint 塞入 stage_hints['prose']")


def test_v1_migration_no_double_migrate():
    """v2 预设不应再迁移"""
    v2 = {"id": "x", "name": "y", "version": 2, "stage_hints": {"prose": "ok"}}
    migrated = _migrate_v1_to_v2(v2)
    assert migrated.get("version") == 2
    assert migrated.get("stage_hints", {}).get("prose") == "ok"
    # 应是同一对象（不复制）
    assert migrated is v2
    print(f"  ✓ _migrate_v1_to_v2: v2 预设不重复迁移")


def test_genre_block_fallback_v1():
    """v1 预设（无 stage_hints）走 genre_block 全量注入（向后兼容）"""
    # 直接测 genre_block（v1 路径）
    p = load_preset("urban_destiny")
    # v2 路径有 stage_hints，走 genre_block_for；用空 stage 模拟
    gb = genre_block("urban_destiny")
    assert "都市悬疑·改命流" in gb
    assert "文风补充" in gb  # PRESET_FIELDS 第一个
    assert "题材世界规则" in gb
    assert "题材禁忌" in gb
    print(f"  ✓ genre_block fallback: v1 路径正确注入 6 块 PRESET_FIELDS")


# ---- 测试 5：grow_block 仍然可用 ----

def test_grow_block_still_works():
    """grow_block 共写档参考块函数未受影响"""
    from app.presets import grow_block
    g = grow_block("urban_destiny", "grow_core_template")
    assert g and "改命流" in g
    g2 = grow_block("nonexistent_id", "grow_core_template")
    assert "未提供" in g2
    g3 = grow_block("", "grow_core_template")
    assert "通用" in g3
    print(f"  ✓ grow_block 共写档参考块函数正常")


# ---- 测试 6：用户目录导入覆盖 ----

def test_user_dir_overrides_builtin():
    """用户目录同名预设覆盖内置"""
    user_d = os.path.join(_FH, ".qianbi_novel", "presets")
    os.makedirs(user_d, exist_ok=True)
    custom = {
        "id": "urban_destiny",
        "name": "我的自定义改命流",
        "version": 2,
        "stage_hints": {"prose": "用户自定义 prose hint"},
    }
    with open(os.path.join(user_d, "urban_destiny.json"), "w", encoding="utf-8") as f:
        json.dump(custom, f, ensure_ascii=False)
    p = load_preset("urban_destiny")
    assert p.get("name") == "我的自定义改命流"
    assert "用户自定义" in p["stage_hints"]["prose"]
    print(f"  ✓ user dir overrides builtin (用户自定义胜出)")
    # 清理
    shutil.rmtree(user_d, ignore_errors=True)


# ---- runner ----

if __name__ == "__main__":
    print("== test_preset_v2 ==")
    test_list_presets_count()
    test_each_v2_preset_has_stage_hints()
    test_each_v2_preset_has_genre()
    test_stage_hint_returns_hints()
    test_stage_hint_empty_for_invalid()
    test_genre_block_for_all_stages()
    test_genre_block_for_includes_shared_fields()
    test_genre_block_for_review_no_shared()
    test_v1_migration()
    test_v1_migration_no_double_migrate()
    test_genre_block_fallback_v1()
    test_grow_block_still_works()
    test_user_dir_overrides_builtin()
    shutil.rmtree(_FH, ignore_errors=True)
    print("\n✓ All 13 tests passed")
