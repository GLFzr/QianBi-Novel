# -*- coding: utf-8 -*-
"""P4/P5：预设里填了的字段必须真的落到最终 prompt；共写口径与世界书提案边界

断链的形态永远是「UI 能填、文件里有、prompt 里没有」，所以这里测的不是解析，
而是每个字段的出口：环节特化看模板槽位，题材限量看去红线段，审校特化看审校槽。
"""
import json
import os

from app import presets as P
from app import project, prompts, wb
from app.core import co_dialogue, stages
from app.core import state as st

# stage_hints 六键 → 承载它的模板与占位符；缺一键即有人填了字却永不生效
HINT_SLOTS = {
    "core_setting": ("CORE_SETTING_PROMPT", "genre_block"),
    "outline": ("VOLUME_OUTLINE_PROMPT", "genre_block"),
    "unit_outline": ("CHAPTER_OUTLINE_PROMPT", "genre_block"),
    "prose": ("PROSE_WRITING_PROMPT", "genre_block"),
    "worldbook": ("WORLDBOOK_GEN_PROMPT", "genre_block"),
    "review": ("FINAL_REVIEW_PROMPT", "genre_review_extra"),
}

SENTINEL = {
    "style_hint": "句式甲哨兵",
    "world_rules": "世界规则乙哨兵",
    "plot_conventions": "套路节奏丙哨兵",
    "taboos": "题材禁忌丁哨兵",
    "deslop_extra": "腔调配额戊哨兵：每章最多2次",
    "review_extra": "审校专项己哨兵",
}

HINTS = {k: f"{k}特化哨兵" for k, _lab in P.STAGE_HINT_KEYS}


def _sandbox(tmp_path, monkeypatch):
    """预设落沙箱用户仓：不碰内置 JSON，也不碰真实 ~/.qianbi_novel"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    d = os.path.join(str(tmp_path), ".qianbi_novel", "presets")
    os.makedirs(d, exist_ok=True)
    data = {"id": "wired", "name": "接线预设", "version": 2,
            "stage_hints": HINTS, **SENTINEL}
    with open(os.path.join(d, "wired.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    proj = project.create_project(os.path.join(str(tmp_path), "books"), "接线书")
    st.save_state(proj, {"genre_preset": "wired"})
    return proj


def test_every_stage_hint_key_has_a_live_slot():
    assert set(HINT_SLOTS) == {k for k, _lab in P.STAGE_HINT_KEYS}
    for stage, (attr, ph) in HINT_SLOTS.items():
        assert "{%s}" % ph in getattr(prompts, attr), f"{stage} 的 {attr} 缺 {{{ph}}}"


def test_book_without_preset_keeps_placeholders_not_crash(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    proj = project.create_project(os.path.join(str(tmp_path), "books2"), "无预设书")
    assert "未启用题材预设" in stages._genre_block(proj, "core_setting")
    assert stages._genre_review_extra(proj) == "（无题材专项检查）"


def test_deslop_extra_reaches_the_dedicated_redline_slot(tmp_path, monkeypatch):
    """题材专属去味黑名单走「去 AI 味红线」段：那里同时是扩写/压缩/去味的落点"""
    proj = _sandbox(tmp_path, monkeypatch)
    line = stages._tic_blacklist(proj)
    assert SENTINEL["deslop_extra"] in line
    assert "题材专属限量" in line
    assert P.genre_block("wired").count("腔调配额戊哨兵") == 0      # 不双份注入


def test_deslop_extra_slot_exists_in_every_writing_template(tmp_path, monkeypatch):
    """四张模板都有这条槽：只补写作一张等于扩写/压缩/去味仍在裸写"""
    for attr in ("PROSE_WRITING_PROMPT", "ENRICH_PROMPT", "TRIM_PROMPT",
                 "DESLOP_REWRITE_PROMPT"):
        assert "{tic_blacklist}" in getattr(prompts, attr), attr


def test_no_preset_tic_blacklist_text_unchanged(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    proj = project.create_project(os.path.join(str(tmp_path), "books3"), "无预设书2")
    assert stages._tic_blacklist(proj) == "（样本不足，暂无）"


def test_review_slot_carries_both_v1_and_v2_genre_checks(tmp_path, monkeypatch):
    proj = _sandbox(tmp_path, monkeypatch)
    extra = stages._genre_review_extra(proj)
    assert SENTINEL["review_extra"] in extra
    assert HINTS["review"] in extra


def test_genre_block_for_injects_hint_for_every_stage(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    for stage in HINT_SLOTS:
        block = P.genre_block_for("wired", stage)
        assert HINTS[stage] in block, stage


def test_filled_shared_fields_reach_the_stage_block(tmp_path, monkeypatch):
    """环节块除特化 hint 外还带该环节该看的共享字段：正文要文风与禁忌，设定要套路"""
    _sandbox(tmp_path, monkeypatch)
    prose = P.genre_block_for("wired", "prose")
    assert SENTINEL["style_hint"] in prose and SENTINEL["taboos"] in prose
    core = P.genre_block_for("wired", "core_setting")
    assert SENTINEL["world_rules"] in core and SENTINEL["plot_conventions"] in core
    # 世界书环节只要世界规则，别把文风锚塞进登记表
    wbd = P.genre_block_for("wired", "worldbook")
    assert SENTINEL["world_rules"] in wbd and SENTINEL["style_hint"] not in wbd


def test_cw_prose_reference_block_demands_must_self_check(tmp_path, monkeypatch):
    """P5-a：共写正文只平铺正则不够，必须要求逐条 must 给落点"""
    proj = _sandbox(tmp_path, monkeypatch)
    block = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "wired", 1)
    assert "must 级自检" in block
    assert block.index("【正则约束】") < block.index("must 级自检") < block.index("【角色状态】")


def test_worldbook_proposal_never_enters_activated_view(tmp_path, monkeypatch):
    """P5-b：修正提案是待裁决队列，不是事实——不得进任何装配/激活口径"""
    from app.core import memory
    proj = _sandbox(tmp_path, monkeypatch)
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH),
                       "# 世界书\n\n## 实体登记\n\n### 陈更\n- 身份：当铺学徒\n")
    project.write_file(os.path.join(proj, memory.PROPOSAL_PATH),
                       "# 世界书修正提案\n\n### 幽灵实体丙\n- 身份：提案里才有的角色\n"
                       "- 建议：正文已把陈更写成掌柜，请核对\n")
    for budget in (2000, 160):
        assert "幽灵实体丙" not in project.worldbook_text(proj, budget, num=1)
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    activated = wb.assemble(proj, num=1, doc=doc)
    assert "幽灵实体丙" not in activated["text"]
    names = [e["name"] for e in activated["activated"]]
    assert "陈更" in names and "幽灵实体丙" not in names
