# -*- coding: utf-8 -*-
"""A8 开幕轮密度压缩回归（cost.a8_opening_compress，L5-A1 成本线）

- 缺省 False：章会话/卷会话开幕轮装配与 0.19.x 逐字节一致（变量隔离纪律；
  off 全链路由 tests/probe_prompt_baseline.py 的零漂移基线兜底）；
- 开启：开幕轮里与 system 前缀重复的三个指令性槽位（全局写作纪律/正则契约/
  世界书常驻）收敛为短引用；卷会话（跨章历史已含前情正文）开幕章头再跳
  与历史逐字重复的三节（S4-b volume_mode 同款语义）。章级动态变量全保留。
- 装配层字节测量：真实模板 + 真实尺寸夹具书，写死期望区间（口径=仓库既有
  han_tokens，中文字符×0.6）。

台账口径的诚实声明（写入断言注释）：台账 -5~8k tok/章 立项于 S4 落地前；其中
指令体大头已由 s4_static_freeze 兑现，细纲引用化属 A12 已否证项（近场保留）。
A8 在不违反 A12、不与 S4 重复的前提下，可去重空间以本测试实测为准（约 2k
han-tok/章 夹具口径；真实书随正则/世界书体量浮动）。S4/head_rebuild 模式的
开幕轮已是压缩形态，本开关在该模式下 no-op。
"""
import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

