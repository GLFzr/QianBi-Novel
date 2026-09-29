# -*- coding: utf-8 -*-
"""T2 钩子追读链账本——7 钩型受控词表（app/prompts/hook_vocab.py）单元测试（C34 段1）

四组验收（卡4 ⑤先写哪条测试 + 本卡任务4）：
1. 封闭性：判据字典键集 == 7 型枚举；路由值 ⊆ 枚举；extract_hook_type 输出必在
   枚举内（或空）；注入块无 ASCII 花括号（模板要走 .format()）。
2. 细纲字段接线：planning 模板带词表块与三处升级字段；章首钩子不再是空壳。
3. 解析落账：parse_hook_record 的数据形状（型+定位+一句概括）与枚举校验兜底。
4. 连弱钩检测纯函数 + 低压白名单（低张力章允许无钩/弱钩）。

纯函数零 API；stages/co_dialogue 的落账接线为 TODO（B3/S2c 领地），本文件钉的是
接线方必须遵守的数据形状与裁决内核。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.prompts import hook_vocab as hv
from app.prompts.hook_vocab import (
    HOOK_POSITIONS, HOOK_ROUTE, HOOK_ROW_KEYS, HOOK_STRENGTHS, HOOK_TYPE_CRITERIA,
    HOOK_TYPES, NO_HOOK_POSITIONS, OUTLINE_POSITIONS,
    extract_hook_strength, extract_hook_type, extract_outline_position,
    no_hook_allowed, parse_hook_record, route_hook_types,
    validate_hook_row, weak_hook_findings,
)

SAMPLE_OUTLINE = """### 第 21 章：清账夜
- 章节定位：高压（本卷第一次正面交锋）
- 章首钩子：当票背面多出一行不属于任何人的小字。
- 爽点：陈更当众戳穿假账。
#### 结尾设定和钩子
- 结尾设定：柳三更把第三枚指印拓进册子。
- 章尾钩子：陈更发现当票上多出第三枚指印，怀疑铺子里有内鬼。期待度：强；钩型：悬念缺口；与下一章承接：开查内鬼
"""


# ---------- 1. 封闭性 ----------

def test_hook_type_vocab_closed():
    """7 型常量与判据字典键集相等且每条判据非空（受控词表封闭性，卡4 ⑤首测）"""
    assert len(HOOK_TYPES) == 7 and len(set(HOOK_TYPES)) == 7
    assert set(HOOK_TYPE_CRITERIA) == set(HOOK_TYPES)
    for t in HOOK_TYPES:
        assert HOOK_TYPE_CRITERIA[t].strip(), f"{t} 判据为空"
    # 判据是自产表达：不内化十三式原文——判据必须是「成立条件」而非招式名堆砌
    assert all("判据" not in c and "示例" not in c for c in HOOK_TYPE_CRITERIA.values())


def test_route_table_within_enum():
    """路由表键 = 章节定位六档全集；值 ⊆ 7 型且非空；烈度三档不扩档"""
    assert set(HOOK_ROUTE) == set(OUTLINE_POSITIONS)
    assert len(OUTLINE_POSITIONS) == 6
    for pos, types in HOOK_ROUTE.items():
        assert types and set(types) <= set(HOOK_TYPES), f"{pos} 路由越出词表"
    assert HOOK_STRENGTHS == ("强", "中", "弱")
    assert HOOK_POSITIONS == ("章首", "章尾")


def test_no_type_name_is_substring_of_another():
    """解析按子串命中：任何一型不得是另一型的子串（否则命中歧义）"""
    for a in HOOK_TYPES:
        for b in HOOK_TYPES:
            if a != b:
                assert a not in b, f"{a} 是 {b} 的子串，解析会歧义"


def test_extract_type_output_always_in_enum():
    """封闭性核心：任意输入下 extract_hook_type 只可能返回枚举值或空串"""
    samples = ["钩型：危机迫近（期待度：强）", "反转揭示+情绪定格", "乱写的：天外飞仙",
               "", None, "悬念缺口危机迫近两难抉择承诺威胁意象异变情绪定格反转揭示",
               "HOOK：info_gap", "「意象异变」"]
    for s in samples:
        assert extract_hook_type(s) in HOOK_TYPES or extract_hook_type(s) == ""
    assert extract_hook_type("钩型：危机迫近（期待度：强）") == "危机迫近"
    assert extract_hook_type("乱写的：天外飞仙") == ""
    assert extract_hook_strength("期待度：弱") == "弱"
    assert extract_hook_strength("没有标注") == ""


# ---------- 2. 细纲字段接线（prompt 面） ----------

def test_planning_fields_wired_to_vocab():
    """三处字段升级点：词表块整体注入；章尾钩子带七选一菜单；章首钩子不再空壳"""
    from app.prompts import CHAPTER_OUTLINE_PROMPT
    from app.prompts.hook_vocab import FIRST_HOOK_GUIDE, HOOK_TYPE_MENU, HOOK_VOCAB_BLOCK
    assert HOOK_VOCAB_BLOCK in CHAPTER_OUTLINE_PROMPT
    assert "钩型：" + HOOK_TYPE_MENU in CHAPTER_OUTLINE_PROMPT          # :239 章尾钩子
    assert "- 章首钩子：（" + FIRST_HOOK_GUIDE in CHAPTER_OUTLINE_PROMPT  # :206 不再空壳
    assert "闪前碎片" in FIRST_HOOK_GUIDE and "倒计时" in FIRST_HOOK_GUIDE  # 两式并入指引
    assert "章节定位" in CHAPTER_OUTLINE_PROMPT and "无钩白名单" in CHAPTER_OUTLINE_PROMPT  # :202 分档路由指引
    # 旧空壳不允许复活
    assert "- 章首钩子：\n" not in CHAPTER_OUTLINE_PROMPT


def test_injected_blocks_brace_free():
    """注入块拼接进模板后整体走 .format()：块内出现 ASCII 花括号即 KeyError 级隐患"""
    from app.prompts.hook_vocab import FIRST_HOOK_GUIDE, HOOK_VOCAB_BLOCK
    for blob in (HOOK_VOCAB_BLOCK, FIRST_HOOK_GUIDE):
        assert "{" not in blob and "}" not in blob
    # 全 7 型在词表块中逐一在场（按展示顺序）
    pos = [HOOK_VOCAB_BLOCK.index(t) for t in HOOK_TYPES]
    assert pos == sorted(pos), "词表块展示顺序应与枚举一致"


def test_route_block_renders_all_positions():
    """分档路由行覆盖六档定位且低压分组收敛到两型子集"""
    import re
    from app.prompts.hook_vocab import HOOK_VOCAB_BLOCK
    for pos in OUTLINE_POSITIONS:
        assert pos in HOOK_VOCAB_BLOCK, f"路由行缺 {pos}"
    # 只取「低压生活/信息整理→…」路由段本身：段内不得出现高张力钩型
    seg = re.search(r"低压生活/信息整理→([^；。\n]+)", HOOK_VOCAB_BLOCK)
    assert seg, "路由行缺低压分组"
    assert {s.strip() for s in seg.group(1).replace("仅", "").split("/")} == {"意象异变", "情绪定格"}
    # 白名单说明句在场：不强求钩子、可写「无」但须给往下看的理由
    assert "不强求钩子" in HOOK_VOCAB_BLOCK and "「无」" in HOOK_VOCAB_BLOCK


# ---------- 3. 分档路由与低压白名单 ----------

def test_route_full_set_for_high_tension():
    """高压/推进 → 全 7 型（卡4：全 7 型提示）"""
    assert route_hook_types("高压") == HOOK_TYPES
    assert route_hook_types("推进") == HOOK_TYPES


def test_route_low_pressure_subset():
    """低压子集：低压生活/信息整理 可用钩型 ⊆ {意象异变, 情绪定格}（卡4 ⑤）"""
    for pos in ("低压生活", "信息整理"):
        assert set(route_hook_types(pos)) <= {"意象异变", "情绪定格"}


def test_route_unknown_position_fail_open():
    """未知/空定位 fail-open 放开全 7 型（不硬拦，缺枚举值时宁可多提示）"""
    assert route_hook_types("未知档") == HOOK_TYPES
    assert route_hook_types("") == HOOK_TYPES
    assert route_hook_types(None) == HOOK_TYPES
    # 中间档落在两端之间（非全量、非低压两型）
    assert 0 < len(route_hook_types("修炼试错")) < 7
    assert 0 < len(route_hook_types("关系回收")) < 7


def test_no_hook_whitelist():
    """白名单逻辑：低张力章允许无钩；其余档不允许"""
    assert no_hook_allowed("低压生活") and no_hook_allowed("信息整理")
    assert NO_HOOK_POSITIONS == ("低压生活", "信息整理")
    for pos in ("高压", "推进", "修炼试错", "关系回收", "", "乱写"):
        assert not no_hook_allowed(pos)


# ---------- 4. 解析落账：数据形状 + 枚举兜底 ----------

def test_parse_hook_record_shape():
    """型+定位+一句概括：账本行形状冻结（卡4 schema 超集），字段键集不增不减"""
    rec = parse_hook_record(21, SAMPLE_OUTLINE)
    row = rec.to_row()
    assert tuple(sorted(row)) == tuple(sorted(HOOK_ROW_KEYS))
    assert row["num"] == 21 and row["position"] == "章尾"
    assert row["type"] == "悬念缺口" and row["strength"] == "强"
    assert row["summary"] == "陈更发现当票上多出第三枚指印，怀疑铺子里有内鬼"
    assert row["outline_position"] == "高压"
    # 「第三枚指印」引文不在本句 → 引文优先策略下 event_kw 允许为空（弃权转 LLM 轨）
    assert row["is_event_hook"] == bool(row["event_kw"])
    assert validate_hook_row(row) == []


def test_parse_hook_record_first_hook_and_position_enum():
    """章首行解析：position=章首；章首钩无烈度档 → strength 为空"""
    rec = parse_hook_record(21, SAMPLE_OUTLINE, position="章首")
    assert rec.position == "章首" and rec.type == ""
    assert rec.summary == "当票背面多出一行不属于任何人的小字"
    assert rec.strength == "" and rec.is_event_hook is False


def test_parse_hook_record_event_kw_from_quotes():
    """event_kw 启发式：「」引文优先，最多 2 条；无引文 → 空串弃权（卡4 风险②）"""
    line = "### 第 5 章\n- 章尾钩子：她说「三日后交货」，他把刀留在「当铺」柜台。期待度：中；钩型：承诺威胁\n"
    row = parse_hook_record(5, line).to_row()
    assert row["type"] == "承诺威胁" and row["strength"] == "中"
    assert row["event_kw"] == "三日后交货|当铺"
    assert row["is_event_hook"] is True
    bare = parse_hook_record(6, "- 章尾钩子：夜色压下来，谁也没说话。期待度：弱；钩型：情绪定格").to_row()
    assert bare["event_kw"] == "" and bare["is_event_hook"] is False
    assert validate_hook_row(bare) == []


def test_parse_hook_record_missing_line_fails_open():
    """钩子行缺失 → 全空字段记录（fail-open），弱钩检测据此判弱而非解析报错"""
    row = parse_hook_record(9, "### 第 9 章\n- 爽点：无\n").to_row()
    assert row["type"] == "" and row["summary"] == "" and row["is_event_hook"] is False
    assert row["outline_position"] == ""  # 无定位行也不炸
    assert validate_hook_row(row) == []


def test_validate_hook_row_enum_guards():
    """枚举兜底：乱填型别/烈度/定位、键值不一致必须被点名（卡4 风险③）"""
    bad = {"num": 0, "position": "章中", "type": "天外飞仙", "strength": "爆",
           "outline_position": "无敌", "is_event_hook": True, "event_kw": ""}
    problems = validate_hook_row(bad)
    assert any("num" in p for p in problems)
    assert any("position" in p for p in problems)
    assert any("钩型" in p for p in problems)
    assert any("期待度" in p for p in problems)
    assert any("章节定位" in p for p in problems)
    assert any("is_event_hook" in p for p in problems)
    assert validate_hook_row({"num": 1}) == []  # 缺省键按容错口径放行（position 默认章尾）


def test_extract_outline_position_normalized():
    """「章节定位：」行归一到六档枚举；带括注/变体写法不炸"""
    assert extract_outline_position(SAMPLE_OUTLINE) == "高压"
    assert extract_outline_position("- 章节定位：低压生活（本章缓冲）") == "低压生活"
    assert extract_outline_position("没有定位行") == ""


# ---------- 5. 连弱钩检测（纯函数段） ----------

def _row(num, strength="强", event=True, position="章尾", outline_position="高压"):
    return {"num": num, "position": position, "type": "悬念缺口" if event else "",
            "strength": strength, "summary": f"第{num}章钩", "event_kw": "指印" if event else "",
            "is_event_hook": event, "outline_position": outline_position}


def test_weak_hook_run_detected():
    """近 2 章全弱钩/非事件钩 → 核对级 finding（卡4：连弱钩核对级）"""
    rows = [_row(20), _row(21, strength="弱", event=True), _row(22, event=False)]
    fs = weak_hook_findings(rows)
    assert len(fs) == 1 and fs[0]["level"] == "核对级" and fs[0]["kind"] == "连弱钩"
    assert fs[0]["nums"] == [21, 22]


def test_weak_hook_run_needs_adjacent_chapters():
    """缺章即断链：章号不相邻不算连排"""
    rows = [_row(20, strength="弱", event=False), _row(23, event=False)]
    assert weak_hook_findings(rows) == []
    rows = [_row(20, strength="弱", event=False), _row(21, event=False), _row(23, event=False)]
    fs = weak_hook_findings(rows)
    assert len(fs) == 1 and fs[0]["nums"] == [20, 21]


def test_strong_event_hooks_pass_clean():
    """强事件钩连排不报；章首行不参与检测（跨章对账只看章尾行）"""
    rows = [_row(1), _row(2), _row(3, position="章首", strength="", event=False)]
    assert weak_hook_findings(rows) == []


def test_weak_run_whitelisted_in_low_pressure():
    """白名单让行：整段连弱都落在低压章（无钩是允许态）→ 不报"""
    rows = [_row(30, strength="弱", event=False, outline_position="低压生活"),
            _row(31, event=False, outline_position="信息整理")]
    assert weak_hook_findings(rows) == []


def test_weak_run_mixed_positions_still_fires():
    """白名单不豁免混排：低压章夹在高压连弱段里照样点名"""
    rows = [_row(40, strength="弱", event=False),
            _row(41, strength="中", event=False, outline_position="低压生活")]
    fs = weak_hook_findings(rows)
    assert len(fs) == 1 and fs[0]["nums"] == [40, 41]


def test_weak_hook_window_parameter():
    """窗口参数：window=3 时两章连弱不报，三章连弱报一条"""
    rows = [_row(1, event=False), _row(2, event=False)]
    assert weak_hook_findings(rows, window=3) == []
    rows.append(_row(3, strength="弱", event=True))
    fs = weak_hook_findings(rows, window=3)
    assert len(fs) == 1 and fs[0]["nums"] == [1, 2, 3]


def test_long_weak_run_single_finding():
    """长连排只报一条（区间点名），不逐章刷屏"""
    rows = [_row(n, event=False) for n in (50, 51, 52, 53, 54)]
    fs = weak_hook_findings(rows)
    assert len(fs) == 1 and fs[0]["nums"] == [50, 51, 52, 53, 54]
    assert "50-54" in fs[0]["text"]
