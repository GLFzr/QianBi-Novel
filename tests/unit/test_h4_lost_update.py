# -*- coding: utf-8 -*-
"""H-4 主体注入测试：跨线程 load→改→save 丢失更新（C32）。

审查报告 H-4 残留主体：worker 线程（orchestrator.run 主循环）在长生成窗口
两端 load→…（数分钟 LLM 调用）…→save 全量回写，窗口内 GUI 线程的
add_idea / set_guidance / update_history_status 落盘被旧快照覆盖
（嫌疑面：orchestrator.py:343 load → :413/:467/:491 save 形态）。

用 Event 精确交错复现：worker 先持旧快照 → GUI 在窗口内落盘 → worker 再 save。
修复前（整写覆盖）必红；修复后（按项目写锁 + save 前重读三方合并）必须全绿。
"""
import json
import logging
import os
import threading

import pytest

from app.core import state as st


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "book"
    p.mkdir()
    return str(p)


def _read_disk(proj):
    with open(st.state_path(proj), encoding="utf-8") as f:
        return json.load(f)


def test_long_window_save_keeps_gui_idea(proj):
    """旗舰场景：worker 长窗口旧快照 save 不得覆盖窗口内 GUI 提交的想法
    （worker 只改 total_chapters，pending_ideas 未触碰 → 以盘上为准）。"""
    worker_loaded = threading.Event()
    gui_saved = threading.Event()

    def worker():
        state = st.load_state(proj)          # T0 持旧快照
        worker_loaded.set()
        assert gui_saved.wait(5)
        state["total_chapters"] = 10         # worker 自己唯一的变更
        st.save_state(proj, state)           # 旧实现：整写覆盖 → GUI 想法丢

    t = threading.Thread(target=worker)
    t.start()
    assert worker_loaded.wait(5)
    s2 = st.load_state(proj)
    assert st.add_idea(proj, s2, "窗口内提交的GUI想法")
    gui_saved.set()
    t.join(5)
    assert not t.is_alive(), "worker 线程未退出（疑似锁挂死）"

    disk = st.load_state(proj)
    assert isinstance(disk, dict)            # 返回容器仍满足普通 dict 契约
    assert disk["total_chapters"] == 10, "worker 自己的变更丢了"
    assert [i["text"] for i in st.norm_ideas(disk)] == ["窗口内提交的GUI想法"], (
        "窗口内 GUI 提交的想法被 worker 旧快照整写覆盖（H-4 丢失更新）")


def test_guidance_cross_chapter_no_clobber(proj):
    """pending_guidance 子键粒度：worker 登记第 1 章指导的同时 GUI 登记第 5 章
    指导（同一基线、不同子键）——两边都必须落盘。"""
    st.save_state(proj, st.load_state(proj))   # 建立共同基线文件
    worker_loaded = threading.Event()
    gui_saved = threading.Event()

    def worker():
        w = st.load_state(proj)              # 与 GUI 同一基线内容
        worker_loaded.set()
        assert gui_saved.wait(5)
        st.set_guidance(proj, w, 1, "第1章指导")

    t = threading.Thread(target=worker)
    t.start()
    assert worker_loaded.wait(5)
    g = st.load_state(proj)
    st.set_guidance(proj, g, 5, "第5章指导")   # 窗口内 GUI 落盘
    gui_saved.set()
    t.join(5)
    assert not t.is_alive()

    pg = st.load_state(proj)["pending_guidance"]
    assert pg.get("5") == "第5章指导", "GUI 登记的第5章指导被 worker 旧快照覆盖（H-4）"
    assert pg.get("1") == "第1章指导", "worker 自己的登记丢了"


def test_concurrent_add_idea_both_survive(proj):
    """两个线程从同一基线各 add 一条想法（读-读-写-写交错）：加法并集，不得互相吞。"""
    a_loaded = threading.Event()
    b_loaded = threading.Event()
    a_saved = threading.Event()

    def adder_a():
        s = st.load_state(proj)
        a_loaded.set()
        assert b_loaded.wait(5)              # 确保 B 也在 A 落盘前装了同一基线
        st.add_idea(proj, s, "想法A")
        a_saved.set()

    def adder_b():
        assert a_loaded.wait(5)
        s = st.load_state(proj)              # A 落盘前装载 → 同一基线
        b_loaded.set()
        assert a_saved.wait(5)
        st.add_idea(proj, s, "想法B")

    ta = threading.Thread(target=adder_a)
    tb = threading.Thread(target=adder_b)
    tb.start()
    ta.start()
    ta.join(5)
    tb.join(5)
    texts = sorted(i["text"] for i in st.norm_ideas(st.load_state(proj)))
    assert texts == ["想法A", "想法B"], f"并发 add_idea 互相吞条目：{texts}"


