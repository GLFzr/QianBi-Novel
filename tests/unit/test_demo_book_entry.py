# -*- coding: utf-8 -*-
"""零 Key 静态示例书（OB-M4）：《种子书》只读入口与守卫面回归

覆盖（w3_onboarding §5 判据 6「零 Key 信任路径」的可测面）：
- 随包 book/ 整树复制成本地项目（纯文件复制，零网络零 LLM）；
- 打开入口：建目录 + demo 旗 + auto 档 + 打开；真书绝不覆盖；demo 副本重开即重置；
- 只读守卫：打 demo 旗的项目，生成/确定/破坏类七入口全部拦下并指路（零请求）；
- 守卫不误伤：无 demo 旗的正常项目零拦截。
"""
import os
import shutil
import types

import pytest

from app import project
from app.core import state as st
from app.ui import bridge as bmod
from app.ui.demo_pack import DemoPack, unpack_book


class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


class _Recorder:
    """构造即失败——被断言「零请求」的路径上出现任何 worker 实例化即红"""

    def __init__(self, *a, **kw):
        raise AssertionError("该路径不应构造 LLM worker（零网络请求）")


def _toasts(fs, level=None):
    out = [str(c[1] if len(c) > 1 else c[0]) for c in fs.toast.calls]
    if level:
        out = [str(c[1]) for c in fs.toast.calls if c and c[0] == level]
    return " | ".join(out)


class _DemoSelf:
    """openDemoBook 的轻量 self"""

    def __init__(self, root):
        self._running = False
        self._books_root = str(root)
        self.toast = _Sig()
        self.opened = []

    def defaultBooksRoot(self):
        return self._books_root

    def _open_project(self, path, silent=False):
        self.opened.append(path)


# ---------- 复制半边（demo_pack.unpack_book）----------

def test_pack_has_full_book():
    """随包内容包可用且正文 ≥1 章（示例书的信任底座）"""
    pack = DemoPack.load()
    assert pack is not None, "assets/demo 内容包缺失——入口将不可用"
    assert pack.chapter_count() >= 1
    assert pack.book_meta.get("name")


def test_unpack_book_copies_full_tree(tmp_path):
    """整树复制：结构成为合法项目（设定/大纲/正文/追踪），纯文件操作"""
    pack = DemoPack.load()
    dest = str(tmp_path / "种子书")
    n = unpack_book(pack, dest)
    assert n > 0
    assert project.is_project(dest)
    assert os.path.isdir(os.path.join(dest, "正文"))
    assert os.listdir(os.path.join(dest, "正文"))


# ---------- 打开入口（bridge.openDemoBook）----------

def test_open_demo_book_creates_and_opens(tmp_path):
    """入口：复制 + demo 旗 + auto 档 + 打开 + 只读回执"""
    fs = _DemoSelf(tmp_path / "books")
    bmod.Bridge.openDemoBook(fs)
    path = os.path.join(str(tmp_path / "books"), "种子书")
    assert project.is_project(path)
    state = st.load_state(path)
    assert state.get("demo") is True
    assert st.ensure_cw(state)["mode"] == "auto"
    info = project.read_idea_info(path)
    assert info["genre"]                       # 立项元数据随包落盘
    assert fs.opened == [path]
    assert "只读" in _toasts(fs, "ok")


def test_open_demo_book_never_overwrites_real_book(tmp_path):
    """同名真书绝不覆盖：目录内容原样保留，warn 指路"""
    root = tmp_path / "books"
    real = project.create_project(str(root), "种子书")
    sentinel = os.path.join(real, "设定", "选题信息.md")
    with open(sentinel, "w", encoding="utf-8") as f:
        f.write("# 选题信息\n\n- 题材：我自己的书\n")
    fs = _DemoSelf(root)
    bmod.Bridge.openDemoBook(fs)
    with open(sentinel, encoding="utf-8") as f:
        assert "我自己的书" in f.read()          # 真书一字未动
    assert "覆盖" in _toasts(fs, "warn")
    assert fs.opened == []                       # 没有把真书当示例书打开


def test_open_demo_book_resets_demo_copy(tmp_path):
    """demo 副本重开即重置（与演示导演同纪律）"""
    root = tmp_path / "books"
    fs = _DemoSelf(root)
    bmod.Bridge.openDemoBook(fs)                 # 第一次：创建
    copy = os.path.join(str(root), "种子书")
    marker = os.path.join(copy, "正文", "用户涂改.md")
    with open(marker, "w", encoding="utf-8") as f:
        f.write("残迹")
    bmod.Bridge.openDemoBook(fs)                 # 第二次：重置
    assert not os.path.exists(marker)
    assert st.load_state(copy).get("demo") is True


