# -*- coding: utf-8 -*-
"""L4 head_rebuild（每章重建）+ L3 commit_raw 回归（深化计划 v2 §1）

- head_rebuild：每章 fresh VolumeSession（persist=False 不落盘）、system=冻结头
  （含审校尾段）、跨章历史不入栈、开幕轮带完整八节（volume_mode=False）
- commit_raw：清洗改字节时栈里固化原始字节（缓存对齐），清洗稿仍返回调用方
全部内存假件 + tmp_path，无真实 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app.core.volume_session import VolumeSession, volume_messages_path


class FakeClient:
    base_url, model = "https://fake", "m"

    def chat_turn(self, messages, **kw):
        # 返回带围栏与首尾空白的"原始输出"——postprocess（清洗）必改字节
        return "  ```\n清洗前原文正文。\n```  "


def _postprocess(text: str) -> str:
    return text.strip().replace("```", "").strip()


def _make(tmp_path, **kw):
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    s = VolumeSession(FakeClient(), system_text="冻结头", volume=1, proj=proj,
                      **kw)
    return proj, s


def test_persist_false_skips_saving(tmp_path):
    proj, s = _make(tmp_path, persist=False)
    s.open_chapter("【章头】", "写作指令（动态值）", chapter_num=1)
    s.ask("写正文", postprocess=_postprocess, phase="prose")
    assert s.save() == ""                                   # 不落盘
    assert not os.path.exists(volume_messages_path(proj, 1))
    assert len(s._messages) >= 3                            # 栈在内存里照常工作


def test_commit_raw_stores_original_bytes(tmp_path):
    proj, s = _make(tmp_path, persist=False, commit_raw=True)
    reply = s.ask("写正文", postprocess=_postprocess, phase="prose")
    assert reply == "清洗前原文正文。"                        # 调用方拿到清洗稿
    assistant = s._messages[-1]["content"]
    assert assistant == "  ```\n清洗前原文正文。\n```  "      # 栈里是原始字节


def test_commit_raw_off_stores_cleaned(tmp_path):
    proj, s = _make(tmp_path, persist=False)
    s.ask("写正文", postprocess=_postprocess, phase="prose")
    assert s._messages[-1]["content"] == "清洗前原文正文。"   # 缺省：清洗稿入栈


def test_head_rebuild_each_chapter_is_fresh(tmp_path):
    """L4 核心：第二章拿到的是全新空栈（跨章历史不入栈），一层消息只有本章"""
    proj, s1 = _make(tmp_path, persist=False)
    s1.open_chapter("【章头1】", "指令1", chapter_num=1)
    s1.ask("写正文1", postprocess=_postprocess, phase="prose")
    n1 = len(s1._messages)
    # 第二章：fresh 实例（stages 每章新建，不走缓存复用/load）
    _, s2 = _make(tmp_path, persist=False)
    s2.open_chapter("【章头2】", "指令2", chapter_num=2)
    assert len(s2._messages) == 1                           # 只有 system
    assert s2._messages[0]["content"] == "冻结头"
    assert "章头1" not in s2._messages[0]["content"]         # 第一章历史不入栈
    assert n1 >= 3


def test_opening_carries_full_header_and_preface(tmp_path):
    proj, s = _make(tmp_path, persist=False, commit_raw=True)
    turn = s.open_chapter("【八节章头（含上一章结尾）】", "写作指令", chapter_num=3,
                          preface="")
    assert "【八节章头（含上一章结尾）】" in turn             # volume_mode=False：全八节
    assert "写作指令" in turn
    s.ask("写正文", postprocess=_postprocess, phase="prose")
    user = s._messages[-2]["content"]
    assert user.startswith("【新章开幕") or "【八节章头" in user
