# -*- coding: utf-8 -*-
"""A1 章纲合同（ChapterDirective · 17 字段）——解析/校验/合同块/菜单钉测

覆盖四组：
1. 解析全覆盖：JSON 形态（英文键/中文标签/嵌套 chapter_directive/未知字段进
   extra）与结构化文本形态（中文标签行/顿号列表/中文数字章号）双形态 17 字段。
2. validate_directive：缺字段 fail 候选清单（空合同=全部必填；完备合同=空表）。
3. 畸形输入不炸：空串/None/乱码/不配对花括号/伪 JSON/叙述行，一律不抛异常。
4. prompt 侧：to_prompt_block 含全部 17 字段名且零 ASCII 花括号；
   planning.DIRECTIVE_CONTRACT_MENU_BLOCK 与 chapter_directive.
   directive_contract_menu() 逐字节等价（单一出处的钉定渲染副本纪律）。
stages 挂点（_mc_assemble 调 parse/validate）为 D-stages 批 TODO，本文件钉的是
接线方必须遵守的形状。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.chapter_directive import (  # noqa: E402
    FIELD_ORDER, FIELD_SPECS, LIST_FIELDS, REQUIRED_FIELDS,
    ChapterDirective, cn_num_to_int, directive_contract_menu,
    parse_directive, to_prompt_block, validate_directive,
)
from app.prompts.planning import CHAPTER_OUTLINE_PROMPT, DIRECTIVE_CONTRACT_MENU_BLOCK  # noqa: E402


# ---------------- 1. 17 字段解析全覆盖 ----------------

def test_field_schema_has_exactly_17_fields():
    """schema 恰为 T1 报告的 17 字段，list 字段恰为 5 个，必填为 9 个核心字段"""
    assert len(FIELD_ORDER) == 17
    assert set(FIELD_SPECS) == {
        "goal", "obstacles", "cost", "time_anchor", "chapter_span", "countdown",
        "cbn", "cpns", "cen", "must_cover_nodes", "forbidden_zones",
        "chapter_end_open_question", "hook_type", "hook_strength",
        "key_entities", "strand", "antagonist_tier"}
    assert set(LIST_FIELDS) == {"cpns", "must_cover_nodes", "forbidden_zones", "key_entities"}
    assert "must_cover_nodes" in REQUIRED_FIELDS   # A2 覆盖拒收的核对清单必须必填


_JSON_FULL = """```json
{"chapter_num": 103,
 "goal": "退婚对峙", "obstacles": "纳兰嫣然与其护卫", "cost": "暴露药老风险的隐患",
 "time_anchor": "主线第 47 日黄昏", "chapter_span": "当日至当夜", "countdown": "三年之约 D-0",
 "cbn": "萧炎 | 踏入云岚宗大殿 | 迎接纳兰嫣然",
 "cpns": ["退婚宣言 | 当众立字据 | 纳兰家失颜面", "药老现身 | 魂息压场 | 逼退凌影"],
 "cen": "药老 | 露出半缕魂息 | 震退凌影",
 "must_cover_nodes": ["退婚宣言", "药老现身"],
 "forbidden_zones": ["萧炎认输", "药老全貌登场"],
 "chapter_end_open_question": "药老的真实身份",
 "hook_type": "危机迫近", "hook_strength": "强",
 "key_entities": ["萧炎", "纳兰嫣然", "药老"],
 "strand": "quest", "antagonist_tier": "纳兰家供奉",
 "unknown_ext": "扩展位示例"}
```"""


def test_parse_json_form_full_17_fields():
    """JSON 围栏形态：17 字段全解析 + 中文章名键 + 未知字段进 extra（v7 容错）"""
    d = parse_directive(_JSON_FULL)
    assert d.chapter_num == 103
    assert d.goal == "退婚对峙" and d.cbn.startswith("萧炎")
    assert d.cpns == ["退婚宣言 | 当众立字据 | 纳兰家失颜面", "药老现身 | 魂息压场 | 逼退凌影"]
    assert d.must_cover_nodes == ["退婚宣言", "药老现身"]
    assert d.forbidden_zones == ["萧炎认输", "药老全貌登场"]
    assert d.chapter_end_open_question == "药老的真实身份"
    assert d.hook_type == "危机迫近" and d.hook_strength == "强"
    assert d.key_entities == ["萧炎", "纳兰嫣然", "药老"]
    assert d.strand == "quest" and d.antagonist_tier == "纳兰家供奉"
    assert d.time_anchor == "主线第 47 日黄昏" and d.countdown == "三年之约 D-0"
    assert d.chapter_span == "当日至当夜" and d.obstacles and d.cost
    assert d.extra.get("unknown_ext") == "扩展位示例"
    assert validate_directive(d) == []


def test_parse_json_nested_chapter_directive_and_chinese_labels():
    """JSON 嵌套 chapter_directive 键 + 中文标签键 + 半角冒号列表"""
    d = parse_directive('{"chapter_directive": {"目标": "灭门之夜", "时间锚点": "子时",'
                        ' "cpns": "a, b, c", "chapter_num": 7}}')
    assert d.goal == "灭门之夜" and d.time_anchor == "子时"
    assert d.cpns == ["a", "b", "c"] and d.chapter_num == 7


_MD_FULL = """===第103章===
### 第一百零三章：三年之约
- 核心事件：退婚对峙
- 阻力：纳兰嫣然与其护卫
- 代价：暴露药老风险的隐患
- 头部时间戳：主线第 47 日黄昏
- 本章禁区：萧炎认输、药老全貌登场
- 承接节点：萧炎 | 踏入云岚宗大殿 | 迎接纳兰嫣然
- 推进节点：退婚宣言、药老现身
- 章末节点：药老 | 露出半缕魂息 | 震退凌影
- 必须覆盖节点：退婚宣言、药老现身
- 章末未闭合问题：药老的真实身份
- 钩型：危机迫近
- 期待度：强
- 关键实体：萧炎、纳兰嫣然、药老
- 主线归属：quest
- 反派层级：纳兰家供奉
"""


def test_parse_structured_text_form_17_fields():
    """结构化文本形态：中文标签/顿号列表/中文数字章号/别名标签（核心事件→goal）"""
    d = parse_directive(_MD_FULL)
    assert d.chapter_num == 103               # ===第N章=== 头部
    assert d.goal == "退婚对峙"               # 「核心事件」别名映射
    assert d.time_anchor == "主线第 47 日黄昏"  # 「头部时间戳」别名映射
    assert d.hook_strength == "强"             # 「期待度」别名映射
    assert d.must_cover_nodes == ["退婚宣言", "药老现身"]
    assert d.forbidden_zones == ["萧炎认输", "药老全貌登场"]
    assert d.chapter_end_open_question == "药老的真实身份"
    assert validate_directive(d) == []
    assert d.extra == {}                       # 叙述类未知标签不进 extra


def test_parse_explicit_chapter_num_overrides_detection():
    d = parse_directive(_MD_FULL, chapter_num=42)
    assert d.chapter_num == 42


def test_cn_num_to_int_common_forms():
    assert cn_num_to_int("103") == 103
    assert cn_num_to_int("一百零三") == 103
    assert cn_num_to_int("两千零五") == 2005
    assert cn_num_to_int("二十一") == 21
    assert cn_num_to_int("十二") == 12
    assert cn_num_to_int("三万") == 30000
    assert cn_num_to_int("退婚") is None
    assert cn_num_to_int("") is None


# ---------------- 2. 缺字段 fail 候选清单 ----------------

def test_validate_empty_directive_lists_all_required():
    """空合同 → 缺字段清单=全部必填字段（按 FIELD_ORDER 序）"""
    missing = validate_directive(ChapterDirective())
    assert missing == [f for f in FIELD_ORDER if f in REQUIRED_FIELDS]
    assert "goal" in missing and "must_cover_nodes" in missing
    assert "obstacles" not in missing          # 可选字段不进 fail 候选


def test_validate_partial_directive_lists_only_missing():
    d = parse_directive("- 目标：灭门\n- 钩型：悬念缺口\n- 期待度：中\n- 时间锚点：子时\n"
                        "- 承接节点：陈更 | 归铺 | 点灯\n- 章末节点：陈更 | 发现第三枚指印 | 疑内鬼\n")
    assert validate_directive(d) == ["cpns", "must_cover_nodes", "chapter_end_open_question"]


def test_validate_none_and_empty_list_treated_as_missing():
    d = ChapterDirective(goal="x", cpns=[], must_cover_nodes=["a"], cen="y",
                         cbn="z", time_anchor="t", hook_type="危机迫近",
                         hook_strength="强", chapter_end_open_question="q")
    assert validate_directive(d) == ["cpns"]    # 空列表=缺
    assert ChapterDirective.missing_required(ChapterDirective()) == \
        [f for f in FIELD_ORDER if f in REQUIRED_FIELDS]


# ---------------- 3. 畸形输入不炸 ----------------

def test_parse_never_raises_on_degenerate_inputs():
    for bad in ("", None, "   ", "纯属叙述，没有字段", "```json\n{broken\n```",
                "{不配对的花括号", "{\"goal\": }", "### 第abc章：乱码章\n- ：空标签\n- 无值字段：",
                "a" * 5000, "{\"chapter_directive\": \"不是字典\"}"):
        d = parse_directive(bad)
        assert isinstance(d, ChapterDirective)
        assert set(validate_directive(d)) <= set(REQUIRED_FIELDS)


def test_parse_garbage_returns_blank_directive():
    d = parse_directive("这只是一段散文：里面有冒号，但没有字段。")
    assert d.goal is None and d.cpns is None and d.chapter_num is None
    assert d.extra == {}


# ---------------- 4. prompt 侧：合同块与菜单 ----------------

def test_to_prompt_block_contains_all_17_field_names():
    d = parse_directive(_JSON_FULL)
    block = to_prompt_block(d)
    for f in FIELD_ORDER:
        cn = FIELD_SPECS[f][0]
        assert cn in block and f"（{f}）" in block, f"合同块缺字段 {cn}({f})"
    assert "退婚对峙" in block and "、".join(d.must_cover_nodes) in block
    assert "{" not in block and "}" not in block          # 可拼进 .format 模板


def test_to_prompt_block_blank_directive_marks_undeclared():
    block = to_prompt_block(ChapterDirective())
    assert block.count("（未声明）") >= 17 - 0
    for f in FIELD_ORDER:
        assert f"（{f}）" in block


def test_directive_contract_menu_matches_rendered_copy_in_planning():
    """单一出处纪律：planning 注入块与 chapter_directive 渲染逐字节等价，零花括号"""
    menu = directive_contract_menu()
    assert "{" not in menu and "}" not in menu
    assert menu in DIRECTIVE_CONTRACT_MENU_BLOCK
    for f in FIELD_ORDER:
        assert FIELD_SPECS[f][0] in menu and f in menu
        req = "必填" if f in REQUIRED_FIELDS else "可选"
        assert f"（{f}，{req}）" in menu


def test_planning_prompt_injects_contract_menu_and_json_contract():
    """细纲 prompt 已升级为按合同输出：菜单节 + 每章 json 合同小节都在"""
    assert DIRECTIVE_CONTRACT_MENU_BLOCK in CHAPTER_OUTLINE_PROMPT
    assert "#### 章纲合同（chapter_directive）" in CHAPTER_OUTLINE_PROMPT
    assert '"must_cover_nodes"' in CHAPTER_OUTLINE_PROMPT
    assert '"hook_strength"' in CHAPTER_OUTLINE_PROMPT
    # 既有钩型词表注入不被破坏（hook_vocab 单出处仍同源在场）
    from app.prompts.hook_vocab import HOOK_TYPE_MENU
    assert "钩型：" + HOOK_TYPE_MENU in CHAPTER_OUTLINE_PROMPT


def test_parse_directive_round_trips_through_planning_style_output():
    """planning 输出形态（叙事栏目 + 合同 json 小节）可被 parse_directive 消费"""
    sample = CHAPTER_OUTLINE_PROMPT[:0] + """===第9章===
### 第 9 章：清账夜
- 核心事件：陈更当众清账
#### 章纲合同（chapter_directive）
```json
{"chapter_num": 9, "goal": "当众清账", "time_anchor": "主线第 9 日子时",
 "cbn": "陈更 | 归铺 | 点灯", "cpns": ["清账 | 逐笔核销 | 账平"],
 "cen": "陈更 | 发现第三枚指印 | 疑内鬼", "must_cover_nodes": ["清账"],
 "chapter_end_open_question": "第三枚指印是谁的", "hook_type": "悬念缺口",
 "hook_strength": "中"}
```
"""
    d = parse_directive(sample)
    assert d.chapter_num == 9 and d.goal == "当众清账"
    assert validate_directive(d) == []
