# -*- coding: utf-8 -*-
"""B-1(4)：UI_TOOLS 共写动作的话术可达性护栏。

背景：UI_TOOLS 注册了 9 支共写界面动作，bridge 派发面（_ui_tool_dispatch）能处理，
但若规则层与 LLM 白名单都不产出这些名字，它们就是「注册了却永远够不着」的死工具。
本夹具全部离线（打桩 client，不发任何网络请求）：
① 对 UI_TOOLS 每一支，断言 parse_instruction 的关键词规则能产出该名字（/ 强制也通）；
② 规则名 ↔ bridge 派发面分支名逐字对账（改派发面分支名而不同步规则 ⇒ 红）；
③ parse_instruction_llm 白名单放行 UI_TOOLS、白名单外仍拒绝；
④ 共写词接线不吃掉流水线老话术（回退/重跑/读章/设置开关的回归钉）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import agent_tools  # noqa: E402

# UI_TOOLS 每支工具至少两条离线规则短语（与 parse_instruction 尾部关键词块一一对应）
PHRASES = {
    "cw_canon_audit": ["跑一次世界观对账", "做一下设定一致性审查"],
    "cw_read_chapter": ["读一下当前章", "把当前章贴到对话里"],
    "cw_outline_validate": ["细纲体检一下", "校验一下这批细纲衔接"],
    "cw_idea_save": ["记个想法：女主早点出场", "保存选题信息"],
    "cw_prose_to_editor": ["把草案落稿到编辑器", "把草案放进编辑器"],
    "cw_deslop": ["给这章去味", "跑一轮去AI味"],
    "cw_review": ["审校一下这章正文", "帮我审一下"],
    "cw_generate_draft": ["帮我写正文", "生成一份草案"],
    "cw_rollback_stage": ["回到细纲阶段", "退回上一阶段"],
}


class _StubClient:
    def __init__(self, raw):
        self.raw = raw

    def chat(self, prompt, **kw):
        return self.raw


def test_phrase_table_covers_every_ui_tool():
    assert set(PHRASES) == set(agent_tools.UI_TOOLS), \
        "PHRASES 与 UI_TOOLS 不对账——新注册的 UI 工具必须补离线可达短语"


def test_every_ui_tool_reachable_by_rules():
    for name, phrases in PHRASES.items():
        for text in phrases:
            instr = agent_tools.parse_instruction(text, default_chapter=7)
            assert instr is not None and instr[0] == name, \
                f"「{text}」未解析为 {name}（got {instr}）——规则与派发面断链"


def test_forced_slash_hits_ui_tools_exact():
    for name, phrases in PHRASES.items():
        hits = []
        for text in phrases:
            instr = agent_tools.parse_instruction("/" + text, default_chapter=7)
            if instr and instr[0] == name and instr[2] == "exact":
                hits.append(text)
        # 每支工具至少一条 / 短语可达即可（个别短语被优先级更高的老规则接走是既有设计，
        # 如 /读一下当前章 → read_chapter）
        assert hits, f"{'、'.join(phrases)} 无任何一条能以 / 指令强制命中 {name}"


def test_ui_tools_parse_without_args():
    for phrases in PHRASES.values():
        instr = agent_tools.parse_instruction(phrases[0], default_chapter=7)
        assert instr[1] == {}, f"「{phrases[0]}」不该带参数：{instr[1]}"


def test_rule_names_match_bridge_dispatch_branches():
    """规则产出的名字必须逐字出现在 bridge 派发面分支里，否则命中后无人接管。"""
    src = open(os.path.join(ROOT, "app", "ui", "bridge.py"), encoding="utf-8").read()
    for name in agent_tools.UI_TOOLS:
        assert ('"%s"' % name) in src, f"{name} 未在 bridge 派发面接线（注册了没人执行）"
        assert ("_ui_tool_dispatch" in src), "派发面入口丢失"


def test_llm_whitelist_admits_ui_tools_and_still_rejects_stray():
    raw = json.dumps({"tool": "cw_canon_audit", "confidence": 0.9}, ensure_ascii=False)
    got = agent_tools.parse_instruction_llm("跑一下对账", _StubClient(raw))
    assert got and got[0] == "cw_canon_audit" and got[1] == {} and got[2] == "llm"
    # 白名单外仍然拒（变异「把 UI_TOOLS 从白名单摘掉」在上一断言红）
    assert agent_tools.parse_instruction_llm(
        "x", _StubClient('{"tool": "format_disk", "confidence": 0.99}')) is None
    assert agent_tools.parse_instruction_llm(
        "x", _StubClient('{"tool": "cw_deslop", "confidence": 0.3}')) is None


def test_rules_do_not_hijack_pipeline_phrases():
    """共写词接线排在常规规则之后：流水线老话术必须照旧落老 TOOLS。"""
    for text, tool in [
        ("回退到去味之前", "rollback_step"),
        ("重跑第4章审校", "rollback_step"),
        ("重写草稿", "rollback_step"),
        ("看看第3章正文", "read_chapter"),
        ("重新生成第3章的细纲", "regen_outline"),
        ("关闭人工审校", "set_setting"),
    ]:
        instr = agent_tools.parse_instruction(text, default_chapter=5)
        assert instr is not None and instr[0] == tool, \
            f"「{text}」应落老工具 {tool}，实际 {instr}——共写关键词抢了流水线话术"
