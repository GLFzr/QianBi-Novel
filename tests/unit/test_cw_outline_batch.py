# -*- coding: utf-8 -*-
"""细纲批次视图：跟随最新一批、点回执回看该批、批量编辑后拆回各章落盘

这里最要紧的是**保存不能串文件**。一批细纲在编辑器里是一整段合并文本，
如果图省事把 _chapter_path 指向这批的第一个文件，一次保存就会把 5 章内容
写进那一个文件，其余四章直接丢——所以批量态单独记账、按标记拆回去。
"""
import os

import pytest

from app import project
from app.core import co_dialogue, state as st
from app.ui.bridge import Bridge, CwMessageModel


class _Sig:
    def __init__(self):
        self.n = 0

    def emit(self, *a):
        self.n += 1


class _Toast:
    def __init__(self):
        self.items = []

    def emit(self, level, msg):
        self.items.append((level, msg))


class _Bare:
    """只借 Bridge 的方法体做单测：不起 Qt 实例、不建项目、不碰配置"""
    _BATCH_MARK = Bridge._BATCH_MARK
    _BATCH_FALLBACK = Bridge._BATCH_FALLBACK
    _cw_outline_nums = Bridge._cw_outline_nums
    _cw_open_outline_batch = Bridge._cw_open_outline_batch
    _cw_save_outline_batch = Bridge._cw_save_outline_batch
    _cw_get_chapter_title = Bridge._cw_get_chapter_title
    _cw_open_latest_batch = Bridge._cw_open_latest_batch

    def __init__(self, proj):
        self.proj = proj
        self._chapter_path = "旧路径.md"
        self._chapter_text = ""
        self._chapter_findings = []
        self._cw_batch_files = []
        self.toast = _Toast()
        self.chapterTextChanged = _Sig()
        self.chapterFindingsChanged = _Sig()
        self.currentChapterChanged = _Sig()
        self.reset_calls = 0

    def _reset_editor_state(self):
        self.reset_calls += 1

    def refreshQueue(self):
        pass


@pytest.fixture
def proj(tmp_path):
    p = str(tmp_path)
    os.makedirs(os.path.join(p, "大纲"), exist_ok=True)
    for n in (1, 2, 3):
        project.write_file(project.get_outline_path(p, n),
                           "核心事件：事件%d\n故事内容：内容%d" % (n, n))
    return p


# ---------------------------------------------------------------- 打开一批

def test_batch_view_renders_every_chapter(proj):
    b = _Bare(proj)
    assert b._cw_open_outline_batch([1, 2, 3]) is True
    for n in (1, 2, 3):
        assert "事件%d" % n in b._chapter_text
    assert b._chapter_text.count("# ▸ 第") == 3
    # 关键：不能留下单个文件路径，否则保存会把三章写进同一个文件
    assert b._chapter_path == ""
    assert b._cw_get_chapter_title() == "细纲 第1-3章（3 章一批）"


def test_batch_view_skips_empty_and_missing_files(proj):
    project.write_file(project.get_outline_path(proj, 4), "   ")
    b = _Bare(proj)
    assert b._cw_open_outline_batch([1, 4, 77]) is True
    assert b._cw_get_chapter_title() == "细纲 第1章"     # 只剩一章有内容
    assert "事件1" in b._chapter_text


def test_batch_view_reports_nothing_to_show(proj):
    b = _Bare(proj)
    assert b._cw_open_outline_batch([88, 99]) is False
    assert b._chapter_text == ""


# ---------------------------------------------------------------- 拆回各章

def test_batch_save_splits_back_per_chapter(proj):
    b = _Bare(proj)
    b._cw_open_outline_batch([1, 2, 3])
    b._cw_save_outline_batch(b._chapter_text.replace("事件2", "改过的乙事件"))
    assert "改过的乙事件" in project.read_file(project.get_outline_path(proj, 2))
    # 串文件是本组测试存在的意义
    one = project.read_file(project.get_outline_path(proj, 1))
    assert "事件1" in one and "乙事件" not in one and "事件3" not in one
    three = project.read_file(project.get_outline_path(proj, 3))
    assert "事件3" in three and "乙事件" not in three


def test_batch_save_keeps_file_of_deleted_section(proj):
    """删掉某章小节 ≠ 删掉那章：原文不动，只在提示里说清楚"""
    b = _Bare(proj)
    b._cw_open_outline_batch([1, 2, 3])
    before = project.read_file(project.get_outline_path(proj, 2))
    kept = [ln for ln in b._chapter_text.splitlines()
            if "事件2" not in ln and "内容2" not in ln and "# ▸ 第 2 章" not in ln]
    b._cw_save_outline_batch("\n".join(kept))
    assert project.read_file(project.get_outline_path(proj, 2)) == before
    assert any("缺失" in m for _l, m in b.toast.items)