def test_open_demo_book_busy_refuses(tmp_path):
    """流水线运行中不开示例书"""
    fs = _DemoSelf(tmp_path / "books")
    fs._running = True
    bmod.Bridge.openDemoBook(fs)
    assert fs.opened == []
    assert "停止" in _toasts(fs, "warn")


# ---------- 只读守卫（_demo_book_reason + 七入口拦截）----------

class _GuardSelf:
    """生成类入口守卫测试的轻量 self（打 demo 旗的项目）"""

    def __init__(self, proj, mode="auto"):
        self.proj = str(proj)
        self._cw = types.SimpleNamespace(load=lambda: st.load_state(str(proj)))
        self._demo = types.SimpleNamespace(active=False)
        self._running = False
        self._cw_busy = False
        self._cw_confirming = False
        self._cw_view = st.STAGE_CW_PROJECT
        self.cfg = {"writing": {"run_mode": "auto"}, "connections": [], "slots": {}}
        self.toast = _Sig()

    _get_cw_mode = bmod.Bridge._get_cw_mode
    _get_cw_stage_key = bmod.Bridge._get_cw_stage_key
    _demo_book_reason = bmod.Bridge._demo_book_reason
    _DEMO_BOOK_BLOCK = bmod.Bridge._DEMO_BOOK_BLOCK

    def _get_cw_mode_forced(self):
        return "cw"


def _mk_demo_book(tmp_path, name="书"):
    proj = project.create_project(str(tmp_path), name)
    state = st.load_state(proj)
    state["demo"] = True
    st.ensure_cw(state)["mode"] = "auto"
    st.save_state(proj, state)
    return proj


def test_guard_reason_flag_and_failure_open(tmp_path):
    """demo 旗 → 非空；无旗/无项目 → 空串；读盘异常 fail-open 不挡正常书写"""
    proj = _mk_demo_book(tmp_path)
    fs = _GuardSelf(proj)
    assert fs._demo_book_reason() != ""
    fs2 = _GuardSelf(_mk_demo_book(tmp_path, "正常书"))
    state = st.load_state(fs2.proj)
    state.pop("demo", None)
    st.save_state(fs2.proj, state)
    assert fs2._demo_book_reason() == ""


def test_guard_blocks_all_generation_entries(tmp_path, monkeypatch):
    """七入口全拦：流水线/共写对话/草案/确定/去味审校/局部改写/整章重写——零请求"""
    proj = _mk_demo_book(tmp_path)
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "SummarizeWorker", _Recorder)
    fs = _GuardSelf(proj)
    fs._get_cw_mode = lambda: "cw"               # demo 书即便在共写档也被守卫拦
    bmod.Bridge.startPipeline(fs)
    bmod.Bridge.generateCwDraft(fs)
    bmod.Bridge.confirmCwStage(fs)
    bmod.Bridge._start_cw_prose_check(fs, "deslop")
    bmod.Bridge._start_cw_prose_check(fs, "review")
    bmod.Bridge.rewriteSelection(fs, "前", "选中段", "后", "想法")
    bmod.Bridge._rewrite_chapter_common(fs, 1, "")
    text = _toasts(fs, "warn")
    assert text.count("示例书") == 7, f"七个入口应各拦一次，实际：{text}"
    assert "新建项目" in text                     # 每条都带指路
    # 共写对话入口（mode 检查之后才到守卫——共写档下验证守卫本身）
    fs2 = _GuardSelf(proj)
    fs2._cw = types.SimpleNamespace()
    fs2._get_cw_mode = lambda: "cw"
    bmod.Bridge.submitCwMessage(fs2, "写一章", "discuss")
    assert "示例书" in _toasts(fs2, "warn")


def test_guard_does_not_touch_normal_book(tmp_path, monkeypatch):
    """不误伤：正常项目（无 demo 旗）走原检查链（此处到缺 Key 提示，守卫零痕迹）"""
    proj = _mk_demo_book(tmp_path, "正常书")
    state = st.load_state(proj)
    state.pop("demo", None)
    st.save_state(proj, state)
    monkeypatch.setattr(bmod.co_dialogue, "DialogueWorker", _Recorder)
    monkeypatch.setattr(bmod.co_dialogue, "SummarizeWorker", _Recorder)
    fs = _GuardSelf(proj)
    bmod.Bridge.startPipeline(fs)
    text = _toasts(fs)
    assert "示例书" not in text
    assert "连接与模型" in text                   # 原有缺 Key/模型检查照常生效
