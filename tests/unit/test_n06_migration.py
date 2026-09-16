# -*- coding: utf-8 -*-
"""WP-12 / N-06 显式迁移（R12）：老 config 升级行为保持

出厂默认从 1 改 3、地板从 3 改 1 之后，`load_config()` 只补缺失键——老用户盘上
写死的 `review_max_rounds: 1`（被旧地板吃掉的出厂值，实际生效一直是 3）会在升级
后静变成真 1。本组用例钉死迁移语义：
  ① 盘上值为 1 且无迁移标记 ⇒ 回填 3 + 落标记 + 当次落盘；
  ② 标记已存在（迁移时点已过）⇒ 用户显式设 1 尊重用户；
  ③ 其余值不回填，但同样落标记（防止将来显式设 1 被误迁）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import config as cfg_mod
from app.core.stages import _review_round_cap


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "qianbi_home" / ".qianbi_novel"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(cfg_dir / "config.json"))
    # 钉死旧版目录迁移源：不钉的话，_migrate_legacy_dir 会把真机 ~/.oh_story_desktop
    # 的 config.json 拷进假 home，测试结果随执行机器漂移
    monkeypatch.setattr(cfg_mod, "_LEGACY_DIR", str(tmp_path / "oh_story_desktop_absent"))
    return cfg_dir


def _write_disk(cfg_dir, gates, marker=None):
    """真实老用户配置形态：有 connections（否则 _migrate_legacy_format 会整体
    重建 DEFAULT——那条路径 gates 本来就回出厂 3，不在本组用例的被验语义内）"""
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(cfg_mod.DEFAULT_CONFIG))
    cfg["gates"].update(gates)
    if marker is not None:
        cfg[cfg_mod._N06_MARKER_KEY] = marker
    (cfg_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def test_legacy_disk_value_1_migrated_to_3(fake_home, caplog):
    """老 config（出厂值被旧地板吃掉，盘上写着 1）经 load 后上限 == 3"""
    _write_disk(fake_home, {"review_max_rounds": 1})
    with caplog.at_level("INFO", logger="qianbi.config"):
        cfg = cfg_mod.load_config()
    assert cfg["gates"]["review_max_rounds"] == 3
    assert _review_round_cap(cfg["gates"]) == 3
    assert cfg[cfg_mod._N06_MARKER_KEY] is True
    # 迁移必须当次落盘（迁移时点法：不留盘下次分不清「从未设过」与「主动设小」）
    disk = json.loads((fake_home / "config.json").read_text(encoding="utf-8"))
    assert disk["gates"]["review_max_rounds"] == 3
    assert disk[cfg_mod._N06_MARKER_KEY] is True
    assert any("N-06 迁移" in r.getMessage() for r in caplog.records)


def test_explicit_1_after_migration_respected(fake_home):
    """迁移时点已过（标记在盘）：用户显式设 1 ⇒ 上限 1，不再回填"""
    _write_disk(fake_home, {"review_max_rounds": 1}, marker=True)
    cfg = cfg_mod.load_config()
    assert cfg["gates"]["review_max_rounds"] == 1
    assert _review_round_cap(cfg["gates"]) == 1


def test_other_values_marked_but_not_rewritten(fake_home):
    """非 1 的老值（用户自改）不回填，但落标记——防止日后显式设 1 被误迁"""
    _write_disk(fake_home, {"review_max_rounds": 5})
    cfg = cfg_mod.load_config()
    assert cfg["gates"]["review_max_rounds"] == 5
    assert cfg[cfg_mod._N06_MARKER_KEY] is True
    disk = json.loads((fake_home / "config.json").read_text(encoding="utf-8"))
    assert disk[cfg_mod._N06_MARKER_KEY] is True


def test_migration_is_one_shot(fake_home):
    """迁移幂等：首次 load 回填 3 并落盘；二次 load 不再触发（无重复日志/改写）"""
    _write_disk(fake_home, {"review_max_rounds": 1})
    cfg_mod.load_config()
    # 模拟用户在迁移后又显式改 1：标记已在盘，值必须原样活着
    disk = json.loads((fake_home / "config.json").read_text(encoding="utf-8"))
    disk["gates"]["review_max_rounds"] = 1
    (fake_home / "config.json").write_text(
        json.dumps(disk, ensure_ascii=False), encoding="utf-8")
    cfg = cfg_mod.load_config()
    assert cfg["gates"]["review_max_rounds"] == 1


def test_fresh_install_gets_3_and_marker(fake_home):
    """全新安装：无 config.json ⇒ 出厂 3，首次 load 后标记落盘"""
    cfg = cfg_mod.load_config()
    assert cfg["gates"]["review_max_rounds"] == 3
    disk = json.loads((fake_home / "config.json").read_text(encoding="utf-8"))
    assert disk[cfg_mod._N06_MARKER_KEY] is True
