# -*- coding: utf-8 -*-
"""信息壁垒全量破除回归：统一章锚定 / 共写 worker 上下文 / 派活契约 / 模板冒烟"""
import os
import string

from app import prompts, project
from app.core import co_dialogue, memory, state as st


# ---- 夹具：ch1/ch3 存在（缺 ch2），细纲 1-3 齐备 ----

def _mk_proj(tmp_path):
    proj = str(tmp_path)
    prose = os.path.join(proj, "正文")
    outlines = os.path.join(proj, "大纲")
    os.makedirs(prose)
    os.makedirs(outlines)
    with open(os.path.join(prose, "第001章_甲.md"), "w", encoding="utf-8") as f:
        f.write("# 第1章 甲\n" + "第一章内容铺垫。" * 40 + "第一章结尾钩子。")
    with open(os.path.join(prose, "第003章_丙.md"), "w", encoding="utf-8") as f:
        f.write("# 第3章 丙\n第三章开头承接。" + "第三章正文。" * 40)
    for n, ev in [(1, "甲事件"), (2, "乙事件（缺口章）"), (3, "丙事件")]:
        with open(os.path.join(outlines, f"细纲_第{n:03d}章.md"), "w", encoding="utf-8") as f:
            f.write(f"核心事件：{ev}\n故事内容：略。")
    st.save_state(proj, {"current_chapter": 3, "total_chapters": 10})
    return proj


# ---- 统一章锚定基座 ----

def test_nearest_chapter_before_gap(tmp_path):
    proj = _mk_proj(tmp_path)
    prev = project.nearest_chapter_before(proj, 2)
    assert prev and prev[0] == 1                      # 缺口章的上一章 = ch1（不是磁盘最后章）
    assert project.nearest_chapter_before(proj, 1) is None
    prev3 = project.nearest_chapter_before(proj, 3)
    assert prev3 and prev3[0] == 1


def test_prev_chapter_pack_gap(tmp_path):
    from app.core import stages
    proj = _mk_proj(tmp_path)
    ending, sample = stages.prev_chapter_pack(proj, 2, tail=800)
    assert "第一章结尾钩子" in ending
    assert sample.startswith("第一章内容铺垫")        # 文风样本跳过标题行
    assert stages.prev_chapter_pack(proj, 1) == ("", "")


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply

    def chat_stream(self, prompt, on_chunk=None, **kw):
        return self.reply

    def chat(self, prompt, **kw):
        return self.reply


class _FakeRouter:
    def __init__(self, reply=""):
        self._c = _FakeClient(reply)

    def client(self, slot):
        return self._c


def test_outline_batch_worker_anchors_prev_chapter(tmp_path):
    """滚动细纲批：上一章结尾 = 小于批首章的最近存在章（补写中间单元不再误报第一章）"""
    proj = _mk_proj(tmp_path)
    w = co_dialogue.OutlineBatchWorker({}, proj, [2], {"start": 2, "target_end": 6},
                                       router=_FakeRouter(""))
    w.run()   # 空回复 → 解析失败走 error，但 last_prompt 已可断言
    assert "第一章结尾钩子" in w.last_prompt
    assert "（本章为第一章）" not in w.last_prompt


