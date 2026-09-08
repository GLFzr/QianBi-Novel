# -*- coding: utf-8 -*-
"""V2 增量台账（writing.tracking_delta，缺省关）回归

- merge_named_sections：`## 名` 小节替换/追加、既有结构缺失时拒绝（回退全量）
- merge_table_rows：伏笔按首列键替换、时间线整行去重追加
- 旗标关（缺省）：_update_tracking 走全量路径（字节纪律）
全内存假件 + tmp 项目树，无真实 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.memory import merge_named_sections, merge_table_rows


EXISTING_STATES = """# 角色状态追踪

## 沈孤灯
- **当前身份**：守夜人
- **状态变更记录**：（第1章：接掌灯）

## 阿蓟
- **当前身份**：拾骨人
- **状态变更记录**：（第2章：左眼白翳一道）
"""

DELTA_STATES = """## 沈孤灯
- **当前身份**：守夜人
- **状态变更记录**：（第1章：接掌灯）（第5章：灯焰转橙）

## 老更头
- **当前身份**：司更差役
- **状态变更记录**：（第5章：首次登场）
"""


def test_merge_named_sections_replaces_and_appends():
    merged, changed = merge_named_sections(EXISTING_STATES, DELTA_STATES)
    assert set(changed) == {"沈孤灯", "老更头"}
    assert "灯焰转橙" in merged                       # 既有小节被 delta 替换
    assert "老更头" in merged and merged.index("老更头") > merged.index("沈孤灯")
    assert "左眼白翳一道" in merged                   # 未点名的小节原样保留
    assert merged.count("## 沈孤灯") == 1             # 不产生重复小节


def test_merge_named_sections_rejects_non_section_base():
    """既有文件不是 `## 名` 小节结构 → 拒绝合并（调用方回退全量，绝不写坏）"""
    merged, changed = merge_named_sections("# 纯文本没有小节结构", DELTA_STATES)
    assert changed == [] and merged == "# 纯文本没有小节结构"


def test_merge_named_sections_empty_delta_noop():
    merged, changed = merge_named_sections(EXISTING_STATES, "（本节无变更）")
    assert changed == [] and merged == EXISTING_STATES


FORESHADOW_EXISTING = """# 伏笔追踪

| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |
|---|---|---|---|---|---|
| 青铜铃 | 道具谜团 | 第2章 | 已埋 | 第20-30章 | 未回收 |
| 七次点灯 | 数字倒计时 | 第3章 | 已埋 | 第15章前 | 剩五次 |
"""

FORESHADOW_DELTA = """| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |
|---|---|---|---|---|---|
| 青铜铃 | 道具谜团 | 第2章 | 已回收 | 第20-30章 | 第5章敲响 |
| 断线线轴 | 道具谜团 | 第5章 | 已埋 | 第12-18章 | 新埋 |
"""


def test_merge_table_rows_replaces_by_key_and_appends():
    merged, changed = merge_table_rows(FORESHADOW_EXISTING, FORESHADOW_DELTA, key_col=0)
    assert set(changed) == {"青铜铃", "断线线轴"}
    assert "已回收 | 第20-30章 | 第5章敲响" in merged.replace("| ", "").replace(" |", "|") \
        or "已回收" in merged
    assert "剩五次" in merged                         # 未点名的行原样保留
    assert merged.count("| 青铜铃 |") == 1            # 不重复


TIMELINE_EXISTING = """# 故事时间线

| 故事内时间 | 章节 | 事件 |
|---|---|---|
| 第1夜 | 第1章 | 接灯 |
"""

TIMELINE_DELTA = """| 故事内时间 | 章节 | 事件 |
|---|---|---|
| 第5夜 | 第5章 | 灯焰转橙 |
"""


def test_merge_table_rows_timeline_appends_dedup():
    merged, changed = merge_table_rows(TIMELINE_EXISTING, TIMELINE_DELTA, key_col=-1)
    assert len(changed) == 1 and "第5夜" in merged
    # 重放同一 delta：整行去重，零新增
    merged2, changed2 = merge_table_rows(merged, TIMELINE_DELTA, key_col=-1)
    assert changed2 == [] and merged2 == merged


def test_merge_table_rows_rejects_tableless_delta():
    merged, changed = merge_table_rows(FORESHADOW_EXISTING, "（本节无变更）", key_col=0)
    assert changed == [] and merged == FORESHADOW_EXISTING
