# -*- coding: utf-8 -*-
"""共写章节感知回归：参考块锚定用户选中章 + 前后章上下文 + 空章判定 + 双文件守卫"""
import os

from app import project
from app.core import co_dialogue, state as st
from app.ui import bridge as bmod


def _mk_proj(tmp_path):
    """ch1/ch3 存在（缺 ch2），细纲 1-3 齐备"""
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


def test_focus_gap_chapter_context(tmp_path):
    proj = _mk_proj(tmp_path)
    ref = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "", focus_chapter=2)
    assert "锚定第 2 章" in ref
    assert "乙事件（缺口章）" in ref          # 本章细纲=第2章（而非 next_chapter_num=4）
    assert "第一章结尾钩子" in ref            # 上一章=小于2的最近章（ch1 结尾）
    assert "第三章开头承接" in ref            # 下一章=大于2的最近章（ch3 开头）
    assert "尚未写成" in ref                  # 本章现状=空


def test_focus_existing_chapter_has_draft(tmp_path):
    proj = _mk_proj(tmp_path)
    ref = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "", focus_chapter=1)
    assert "锚定第 1 章" in ref
    assert "已有草稿" in ref
    assert "（本章为第一章）" in ref          # ch1 无更前章


def test_no_focus_keeps_legacy_next_chapter(tmp_path):
    proj = _mk_proj(tmp_path)
    ref = co_dialogue.compose_reference_block(proj, st.STAGE_CW_PROSE, "")
    assert "锚定第 4 章" in ref               # ch1/ch3 存在 → next_chapter_num=4
    assert len(ref) < 6000


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply

    def chat_stream(self, prompt, on_chunk=None, **kw):
        return self.reply


class _FakeRouter:
    def __init__(self, reply="好的。"):
        self._c = _FakeClient(reply)

    def client(self, slot):
        return self._c


def test_dialogue_worker_focus_passthrough(tmp_path):
    proj = _mk_proj(tmp_path)
    w = co_dialogue.DialogueWorker({}, proj, st.STAGE_CW_PROSE, "帮我写这一章",
                                   router=_FakeRouter(), focus_chapter=2)
    w.run()
    assert "锚定第 2 章" in w.last_prompt
    assert w.result_text == "好的。"


# ---- 双文件守卫 / 草稿串章兜底（Bridge 方法以轻量 self 驱动，不构造完整 QObject）----

class _Sig:
    def emit(self, *a, **kw):
        pass


class _Timer:
    def stop(self):
        pass


class _FakeSelf:
    def __init__(self, proj):
        self.proj = proj
        self._chapter_path = ""
        self._cur_num = 0
        self._chapter_findings = []
        self._editor_dirty = False
        self._working_text = ""
        self._draft_timer = _Timer()
        self.editorDirtyChanged = _Sig()
        self.chapterFindingsChanged = _Sig()
        self.toast = _Sig()


def test_canonical_chapter_path_redirect(tmp_path):
    proj = _mk_proj(tmp_path)
    fs = _FakeSelf(proj)
    # ch1 已有带标题文件 → 返回真实路径
    got = bmod.Bridge._canonical_chapter_path(fs, 1, "FALLBACK")
    assert got == os.path.join(proj, "正文", "第001章_甲.md")
    # ch2 无文件 → 原样回退
    assert bmod.Bridge._canonical_chapter_path(fs, 2, "FALLBACK") == "FALLBACK"


def test_recover_draft_missing_file_fallback(tmp_path):
    from app.core import versions
    proj = _mk_proj(tmp_path)
    fs = _FakeSelf(proj)
    fs._chapter_path = os.path.join(proj, "正文", "第001章_甲.md")  # 残留的「上一章」路径
    versions.save_draft(proj, 2, "第二章草稿。")
    r = bmod.Bridge.recoverDraft(fs)
    assert r.get("num") == 2 and r.get("text") == "第二章草稿。"
    # 关键：路径不得残留第 1 章（否则保存会把新章内容覆盖进别的章）
    assert fs._chapter_path == project.get_chapter_path(proj, 2)
    assert fs._cur_num == 2
