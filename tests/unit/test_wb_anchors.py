# -*- coding: utf-8 -*-
"""W0b 锚点取材：app/wb.py 专名提取（真实世界书/细纲结构 + 栏目标签防误报）

旧实现（project._WB_NAME_RE + 「角色：」字段）在真实书籍上恒返空，
A4 的相关性截断从未生效；本组测试用真实结构夹具锁住新取材口径。
"""
from app import wb


def test_roster_names_four_real_syntaxes():
    doc = """
## 主要角色表

| 角色 | 定位 | 一句话动机 |
|------|------|------------|
| 陈更 | 主角 | 查清父亲死因 |
| **顾拾遗** | 灯盟 | 守住规矩 |

- 柳三更：灰袍灯客
- 苏晚：报社编辑

### 北城当铺

- 类型：据点

姓名：沈知微
"""
    assert wb.roster_names(doc) == ["陈更", "顾拾遗", "柳三更", "苏晚", "北城当铺", "沈知微"]


def test_roster_names_filters_labels_and_metadata():
    doc = """
| 实体 | 类别 | 描述 | 关联规则 |
|------|------|------|----------|
| 陈默 | 主角 | 沉默寡言 | 规则1 |

### 规则与数值基准

- 点灯：每日三次为限
"""
    names = wb.roster_names(doc)
    assert names == ["陈默", "点灯"]           # 「陈默」留；表头与元数据行剔除
    assert "主角" not in names and "描述" not in names and "实体" not in names
    assert "主要角色表" not in names and "人物" not in names


def test_cast_names_reads_real_outline_field():
    doc = """
## 细纲第4章 · 当票

#### 人物关系和出场顺序

- 出场顺序：陈更、柳三更（灰袍灯客）
- 视角：陈更

#### 情节点序列

1. 陈更发现当票上的印是假的
"""
    assert wb.cast_names(doc) == ["陈更", "柳三更"]      # 只取出场字段，不取整篇
    assert wb.cast_names("") == []


def test_cast_names_accepts_legacy_and_alias_labels():
    assert wb.cast_names("角色：陈更、苏晚") == ["陈更", "苏晚"]
    assert wb.cast_names("登场人物：柳三更，顾拾遗") == ["柳三更", "顾拾遗"]
    assert wb.cast_names("出场：无") == []               # 「无」是占位，不是专名


def test_matching_names_only_hits_known_names():
    body = "1. 顾拾遗在北城当铺烧毁当票\n2. 陈更改写账册\n"
    known = ["顾拾遗", "陈更", "柳三更", "北城当铺"]
    assert wb.matching_names(body, known) == ["顾拾遗", "陈更", "北城当铺"]
    assert wb.matching_names("", known) == []
    assert wb.matching_names(body, []) == []


def test_merge_names_order_and_dedupe():
    assert wb.merge_names(["陈更"], ["陈更", "柳三更"], ["苏晚", "陈更"]) == ["陈更", "柳三更", "苏晚"]
    assert wb.merge_names(None, ["", "顾拾遗"]) == ["顾拾遗"]
