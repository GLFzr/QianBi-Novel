# -*- coding: utf-8 -*-
"""B-2(4) 离线夹具先行：切换矩阵 docs/共写切换矩阵_B2_v1.md 的论断逐条钉死。

零请求、零 Qt 事件循环（CoWriting 自述"纯状态与文件逻辑，可脱离 Qt 单测"）。
状态点 ≥8：空项目 / 六阶段逐点（project/core/outline/worldbook/unit/prose）/
中途有定稿章 / cw→auto 指针保留 / auto→cw→cw 往返原地续跑。
矩阵表若再改动行为，这里必须先改出红。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import project  # noqa: E402
from app.core import state as st  # noqa: E402
from app.core import co_writing  # noqa: E402


def _mkproj(tmp_path, name, files=None, state=None):
    proj = tmp_path / name
    (proj / "设定").mkdir(parents=True)
    (proj / "大纲").mkdir()
    for rel, text in (files or {}).items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if state is not None:
        (proj / "pipeline_state.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return str(proj)


def _resume(tmp_path, name, files=None, state=None):
    """造项目 → 跑 auto→cw 迁移 → 返回 (state, cw dict)。"""
    proj = _mkproj(tmp_path, name, files, state)
    s = {"stage": "prose", "total_chapters": 0}
    s.update(state or {})
    cw = co_writing.CoWriting(proj).migrate_mode(s, to_cw=True)
    return s, cw


# ---------- §一 自动 → 共写：_resume_stage 按产物存在性逐点 ----------

def test_empty_project_resumes_at_project_stage(tmp_path):
    """状态点·空项目：什么产物都没有 → 从创建项目开始。"""
    _, cw = _resume(tmp_path, "empty")
    assert cw["stage"] == st.STAGE_CW_PROJECT


def test_idea_info_only_resumes_at_core(tmp_path):
    """状态点·cw_core：只有选题信息 → 创建项目视为完成，停在核心设定。"""
    _, cw = _resume(tmp_path, "idea_only", {"设定/选题信息.md": "灵感：测试"})
    assert cw["stage"] == st.STAGE_CW_CORE


def test_auto_settings_survive_not_reasked(tmp_path):
    """§一 row1-2：自动档的题材定位被 cw 视为已完成——不会被重问设定
    （设定齐、独缺大纲 ⇒ 直落剧情总大纲阶段，跳过核心设定）。"""
    _, cw = _resume(tmp_path, "auto_prefix", {
        "设定/选题信息.md": "灵感：测试",
        "设定/题材定位.md": "题材定位",
    })
    assert cw["stage"] == st.STAGE_CW_OUTLINE, (
        "已有设定的自动档项目进共写被重问设定——§一「保留 ✓」失真")
    assert cw["reopening"] == ""


def test_outline_without_worldbook_stops_at_worldbook(tmp_path):
    """§一 row4 ⚠：自动档从不需要世界书 → 进 cw 停在世界书阶段（新增作业，须知情）。"""
    _, cw = _resume(tmp_path, "no_wb", {
        "设定/选题信息.md": "灵感：x", "设定/题材定位.md": "s", "大纲/大纲.md": "o",
    })
    assert cw["stage"] == st.STAGE_CW_WORLDBOOK


def test_worldbook_needs_both_files(tmp_path):
    """世界书阶段全件齐才过：只有世界书.md 缺正则.md → 仍停在 cw_worldbook。"""
    _, cw = _resume(tmp_path, "wb_half", {
        "设定/选题信息.md": "灵感：x", "设定/题材定位.md": "s", "大纲/大纲.md": "o",
        "设定/世界书.md": "wb",
    })
    assert cw["stage"] == st.STAGE_CW_WORLDBOOK


def test_worldbook_done_resumes_at_unit(tmp_path):
    """状态点·cw_unit：世界书+正则齐 → 停在单元细纲。"""
    _, cw = _resume(tmp_path, "wb_done", {
        "设定/选题信息.md": "灵感：x", "设定/题材定位.md": "s", "大纲/大纲.md": "o",
        "设定/世界书.md": "wb", "设定/正则.md": "rg",
    })
    assert cw["stage"] == st.STAGE_CW_UNIT


def test_locked_chapter_lands_prose_and_stays_terminal(tmp_path):
    """§一 row5 + 状态点·cw_prose/中途有定稿章：锁定章可见、锁定语义保留、cw_prose 终态。"""
    proj = _mkproj(tmp_path, "locked_mid", {
        "设定/选题信息.md": "灵感：x", "设定/题材定位.md": "s", "大纲/大纲.md": "o",
        "设定/世界书.md": "wb", "设定/正则.md": "rg", "大纲/单元总纲.md": "u",
        "正文/第1章.md": "第一章正文",
    })
    project.set_chapter_locked(proj, 1, True)
    assert project.is_chapter_locked(proj, 1)
    s = {"stage": "prose", "total_chapters": 0}
    cw = co_writing.CoWriting(proj).migrate_mode(s, to_cw=True)
    assert cw["stage"] == st.STAGE_CW_PROSE, "已有全套产物+定稿章应直达正文写作阶段"
    assert st.CW_NEXT[st.STAGE_CW_PROSE] == st.STAGE_CW_PROSE, "cw_prose 必须是终态"
    # 锁定语义在 cw 侧同一个 project.py 读取（confirmChapterLocked 拒绝重复锁的前提）
    assert project.is_chapter_locked(proj, 1)


# ---------- §二 共写 → 自动：migrate 只改 mode，其余全保留 ----------

def test_cw_to_auto_preserves_pointer_transcript_totals(tmp_path):
    """§二 row6-7 + total 行：cw→auto 不动 stage 指针、转写、total_chapters
    （总章数不被 cw 单元规划静默迁移——文档明示的断点，行为必须保持可预期）。"""
    proj = _mkproj(tmp_path, "cw_out", state={
        "cw": {"mode": "cw", "stage": "cw_unit",
               "transcript": {"cw_unit": [{"role": "user", "text": "单元讨论"}]}},
        "total_chapters": 0,
    })
    s = st.load_state(proj)
    cw = co_writing.CoWriting(proj).migrate_mode(s, to_cw=False)
    assert cw["mode"] == "auto"
    assert cw["stage"] == "cw_unit", "cw→auto 不得动 stage 指针（可回得去的前提）"
    assert cw["transcript"], "共写转写不得被切换清空"
    assert s.get("total_chapters", 0) == 0, "cw 单元规划不得被静默迁移成总章数（§三.3 另行裁决）"


def test_migrate_never_touches_auto_stage(tmp_path):
    """§一 row6-7：migrate 双向都不写 state['stage']（自动档 run() 按产物重推断）。"""
    proj = _mkproj(tmp_path, "stage_untouched", state={"stage": "ch_outline"})
    s = st.load_state(proj)
    cwmod = co_writing.CoWriting(proj)
    cwmod.migrate_mode(s, to_cw=True)
    assert s["stage"] == "ch_outline"
    cwmod.migrate_mode(s, to_cw=False)
    assert s["stage"] == "ch_outline", "切回自动档时 migrate 不得改写 state['stage']"


def test_roundtrip_resumes_in_place_reopen_cleared(tmp_path):
    """§二 row6「原地续跑（含 reopening 清空）」：cw_unit 进行中（单元总纲未落盘）
    → 切自动再切回 → 仍停在 cw_unit；reopening 回看态被清空；转写保留。"""
    proj = _mkproj(tmp_path, "roundtrip", {
        "设定/选题信息.md": "灵感：x", "设定/题材定位.md": "s", "大纲/大纲.md": "o",
        "设定/世界书.md": "wb", "设定/正则.md": "rg",
    }, state={
        "cw": {"mode": "cw", "stage": "cw_unit", "reopening": "cw_prose",
               "transcript": {"cw_unit": [{"role": "assistant", "text": "讨论中"}]}},
    })
    s = st.load_state(proj)
    cwmod = co_writing.CoWriting(proj)
    cwmod.migrate_mode(s, to_cw=False)
    cw = cwmod.migrate_mode(s, to_cw=True)
    assert cw["stage"] == "cw_unit", "往返后未原地续跑（指针被产物推断带偏）"
    assert cw["reopening"] == "", "回看中切换必须清 reopening（文档明示行为）"
    assert cw["transcript"], "往返后转写丢失"


def test_auto_never_consumes_unit_outline(tmp_path):
    """§二 row3：单元总纲是 cw 专属产物，自动档路径零消费（静态钉）。"""
    for rel in ("app/core/orchestrator.py", "app/core/stages.py",
                "app/deslop.py", "app/export.py"):
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            src = f.read()
        assert "单元总纲" not in src, (
            f"{rel} 出现「单元总纲」——cw 专属产物被自动档消费，§二 row3 失真")