def test_review_outlines_worker_anchors_prev_chapter(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.ReviewOutlinesWorker({}, proj, [2], {"start": 2, "target_end": 6},
                                         router=_FakeRouter(""))
    w.run()
    assert "第一章结尾钩子" in w.last_prompt
    assert "（本章为第一章）" not in w.last_prompt


# ---- Supervisor：本章细纲 + 工作副本覆盖 + 章号锚定 ----

def test_supervisor_outline_injection_and_num_anchor(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.SupervisorWorker({}, proj, 3, router=_FakeRouter("报告。"))
    w.run()
    assert "丙事件" in w.last_prompt                  # 本章细纲已注入
    assert "第 3 章" in w.last_prompt                 # 章号锚定行


def test_supervisor_editor_working_copy_override(tmp_path):
    """定稿时正文还在编辑器没落盘：传工作副本应覆盖磁盘基准"""
    proj = _mk_proj(tmp_path)
    w = co_dialogue.SupervisorWorker({}, proj, 2, router=_FakeRouter("报告。"),
                                     chapter_text="# 第2章 乙（工作副本）\n编辑器里的未保存正文。")
    w.run()
    assert "编辑器里的未保存正文" in w.last_prompt
    assert "尚在工作副本中" not in w.last_prompt


def test_supervisor_missing_chapter_placeholder(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.SupervisorWorker({}, proj, 2, router=_FakeRouter("报告。"))
    w.run()
    assert "乙事件（缺口章）" in w.last_prompt        # 缺口章也有细纲锚点


# ---- Readback：章号 + 本章细纲 ----

def test_readback_num_and_outline(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.ReadbackWorker({}, proj, 3, "旧文本。" * 20, "新文本。" * 20,
                                   router=_FakeRouter("揣摩。"))
    w.run()
    assert "第 3 章" in w.last_prompt
    assert "丙事件" in w.last_prompt


# ---- parse_supervisor_report：三种形态 + 兜底 ----

def test_parse_report_pass():
    text = "### 主 Agent 报告\n- 衔接：OK\n- 结论：通过（无需改动）"
    assert co_dialogue.parse_supervisor_report(text) == (False, "")


def test_parse_report_needs_fix_with_directive():
    text = ("- 衔接：断裂\n- 结论：需调整（开头未承接上章结尾）\n"
            "- 【改写指令】把开头 300 字改为承接赵乾登门，\n"
            "  续行内容并入指令。\n- 其他：无")
    needs_fix, directive = co_dialogue.parse_supervisor_report(text)
    assert needs_fix is True
    assert "承接赵乾登门" in directive and "续行内容并入指令" in directive
    assert "其他" not in directive                    # 下一个列表项截断


def test_parse_report_needs_fix_without_directive():
    text = "- 结论：需调整（问题存在但未给指令）"
    assert co_dialogue.parse_supervisor_report(text) == (True, "")


def test_parse_report_no_conclusion_line():
    """解析失败 = 不猜，自动链停"""
    assert co_dialogue.parse_supervisor_report("一段没有结论行的自由文本") == (False, "")


# ---- memory：伏笔过滤 + 摘要解包守卫 ----

def test_unfished_foreshadows_filters_recovered(tmp_path):
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "追踪"))
    table = ("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
             "|------|------|---------|------|---------|------|\n"
             "| 神秘玉佩 | 道具谜团 | 第1章 | 埋设中 | 第60-75章卷末 |  |\n"
             "| 七日之约 | 规则契约 | 第2章 | 已回收 | 第5章 | 第5章回收 |\n"
             "| 灵石账 | 数字倒计时 | 第3章 | 推进中 | 第30章 |  |\n")
    with open(os.path.join(proj, "追踪", "伏笔.md"), "w", encoding="utf-8") as f:
        f.write(table)
    out = memory.unfished_foreshadows(proj)
    assert "神秘玉佩" in out and "灵石账" in out
    assert "七日之约" not in out                      # 已回收条目被过滤
    assert "| 伏笔 |" in out                          # 表头保留


def test_append_chapter_summary_survives_malformed_line(tmp_path):
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "追踪"))
    with open(os.path.join(proj, "追踪", "章节摘要.md"), "w", encoding="utf-8") as f:
        f.write("# 章节摘要链\n\n"
                "- 第1章《甲》：正常条目。\n"
                "- 第5章 手写备注没按格式来（曾触发 TypeError）\n")
    memory.append_chapter_summary(proj, 2, "乙", "新条目。")   # 不得抛异常
    text = open(os.path.join(proj, "追踪", "章节摘要.md"), encoding="utf-8").read()
    assert "第2章《乙》：新条目。" in text
    assert "第1章《甲》：正常条目。" in text


# ---- 模板 format 冒烟：改过的模板必须能用 dummy kwargs 完整 format ----

def _smoke_format(template: str):
    names = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    return template.format(**{n: "占位" for n in names})


def test_modified_templates_format_smoke():
    for t in (prompts.CO_SUPERVISOR_PROMPT, prompts.CO_READBACK_PROMPT,
              prompts.CHAPTER_OUTLINE_PROMPT, prompts.PROSE_WRITING_PROMPT,
              prompts.ENRICH_PROMPT, prompts.TRIM_PROMPT, prompts.DESLOP_REWRITE_PROMPT,
              prompts.REVIEW_FIX_PROMPT, prompts.TRACKING_UPDATE_PROMPT,
              prompts.BLURB_AND_TAGS_PROMPT):
        assert isinstance(_smoke_format(t), str)


def test_new_placeholders_present():
    assert "{chapter_num}" in prompts.CO_SUPERVISOR_PROMPT
    assert "{chapter_outline}" in prompts.CO_SUPERVISOR_PROMPT
    assert "{chapter_num}" in prompts.CO_READBACK_PROMPT
    assert "{chapter_outline}" in prompts.CO_READBACK_PROMPT
    assert "{global_summary}" in prompts.CHAPTER_OUTLINE_PROMPT
    assert "{recent_summaries}" in prompts.CHAPTER_OUTLINE_PROMPT
    assert "{character_states}" in prompts.CHAPTER_OUTLINE_PROMPT
    # v0.19 双层前缀架构：章级上下文（timeline/状态/摘要/上一章锚点）由 {chapter_header}
    # 统一承载，不再散装注入各模板——散装占位符的移除是有意变更
    for t in (prompts.PROSE_WRITING_PROMPT, prompts.ENRICH_PROMPT, prompts.TRIM_PROMPT,
              prompts.DESLOP_REWRITE_PROMPT, prompts.FINAL_REVIEW_PROMPT,
              prompts.REVIEW_FIX_PROMPT, prompts.CHAPTER_SUMMARY_PROMPT,
              prompts.GLOBAL_SUMMARY_PROMPT, prompts.TRACKING_UPDATE_PROMPT):
        assert "{project_header}" in t and "{chapter_header}" in t,             "模板缺双层前缀：%r" % t[:40]
    assert "{old_context}" in prompts.TRACKING_UPDATE_PROMPT
    # ROOT_CAUSE 真实锚定块占位（GUI 审校反馈环消费）
    from app.prompts import ROOT_CAUSE_PROMPT
    assert "{upstream_anchors}" in ROOT_CAUSE_PROMPT
