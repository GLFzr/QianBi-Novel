# -*- coding: utf-8 -*-
"""共写双模式（方案 A）与落稿提取契约（方案 C1）：钉住「发嗯收千字」的棺材板

讨论模式的三道闸，缺一道都会退化回「一言堂」：
① mode_block 硬约束（复述确认+字数上限+禁止展开）；
② 短输入配更短上限（≤12 字 → ≤80 字）；
③ bridge 侧机器截断（提示词失效时兜底）。
正文提取（C1）反过来：标记内是正文，开场白/元话语一个字不许混进存盘文件。
"""
from app.core import co_dialogue as cod
from app.prompts import co_writing as cw


def test_discuss_block_has_confirm_and_cap():
    block = cw.mode_block_for("cw_core", "discuss", "主角用第一人称写，重点写他在坊市查药材掺假的调查过程")
    assert "回应模式：讨论" in block
    assert "复述确认" in block
    assert "禁止展开" in block
    assert "200" in block and "80" not in block      # 常规输入 200 字上限


def test_short_input_gets_tighter_cap():
    block = cw.mode_block_for("cw_core", "discuss", "嗯")
    assert "80" in block                              # ≤12 字输入 → 80 字上限
    assert "200" not in block


def test_compose_block_requests_draft_and_prose_markers():
    block = cw.mode_block_for("cw_core", "compose", "直接出草案")
    assert "撰写" in block and "草案" in block
    prose = cw.mode_block_for("cw_prose", "compose", "写第一章")
    assert "<<<正文>>>" in prose and "<<<正文完>>>" in prose   # C1 落稿契约
    other = cw.mode_block_for("cw_outline", "compose", "出大纲")
    assert "<<<正文>>>" not in other                  # 正文包裹约定只属于正文阶段


def test_cap_discuss_reply_truncates_long_output():
    long_text = "这是一句话。" * 100                  # 600 字，全是句号收口
    capped = cod.cap_discuss_reply(long_text, cap=200)
    assert len(capped) < 260
    assert "已截断" in capped
    assert capped.rstrip().endswith("。") is False or "已截断" in capped


def test_cap_discuss_reply_passes_short_output_through():
    short = "已记录：作者希望第一人称。"
    assert cod.cap_discuss_reply(short) == short


def test_extract_prose_reply_prefers_markers():
    reply = ("好的，按作者要求交正文。\n\n<<<正文>>>\n## 第1章 开端\n"
             "正文第一段。\n\n正文第二段。\n<<<正文完>>>\n\n"
             "待确认：下一章是否引入云岚宗？")
    body = cod.extract_prose_reply(reply)
    assert body.startswith("## 第1章 开端")
    assert "正文第二段" in body
    assert "好的，按作者要求" not in body              # 开场白不许混入
    assert "待确认" not in body                        # 元话语不许混入


def test_extract_prose_reply_fallback_without_markers():
    reply = ("先说两句题外话。\n\n## 第2章 风起\n\n本章正文内容。\n\n"
             "→ 下阶段交接\n- 事实一")
    body = cod.extract_prose_reply(reply)
    assert body.startswith("## 第2章 风起")
    assert "本章正文内容" in body
    assert "题外话" not in body and "下阶段交接" not in body


def test_draft_requests_cover_all_dialogue_stages():
    for stage in ("cw_core", "cw_outline", "cw_worldbook", "cw_unit", "cw_prose"):
        assert stage in cw.CW_DRAFT_REQUESTS, stage