def test_batch_save_refuses_unknown_chapter_number(proj):
    b = _Bare(proj)
    b._cw_open_outline_batch([1, 2])
    b._cw_save_outline_batch(b._chapter_text + "\n\n# ▸ 第 99 章\n\n凭空多出来的一章")
    assert not os.path.isfile(project.get_outline_path(proj, 99))
    assert any("未知章号" in m for _l, m in b.toast.items)


def test_batch_save_clears_dirty_flag(proj):
    b = _Bare(proj)
    b._cw_open_outline_batch([1])
    b._cw_save_outline_batch("# ▸ 第 1 章\n\n新内容")
    assert b.reset_calls == 2          # 打开一次、保存一次都要重置编辑态
    assert b._chapter_text.endswith("新内容")


# ---------------------------------------------------------------- 哪批算"最新"

def test_latest_batch_uses_recorded_batch_not_highest(proj):
    """记了批次就用批次：后面又补写了 4、5 章，也不该把 1-3 那批挤掉"""
    b = _Bare(proj)
    state = {"cw": {"last_outline_batch": [1, 2]}}
    assert b._cw_outline_nums(state) == [1, 2]


def test_latest_batch_drops_chapters_that_were_removed(proj):
    b = _Bare(proj)
    state = {"cw": {"last_outline_batch": [1, 2, 55]}}
    assert b._cw_outline_nums(state) == [1, 2]


def test_latest_batch_falls_back_to_highest_five(tmp_path):
    p = str(tmp_path)
    for n in range(1, 9):
        project.write_file(project.get_outline_path(p, n), "x%d" % n)
    b = _Bare(p)
    assert b._cw_outline_nums({}) == [4, 5, 6, 7, 8]


def test_open_latest_batch_false_when_no_outlines(tmp_path):
    """一批都没有 → 返回 False，让调用方回落到单元总纲产物（不是显示空白）"""
    b = _Bare(str(tmp_path))
    b._cw = type("CW", (), {"load": lambda self: {}})()
    assert b._cw_open_latest_batch() is False


# ---------------------------------------------------------------- 对话回执

def test_transcript_receipt_carries_batch_nums(tmp_path):
    state = {}
    co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "agent", "本批已生成",
                                  nums=[3, 4, 5])
    co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "user", "继续")
    items = st.ensure_cw(state)["transcript"][st.STAGE_CW_UNIT]
    assert items[0]["nums"] == [3, 4, 5]
    assert "nums" not in items[1], "不带批次的普通消息不该多出空键"


def test_batch_nums_survive_state_roundtrip(tmp_path):
    p = str(tmp_path)
    state = {}
    co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "agent", "回执", nums=[7])
    st.save_state(p, state)
    back = st.ensure_cw(st.load_state(p))["transcript"][st.STAGE_CW_UNIT]
    assert back[0]["nums"] == [7]


# ---------------------------------------------------------------- 增量模型（#6）

def test_message_model_appends_without_reset():
    m = CwMessageModel()
    events = []
    m.rowsInserted.connect(lambda *_a: events.append("insert"))
    m.modelReset.connect(lambda: events.append("reset"))
    a = [{"role": "user", "text": "一"}, {"role": "agent", "text": "二"}]
    m.sync(a)
    m.sync(a + [{"role": "agent", "text": "三", "nums": [1, 2]}])
    assert events == ["insert", "insert"], events   # 全程没有 reset＝不整表重建
    assert m.rowCount() == 3


def test_message_model_resets_only_on_divergence():
    m = CwMessageModel()
    events = []
    m.rowsInserted.connect(lambda *_a: events.append("insert"))
    m.modelReset.connect(lambda: events.append("reset"))
    m.sync([{"role": "user", "text": "一"}])
    m.sync([{"role": "user", "text": "一"}])          # 完全相同 → 什么都不发
    assert events == ["insert"]
    m.sync([{"role": "agent", "text": "换了个阶段"}])  # 回看别的阶段 → 整表重来
    assert events == ["insert", "reset"]


def test_message_model_exposes_batch_nums():
    from PySide6.QtCore import Qt
    m = CwMessageModel()
    m.sync([{"role": "agent", "text": "本批", "nums": [4, 5]}])
    idx = m.index(0)
    assert m.data(idx, CwMessageModel.MsgNumsRole) == [4, 5]
    assert m.data(idx, CwMessageModel.MsgTextRole) == "本批"
    assert m.data(idx, CwMessageModel.MsgRoleRole) == "agent"
    # 普通消息没有批次 → 空列表而非 None（QML 侧直接取 .length）
    m.sync([{"role": "user", "text": "普通"}])
    assert m.data(m.index(0), CwMessageModel.MsgNumsRole) == []
    assert m.data(m.index(0), CwMessageModel.MsgRoleRole) == "user"
