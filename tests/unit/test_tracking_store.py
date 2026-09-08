# -*- coding: utf-8 -*-
"""V2.1 追踪 JSON 补丁协议回归（深度研究 §4 + 台账最小化调研落地）

- tracking_store：markdown 惰性播种 / 键控 upsert / 追加记录行 / 派生视图渲染
- 输出量绑定「本章出场实体数」：既有角色不动就不出现在输出里
- _extract_json_block：```json 围栏 / 裸对象 / 垃圾输入
全部 tmp_path 真实文件，无 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import tracking_store as ts
from app.core.stages import _extract_json_block

MD_SEED = """# 角色状态追踪

## 沈孤灯
- **当前身份**：守夜人
- **当前能力**：点灯改命
- **关键关系**：阿蓟（搭档）
- **公众形象**：孤僻
- **待回收伏笔**：无
- **状态变更记录**：（第1章：接掌灯）
"""


def _proj(tmp_path, md=MD_SEED):
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    with open(os.path.join(proj, "追踪", "角色状态.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return proj


def test_seed_from_markdown_then_keyed_update(tmp_path):
    proj = _proj(tmp_path)
    changed = ts.apply_character_updates(
        proj, 5,
        updates=[{"id": "沈孤灯", "field": "公众形象", "value": "临安名人"}],
        records=[{"id": "沈孤灯", "line": "灯焰转橙"}],
        new_chars=[])
    assert changed == ["沈孤灯"]
    md = ts.render_characters_md(proj)
    assert "临安名人" in md and "灯焰转橙" in md and "（第1章：接掌灯）" in md
    assert md.count("## 沈孤灯") == 1
    # sidecar 是真源：变更记录全量保留，视图只渲染最近 N 条
    side = json.load(open(os.path.join(proj, "追踪", "角色状态.json"), encoding="utf-8"))
    assert len(side["characters"]["沈孤灯"]["_records"]) == 2


def test_new_character_and_record_append(tmp_path):
    proj = _proj(tmp_path)
    changed = ts.apply_character_updates(
        proj, 2, updates=[],
        records=[{"id": "沈孤灯", "line": "首次出手"}],
        new_chars=[{"id": "阿蓟", "当前身份": "拾骨人", "record": "登场"}])
    assert set(changed) == {"沈孤灯", "阿蓟"}
    md = ts.render_characters_md(proj)
    assert "## 阿蓟" in md and "（第2章：登场）" in md


def test_untouched_character_stays_intact(tmp_path):
    """输出量绑定本章出场实体数：未点名角色零变化（照抄膨胀的根治验证）"""
    proj = _proj(tmp_path)
    ts.apply_character_updates(proj, 5, updates=[{"id": "沈孤灯", "field": "公众形象",
                                                  "value": "名人"}],
                               records=[], new_chars=[])
    side = json.load(open(os.path.join(proj, "追踪", "角色状态.json"), encoding="utf-8"))
    assert side["characters"]["沈孤灯"]["当前身份"] == "守夜人"   # 只动被点名字段


def test_foreshadow_upsert_and_render(tmp_path):
    proj = str(tmp_path / "书2")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    changed = ts.apply_foreshadow_upserts(proj, [
        {"伏笔": "青铜铃", "类别": "道具谜团", "埋设章节": "第2章",
         "状态": "已回收", "计划回收": "第20-30章", "备注": "敲响"},
        {"伏笔": "断线线轴", "类别": "道具谜团", "埋设章节": "第5章",
         "状态": "已埋", "计划回收": "第12-18章", "备注": ""},
    ])
    assert set(changed) == {"青铜铃", "断线线轴"}
    md = ts.render_foreshadow_md(proj)
    assert md.count("| 青铜铃 |") == 1 and "已回收" in md
    # 再 upsert 同名：last-write-wins 不重复
    ts.apply_foreshadow_upserts(proj, [{"伏笔": "青铜铃", "状态": "已回收"}])
    assert ts.render_foreshadow_md(proj).count("| 青铜铃 |") == 1


def test_extract_json_block_variants():
    assert _extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_block('前言 {"a": {"b": 2}} 后记') == {"a": {"b": 2}}
    for bad in ("", "没有对象", "```json\n[1]\n```"):
        try:
            _extract_json_block(bad)
            raise SystemExit("应当抛错: %r" % bad)
        except ValueError:
            pass
