# -*- coding: utf-8 -*-
"""wb.constant_entries：常驻条目独立出口（体验轮 A2'）

确定性是灵魂——同一世界书两次调用必须逐字节一致（共享前缀架构的地基）；
只取 [常驻] 条目；截断按条不切半。
"""
import os

from app import project, wb


def _mk_proj(tmp_path, doc):
    proj = tmp_path / "wb书"
    (proj / "设定").mkdir(parents=True)
    project.write_file(str(proj / "设定" / "世界书.md"), doc)
    return str(proj)


DOC = """## 世界书

### 体系规则

- **斗气**（体系规则）：唯一主调能量。
  [常驻]
- **金币**（经济）：唯一基础货币。
  [常驻]
- **坊市**（民生与市场）：基层交易场所。
  [关键词：坊市]
- **岩甘草**（物品）：韩彻剥出的药材。
"""


def test_only_constant_entries(tmp_path):
    proj = _mk_proj(tmp_path, DOC)
    out = wb.constant_entries(proj)
    assert "斗气" in out and "金币" in out
    assert "坊市" not in out and "岩甘草" not in out


def test_deterministic_regardless_of_file_order(tmp_path):
    out1 = wb.constant_entries(_mk_proj(tmp_path / "a", DOC))
    shuffled = DOC.replace("- **斗气**（体系规则）：唯一主调能量。\n  [常驻]\n- **金币**（经济）：唯一基础货币。\n  [常驻]",
                           "- **金币**（经济）：唯一基础货币。\n  [常驻]\n- **斗气**（体系规则）：唯一主调能量。\n  [常驻]")
    out2 = wb.constant_entries(_mk_proj(tmp_path / "b", shuffled))
    assert out1 == out2, "排序必须与文件顺序无关"


def test_budget_truncates_by_entry(tmp_path):
    proj = _mk_proj(tmp_path, DOC)
    out = wb.constant_entries(proj, budget=10)
    assert "…（常驻条目截断）" in out
    assert out.count("- **") == 1, "按条截断：预算内只留第一条"


def test_empty_worldbook_returns_empty(tmp_path):
    proj = _mk_proj(tmp_path, "")
    assert wb.constant_entries(proj) == ""
    proj2 = _mk_proj(tmp_path / "2", "## 世界书\n\n- **坊市**（民生）：场所。\n")
    assert wb.constant_entries(proj2) == ""
