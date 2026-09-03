# -*- coding: utf-8 -*-
"""A2 世界书修正提案路由单测：双轨裁决的确定性半边

- propose_worldbook_corrections 只登记带【世界书修正】标记的条目
- 提案只写 设定/世界书_修正提案.md，绝不改世界书本体
- 「世界书旧条目 vs 正文已演进」场景：条目保持 marginal → 不产生
  REJECT 判决、不进修复目标，只落修正提案文件
"""
import os

from app.core import memory, stages
from app import project


def _proposal_path(proj: str) -> str:
    return os.path.join(proj, memory.PROPOSAL_PATH)


def _marked_item(text: str, level: str = "marginal", dim: str = "D") -> dict:
    return {"level": level, "dim": dim, "text": text, "quote": ""}


def test_marked_items_registered(tmp_path):
    proj = str(tmp_path)
    items = [
        _marked_item("【世界书修正】世界书登记陈屿为炼气三层，正文已写其突破筑基"
                     "（正文与近章摘要/角色状态自洽，疑世界书条目更新滞后）"),
        _marked_item("[世界书修正] 世界书登记灵石余额 30，正文按 80 演进"
                     "（反哺已登记收支，疑旧条目过时）"),
        _marked_item("普通问题：章末钩子偏弱"),          # 无标记 → 不登记
    ]
    n = memory.propose_worldbook_corrections(proj, 3, items)
    assert n == 2
    doc = project.read_file(_proposal_path(proj))
    assert doc.startswith("# 世界书修正提案")
    assert "## 第3章" in doc
    assert "炼气三层" in doc and "灵石余额 30" in doc
    assert "章末钩子偏弱" not in doc


def test_no_mark_no_file(tmp_path):
    proj = str(tmp_path)
    n = memory.propose_worldbook_corrections(
        proj, 5, [_marked_item("正文与世界书冲突 → 正文写错"), None])
    assert n == 0
    assert not os.path.exists(_proposal_path(proj))


def test_append_keeps_header_single(tmp_path):
    proj = str(tmp_path)
    memory.propose_worldbook_corrections(
        proj, 3, [_marked_item("【世界书修正】条目甲")])
    memory.propose_worldbook_corrections(
        proj, 7, [_marked_item("【世界书修正】条目乙")])
    doc = project.read_file(_proposal_path(proj))
    assert doc.count("# 世界书修正提案") == 1
    assert "## 第3章" in doc and "## 第7章" in doc
    assert "- [审校修正] 【世界书修正】条目甲" in doc


def test_worldbook_body_never_touched(tmp_path):
    proj = str(tmp_path)
    wb = os.path.join(proj, project.WORLDBOOK_PATH)
    project.write_file(wb, "# 世界书\n## 实体登记\n- **陈屿**（主角）：炼气三层修士。\n")
    memory.propose_worldbook_corrections(
        proj, 9, [_marked_item("【世界书修正】陈屿修为应更新为筑基")])
    assert project.read_file(wb) == "# 世界书\n## 实体登记\n- **陈屿**（主角）：炼气三层修士。\n"


def test_stale_worldbook_scenario_not_blocking(tmp_path):
    """验收夹具：世界书旧条目（炼气三层）vs 正文已演进（筑基）

    审校按双轨判为 marginal + 【世界书修正】标记（LLM 半边，此处用真实
    产出形态回放）→ 确定性半边必须满足：
    1. 判决非 REJECT（不进修复环：无 fail 级条目 = 无修复目标）
    2. 修正提案落盘，供人工核对后并入
    """
    proj = str(tmp_path)
    items = [_marked_item(
        "【世界书修正】世界书登记陈屿为炼气三层，正文已写其突破筑基；"
        "正文与近章摘要/角色状态自洽，疑世界书条目更新滞后")]
    summary = {"pass": 5, "marginal": 1, "fail": 0}
    verdict = stages.compute_verdict(summary, items, declared="")
    assert verdict == "PASS"
    assert verdict not in ("REJECT", "REJECT-HARD")
    # 修复目标只收 fail 级（同 bridge._build_fix_targets 口径）→ 无目标
    assert not [it for it in items if it.get("level") == "fail"]
    n = memory.propose_worldbook_corrections(proj, 12, items)
    assert n == 1
    assert "炼气三层" in project.read_file(_proposal_path(proj))
