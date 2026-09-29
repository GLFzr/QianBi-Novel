# -*- coding: utf-8 -*-
"""A11：w1_ux 摩擦点四件 S 级小修的行为钉（w1_ux §2.a 缺口①④ + §3 附加两行）。

① 导出工具条 tooltip 虚标 md（对话框实为 txt/epub 两档）——tooltip 无 md；
② 「去一下AI味」动词与宾语隔「一下」不再漏解析（旧规则必 None 落成普通聊天）；
③ 「看看当前章正文」不再被老 read_chapter（读磁盘定稿）先吃，归 cw_read_chapter；
④ 自动档 Console 派发 cw_outline_validate / cw_idea_save 不再绕过共写档守卫
   （旧：回「请先回到单元细纲阶段」「点确定进入核心设定」——自动档没有这些按钮）。
全部离线，不发任何网络请求。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import agent_tools  # noqa: E402

QML_MAIN = os.path.join(ROOT, "app", "ui", "qml", "Main.qml")


# ---------- ① 导出 tooltip 虚标 md（w1_ux §3⑧导出行，验收口径：tooltip 无 md） ----------

def test_export_tooltip_no_md_claims():
    src = open(QML_MAIN, encoding="utf-8").read()
    # 导出按钮的 ToolTip.text 字符串本体（注释不计入）
    tips = re.findall(r'ToolTip\.text:\s*"([^"]*)"', src)
    export_tip = [t for t in tips if "导出全本" in t]
    assert export_tip, "导出按钮 tooltip 丢失（U-20：图标钮必配提示）"
    tip = export_tip[0]
    assert "md" not in tip, f"导出 tooltip 仍虚标 md（对话框只有 txt/epub 两档）：{tip}"
    assert "txt" in tip and "epub" in tip, f"tooltip 应如实标注 txt/epub 两档：{tip}"


def test_export_dialog_offers_exactly_txt_epub():
    """钉住「如实」的另一半：导出对话框格式档就是 txt/epub（tooltip 与之对齐）。"""
    src = open(QML_MAIN, encoding="utf-8").read()
    assert '"epub（阅读器通用）", v: "epub"' in src, "导出对话框 epub 档丢失"
    assert '"txt（平台上传标准）", v: "txt"' in src, "导出对话框 txt 档丢失"
    assert 'v: "md"' not in src, "导出对话框冒出 md 档——请回改 tooltip 三方对账"


# ---------- ② 「去一下AI味」不再漏解析（w1_ux §2.a 缺口④） ----------

def test_deslop_with_yixia_variant_parses():
    instr = agent_tools.parse_instruction("去一下AI味", default_chapter=3)
    assert instr is not None, "「去一下AI味」解析为 None——隔「一下」的口语仍是死区"
    assert instr[0] == "cw_deslop" and instr[1] == {} and instr[2] == "guess"


def test_deslop_variants_still_parse():
    for text in ["给这章去味", "去AI味", "去 AI 味", "跑一轮去AI味", "去一下味"]:
        instr = agent_tools.parse_instruction(text, default_chapter=3)
        assert instr is not None and instr[0] == "cw_deslop", \
            f"「{text}」应落 cw_deslop，实际 {instr}——一下变体收口误伤旧口径"


def test_deslop_forced_slash_exact():
    instr = agent_tools.parse_instruction("/去一下AI味", default_chapter=3)
    assert instr is not None and instr[0] == "cw_deslop" and instr[2] == "exact"


# ---------- ③ 「看看当前章正文」归 cw_read_chapter（w1_ux §2.a 缺口①） ----------

def test_current_chapter_reading_goes_to_cw_read_chapter():
    for text in ["看看当前章正文", "读一下当前章", "把当前章正文贴到对话里"]:
        instr = agent_tools.parse_instruction(text, default_chapter=3)
        assert instr is not None and instr[0] == "cw_read_chapter" and instr[1] == {}, \
            f"「{text}」应落 cw_read_chapter（读共写当前稿），实际 {instr}——老 read_chapter 又先吃了"


def test_current_chapter_forced_slash_exact():
    instr = agent_tools.parse_instruction("/看看当前章正文", default_chapter=3)
    assert instr is not None and instr[0] == "cw_read_chapter" and instr[2] == "exact"


def test_numbered_chapter_reading_still_read_chapter():
    """负向不越界：带章号的查看话术仍落老 read_chapter（w1_ux：注释意图「只认当前章」）。"""
    instr = agent_tools.parse_instruction("看看第3章正文", default_chapter=0)
    assert instr is not None and instr[0] == "read_chapter" and instr[1] == {"chapter": 3}


# ---------- ④ 自动档 Console 不再绕过共写档守卫（w1_ux §3 附加行） ----------

def _make_bridge():
    from app.ui.bridge import Bridge
    return Bridge()


def test_auto_mode_console_stage_bound_tools_get_mode_guidance(tmp_path, monkeypatch):
    """自动档（无 cw.mode 落盘）Console 说「细纲体检/记一下选题想法」：
    不得进共写阶段机（旧回执「请先回到单元细纲阶段」「点确定进入核心设定」错位），
    必须落共写档守卫的档位指路。"""
    bridge = _make_bridge()
    bridge.proj = str(tmp_path)          # 目录不存在 ⇒ raw_cw_mode="" ⇒ auto（R17 老项目口径）
    called = []
    monkeypatch.setattr(bridge, "validateCwOutlines", lambda: called.append("validate"))
    monkeypatch.setattr(bridge, "saveCwIdeaInfo", lambda *a: called.append("idea_save"))
    toasts = []
    bridge.toast.connect(lambda kind, msg: toasts.append((kind, msg)))

    for name in ("cw_outline_validate", "cw_idea_save"):
        bridge._ui_tool_dispatch(name)
        assert called == [], f"{name} 在自动档仍被派发进共写阶段机"
        assert toasts and toasts[-1][0] == "warn" and "共写档" in toasts[-1][1], \
            f"{name} 自动档回执不是档位指路：{toasts}"


def test_cw_mode_stage_bound_tools_still_dispatch(monkeypatch):
    """对照：共写档下两支照常真实派发（守卫收口不得误伤共写档可用性）。"""
    bridge = _make_bridge()
    monkeypatch.setattr(bridge, "_get_cw_mode", lambda: "cw")
    called = []
    monkeypatch.setattr(bridge, "validateCwOutlines", lambda: called.append("validate"))
    monkeypatch.setattr(bridge, "saveCwIdeaInfo", lambda *a: called.append("idea_save"))

    import app.ui.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod.project, "read_idea_info",
                        lambda p: {"genre": "都市", "platform": "番茄", "idea": "x",
                                   "total_words_wan": 100})
    bridge._ui_tool_dispatch("cw_outline_validate")
    bridge._ui_tool_dispatch("cw_idea_save")
    assert called == ["validate", "idea_save"], f"共写档下派发断链：{called}"


def test_cross_mode_tools_still_work_in_auto_mode(tmp_path, monkeypatch):
    """跨档两支（世界观对账/读当前章）不受守卫收口影响：自动档仍直派。"""
    bridge = _make_bridge()
    bridge.proj = str(tmp_path)
    called = []
    monkeypatch.setattr(bridge, "runCanonAudit", lambda: called.append("audit"))
    monkeypatch.setattr(bridge, "readFileText", lambda: "正文样本")
    bridge.logModel.append = lambda *a, **k: called.append("log")

    bridge._ui_tool_dispatch("cw_canon_audit")
    bridge._ui_tool_dispatch("cw_read_chapter")
    assert called == ["audit", "log"], f"跨档工具被守卫误伤：{called}"