_FH = tempfile.mkdtemp(prefix="qbn_test_a8_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH

import app.prompts as prompts
from app.prompts.writing import PROSE_WRITING_PROMPT
from app import config
from app import project
from app.core import stages
from app.core.shared_prefix import chapter_header
from app.core.history_compaction import han_tokens
from app.core.stages import _a8_compress_enabled, _a8_opening_prose_kw

_CFG_ON = {"cost": {"a8_opening_compress": True}}


# ---------------- 开关缺省态与纯函数 ----------------

def test_default_config_switch_off():
    assert config.DEFAULT_CONFIG["cost"]["a8_opening_compress"] is False
    assert _a8_compress_enabled({}) is False
    assert _a8_compress_enabled({"writing": {"volume_session": True}}) is False, \
        "A8 挂独立 cost 键，不受 writing 区任何旗标影响"
    assert _a8_compress_enabled(_CFG_ON) is True


def test_prose_kw_substitution_only_touches_duplicated_slots():
    """三个与 system 前缀重复的指令性槽位 → 短引用；其余 kwargs 原样；不改调用方"""
    kw = {"style_discipline": "STYLE", "regex_block": "REGEX", "worldbook_block": "WB",
          "chapter_header": "章头", "word_target": 3000}
    snapshot = dict(kw)
    out = _a8_opening_prose_kw(kw)
    assert kw == snapshot, "纯函数不得改调用方"
    assert out is not kw
    assert out["style_discipline"] == stages._A8_STYLE_REF
    assert out["regex_block"] == stages._A8_REGEX_REF
    assert out["worldbook_block"] == stages._A8_WB_REF
    for k, v in kw.items():
        if k not in ("style_discipline", "regex_block", "worldbook_block"):
            assert out[k] == v, "非重复槽位不得被动：%s" % k
    for ref in (stages._A8_STYLE_REF, stages._A8_REGEX_REF, stages._A8_WB_REF):
        assert "以系统" in ref and "为准" in ref, "引用行必须指向 system 既有节"


# ---------------- 章头：off 三节保留 / 卷会话 on 三节收敛 ----------------

def _mk_proj(tmp_root):
    """真实尺寸夹具书（体量对齐真机书：世界书 25 实体 + 24 条正则 + 前情正文）"""
    proj = pathlib.Path(tmp_root) / "p"
    for d in ("设定", "大纲", "正文", "追踪"):
        (proj / d).mkdir(parents=True)
    (proj / "设定" / "题材定位.md").write_text("# 设定\n主角：陈默\n" * 20, encoding="utf-8")
    wb = "\n".join("### 角色%02d\n- 身份：当铺相关人物%02d，与主角有债务或账目往来\n"
                   "- 约束：不能说谎\n" % (i, i) for i in range(1, 26))
    (proj / "设定" / "世界书.md").write_text(
        "# 世界书\n\n## 实体登记\n\n" + wb +
        "\n## 追加登记\n\n- **第九指**（道具）：可替持有者承担一次改写代价 ｜ 首见第2章\n",
        encoding="utf-8")
    (proj / "设定" / "正则.md").write_text(
        "# 正则约束\n\n" + "\n".join(
            "- 规则：第%d条 不得出现套路化描写示例规则文本，违者算硬伤。" % i
            for i in range(1, 25)), encoding="utf-8")
    (proj / "大纲" / "大纲.md").write_text("# 大纲\n### 第1卷（第1-10章）\n", encoding="utf-8")
    (proj / "大纲" / "细纲_第002章.md").write_text(
        "### 第 2 章：查账\n- 核心事件：陈默查账发现缺口\n"
        + "- 情节点：示例情节点文本，用于撑起真实细纲体量。" * 30, encoding="utf-8")
    (proj / "正文" / "第001章_开局.md").write_text(
        "# 第1章 开局\n\n" + "陈默把当票压在柜台上，柳三更没有抬头。"
        "子时的灯灭了三次，账本上多出一行不属于任何人的字。" * 30, encoding="utf-8")
    (proj / "追踪" / "角色状态.md").write_text(
        "## 陈默\n- **当前身份**：调查员\n- **状态变更记录**：\n  - 第1章：开局\n" * 8,
        encoding="utf-8")
    (proj / "追踪" / "时间线.md").write_text("第1章：子时清账夜\n" * 40, encoding="utf-8")
    (proj / "追踪" / "伏笔.md").write_text(
        "| 伏笔 | 状态 | 登记章 |\n|---|---|---|\n| 指印 | 未回收 | 1 |\n", encoding="utf-8")
    (proj / "追踪" / "章节摘要.md").write_text(
        "# 章节摘要链\n\n> 每章一句话摘要，按章号追加。\n\n"
        + "- 第1章《开局》：陈默典当三日记忆，柳三更查账发现缺口。\n"
        "- 第2章《查账》：缺口对上了当票的第三枚指印。\n", encoding="utf-8")
    (proj / "追踪" / "全局摘要.md").write_text(
        "全书主线：陈默以记忆为代价改写账本，柳三更逐章逼近真相。\n", encoding="utf-8")
    proj_s = str(proj)
    project.write_idea_info(proj_s, "都市悬疑", "番茄", "测试灵感", 30)
    from app.core import state as st_
    st_.save_state(proj_s, {"genre_preset": "urban_destiny", "total_chapters": 10})
    return proj_s


def test_volume_mode_header_drops_history_duplicated_sections():
    """A8 卷会话开幕（volume_mode=True）：三节收敛，章级动态变量保留"""
    proj = _mk_proj(tempfile.mkdtemp(prefix="qbn_a8_hdr_"))
    off = chapter_header(proj, 2)
    on = chapter_header(proj, 2, volume_mode=True)
    for sec in ("最近章节摘要", "上一章结尾", "上一章开头"):
        assert sec in off, "off（历史重复节保留）：%s" % sec
        assert sec not in on, "on（与跨章历史逐字重复的三节收敛）：%s" % sec
    for sec in ("本章细纲", "全局摘要", "角色状态", "时间线", "待回收/推进伏笔"):
        assert sec in on, "章级动态变量必须保留：%s" % sec


# ---------------- 装配层字节测量（真实模板 + 真实尺寸夹具，写死区间） ----------------

def test_opening_turn_assembly_delta_meets_calibrated_floor():
    """开幕轮 off vs on 的装配字节差（S1 卷会话口径：三槽引用化 + 三节收敛）。

    写死期望区间 [1800, 2600] han-tok（夹具实测 1965，口径=中文字符×0.6）。
    下限跌破 = 压缩失效；上限突破 = 夹具或实现漂移，需重新校准本区间。
    台账 -5~8k 口径差归因见文件头（S4 已兑现大头 + A12 禁动细纲近场）。
    """
    proj = _mk_proj(tempfile.mkdtemp(prefix="qbn_a8_delta_"))
    from app import wb as wb_mod
    wb_block = wb_mod.assemble(proj, num=2, budget=2000,
                               anchors=project.worldbook_anchors(proj, 2))["text"]
    kw_off = {
        "chapter_num": 2, "next_chapter_brief": "下一章预告文本。" * 6,
        "user_guidance": "无特殊指导", "user_ideas": "（无）", "word_target": 3000,
        "tic_blacklist": "黑名单词若干", "used_setpieces": "（无）",
        "project_header": "【项目设定基准】", "chapter_header": chapter_header(proj, 2),
        "style_discipline": prompts.STYLE_DISCIPLINE,
        "worldbook_block": wb_block,
        "regex_block": project.regex_block(proj, "logic"),
        "craft_block": "工艺路线文本。", "author_note": "（无）",
    }
    kw_on = _a8_opening_prose_kw(kw_off)
    off = prompts.session_turn_text(PROSE_WRITING_PROMPT).format(**kw_off) \
        + "\n\n" + chapter_header(proj, 2)
    on = prompts.session_turn_text(PROSE_WRITING_PROMPT).format(**kw_on) \
        + "\n\n" + chapter_header(proj, 2, volume_mode=True)
    assert off != on
    delta = han_tokens(off) - han_tokens(on)
    assert 1800 <= delta <= 2600, "A8 装配字节差实测 %d，超出校准区间" % delta
    # 收敛的必须恰是重复内容；动态值与细纲近场一字不动
    assert prompts.STYLE_DISCIPLINE not in on
    assert "## 本章细纲" in on and "## 角色状态" in on
    assert "按写作指令库" not in on, "A8 不是 S4：指令体仍随开幕轮发给未开 S4 的会话"


def test_wiring_guard_in_stages_source():
    """装配接线护栏：prose 会话分支必须挂 _a8_opening_prose_kw 与 volume_mode=_a8_on"""
    import re
    src = open(os.path.join(os.path.dirname(stages.__file__), "stages.py"),
               encoding="utf-8").read()
    assert "_a8_opening_prose_kw(prose_kw)" in src
    assert "volume_mode=_a8_on" in src