def test_add_idea_ids_unique_within_same_millisecond(proj, monkeypatch):
    """同毫秒两次 add 不许撞 id（H-4 并发丢更新的真正根因）。

    旧 id = `idea_{毫秒}_{该快照长度}`：两个线程从同一基线装载时长度相同，
    同毫秒内落盘就得到同一个 id；三方合并按 id 去重 ⇒ 后写的把先写的当
    「同一条」覆盖掉。CI 上 `test_concurrent_add_idea_both_survive` 的间歇
    红即此，不是线程调度问题。这里把时钟钉死，把偶发变确定。
    """
    monkeypatch.setattr(st.time, "time", lambda: 1700000000.123)
    base_a = st.load_state(proj)
    base_b = st.load_state(proj)
    st.add_idea(proj, base_a, "想法A")
    st.add_idea(proj, base_b, "想法B")
    state = st.load_state(proj)
    ids = [i["id"] for i in st.norm_ideas(state)]
    assert len(ids) == len(set(ids)), f"id 撞车：{ids}"
    texts = sorted(i["text"] for i in st.norm_ideas(state))
    assert texts == ["想法A", "想法B"], f"同毫秒 add 丢条目：{texts}"


def test_history_status_fix_survives_worker_append(proj):
    """GUI「标记已修复」(needs_fix→pass) 与 worker append_history 并发：
    新章记录要进 history，GUI 的状态修复也不得被旧快照回滚。"""
    seeded = st.load_state(proj)
    st.append_history(proj, seeded, {"num": 1, "title": "第一章", "status": "needs_fix"})
    worker_loaded = threading.Event()
    gui_saved = threading.Event()

    def worker():
        w = st.load_state(proj)
        worker_loaded.set()
        assert gui_saved.wait(5)
        st.append_history(proj, w, {"num": 2, "title": "第二章", "status": "pass"})

    t = threading.Thread(target=worker)
    t.start()
    assert worker_loaded.wait(5)
    st.update_history_status(proj, st.load_state(proj), 1, "pass")
    gui_saved.set()
    t.join(5)
    assert not t.is_alive()

    by_num = {h["num"]: h for h in st.load_state(proj)["history"]}
    assert by_num[1]["status"] == "pass", "GUI 的 needs_fix→pass 被 worker 旧快照回滚（H-4）"
    assert 2 in by_num, "worker 的新章记录丢了"


def test_save_lock_timeout_degrades_to_atomic_write(proj, monkeypatch, caplog):
    """锁必须带超时保护：病态持锁（重入/死锁）不得永久挂死——降级为无锁原子写
    （os.replace 原子性仍在，文件仍是完整 JSON）并大声告警。"""
    monkeypatch.setattr(st, "_SAVE_LOCK_TIMEOUT", 0.2)
    s = st.load_state(proj)
    s["total_chapters"] = 3
    with caplog.at_level(logging.ERROR, logger="qianbi.state"):
        lk = st._project_save_lock(proj)
        with lk:                              # 主线程自持项目锁：save_state 重入必超时
            st.save_state(proj, s)            # 无超时实现：此处永久挂死
    assert _read_disk(proj)["total_chapters"] == 3, "降级路径必须仍完成原子写"
    assert any("超时" in r.getMessage() for r in caplog.records), "降级必须 error 告警"


def test_plain_dict_save_legacy_overwrite(proj):
    """兼容钉：无基线的裸 dict（调用方自建/selftest 形态）保持旧语义——整写覆盖。"""
    st.save_state(proj, st.load_state(proj))   # 先有文件
    st.save_state(proj, {"stage": st.STAGE_OUTLINE, "total_chapters": 7})
    assert _read_disk(proj) == {"stage": st.STAGE_OUTLINE, "total_chapters": 7}
