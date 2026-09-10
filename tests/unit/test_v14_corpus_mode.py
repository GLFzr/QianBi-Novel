# -*- coding: utf-8 -*-
"""v14 corpus_mode 章头瘦身离线回归

- corpus_mode=False（缺省）：chapter_header 与改造前逐字节一致
- corpus_mode=True：上一章结尾→引用行（权威在语料库），文风样本保留
- _chap_cm 门控：corpus_head 与 head_rebuild 同时开启才生效
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v14_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import stages
from app.core.shared_prefix import chapter_header


def _mk_proj_with_prev(tmp_path):
    proj = tmp_path / "p14"
    (proj / "设定").mkdir(parents=True)
    (proj / "大纲").mkdir()
    (proj / "正文").mkdir()
    (proj / "追踪").mkdir()
    (proj / "设定" / "题材定位.md").write_text("# 设定\n主角：测试", encoding="utf-8")
    (proj / "设定" / "世界书.md").write_text("# 世界书", encoding="utf-8")
    (proj / "大纲" / "大纲.md").write_text("# 大纲", encoding="utf-8")
    (proj / "大纲" / "细纲_第002章.md").write_text("第2章细纲：承接", encoding="utf-8")
    (proj / "正文" / "第001章_开局.md").write_text(
        "# 第1章 开局\n开局段的叙述质感样本，句长偏短。\n"
        "上一章的结尾停在一个未决的钩子上：门被敲响了。", encoding="utf-8")
    (proj / "追踪" / "角色状态.md").write_text("## 主角\n- 状态：无变化", encoding="utf-8")
    return str(proj)


def test_corpus_mode_off_is_byte_identical():
    """缺省（corpus_mode=False）必须与旧实现同字节——旧路径硬行为不改"""
    p = _mk_proj_with_prev(__import__("pathlib").Path(tempfile.mkdtemp()))
    h_default = chapter_header(p, 2)
    h_explicit = chapter_header(p, 2, corpus_mode=False)
    assert h_default == h_explicit
    assert "## 上一章结尾（直接衔接用）" in h_default
    assert "门被敲响了" in h_default, "旧模式保留上一章结尾原文"
    assert "文风锚定样本" in h_default


def test_corpus_mode_swaps_ending_for_pointer_keeps_style():
    p = _mk_proj_with_prev(__import__("pathlib").Path(tempfile.mkdtemp()))
    h = chapter_header(p, 2, corpus_mode=True)
    assert "## 上一章结尾（衔接用）" in h
    assert "已锁章节原文" in h, "引用行指向语料库"
    assert "## 上一章结尾（直接衔接用）" not in h, "结尾原文段不再注入（已在语料库，纯 miss）"
    assert "文风锚定样本" in h and "叙述质感样本" in h, "文风样本保留（近场风格锚定）"
    assert "## 本章细纲" in h and "细纲：承接" in h


def test_chap_cm_gate_requires_both_flags():
    class _Ctx:
        def __init__(self, w):
            self.cfg = {"writing": w}

    assert stages._chap_cm(_Ctx({"corpus_head": True, "head_rebuild": True})) is True
    assert stages._chap_cm(_Ctx({"corpus_head": True})) is False
    assert stages._chap_cm(_Ctx({"head_rebuild": True})) is False
    assert stages._chap_cm(_Ctx({})) is False


def test_volume_mode_beats_corpus_mode():
    """volume_mode（S1/S4 卷会话开幕）跳过的节不因 corpus_mode 回归——互斥语义保持"""
    p = _mk_proj_with_prev(__import__("pathlib").Path(tempfile.mkdtemp()))
    h = chapter_header(p, 2, volume_mode=True, corpus_mode=True)
    assert "上一章结尾" not in h and "文风锚定样本" not in h
    assert "## 角色状态" in h  # 五节 recitation 保留
