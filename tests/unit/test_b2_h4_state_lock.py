# -*- coding: utf-8 -*-
"""H-4 护栏：save_state 进程内互斥——GUI 线程与流水线 worker 线程并发写盘
不产生交错/截断现场。

审查报告：load_state→改→save_state 全程无锁，orchestrator 与 bridge 多处
跨线程并发调用。最小修：_SAVE_LOCK 串行化「校验→写临时→replace」整段
（跨线程 load→改→save 的丢失更新是另一层问题，不在此展开）。
"""
import json
import os
import threading
import time

from app import project
from app.core import state as st


def _make_proj(tmp_path):
    return project.create_project(str(tmp_path), "并发状态")


def test_concurrent_save_state_always_valid_json(tmp_path):
    """8 线程 × 5 次 save_state：文件始终是合法 JSON（无截断/混写），无 tmp 残留"""
    proj = _make_proj(tmp_path)
    st.save_state(proj, dict(st.DEFAULT_STATE))
    errors = []

    def worker(i):
        try:
            for j in range(5):
                st.save_state(proj, {"stage": "prose", "writer": f"w{i}", "seq": j})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发 save_state 抛错：{errors}"
    with open(st.state_path(proj), encoding="utf-8") as f:
        data = json.load(f)   # 截断/交错 ⇒ JSONDecodeError ⇒ 红
    assert isinstance(data.get("seq"), int)
    leftovers = [f for f in os.listdir(proj) if f.endswith(".tmp")]
    assert not leftovers, f"临时文件残留：{leftovers}"


def test_save_state_serializes_write_section(tmp_path, monkeypatch):
    """互斥的行为级观察：A 线程在 json.dump 中途睡眠时，B 的 dump 必须等它
    出临界区才开始——没有锁时 B 会在 A 睡眠期间插入 ⇒ 红。"""
    proj = _make_proj(tmp_path)
    events = []
    real_dump = json.dump

    def spying_dump(obj, fp, *a, **k):
        tag = obj.get("tag", "?") if isinstance(obj, dict) else "?"
        events.append(("enter", tag, time.perf_counter()))
        if tag == "slow":
            time.sleep(0.25)
        real_dump(obj, fp, *a, **k)
        events.append(("exit", tag, time.perf_counter()))

    monkeypatch.setattr(st.json, "dump", spying_dump)
    st.save_state(proj, {"tag": "fast0"})   # 预热（首写也过锁）
    t = threading.Thread(target=st.save_state, args=(proj, {"tag": "slow"}))
    t.start()
    time.sleep(0.05)   # 让 slow 先拿锁、进入 dump 睡眠段
    st.save_state(proj, {"tag": "fast"})
    t.join()

    def span(tag):
        ent = next(v for e, tg, v in events if e == "enter" and tg == tag)
        ext = next(v for e, tg, v in events if e == "exit" and tg == tag)
        return ent, ext

    s_ent, s_ext = span("slow")
    f_ent, _f_ext = span("fast")
    assert f_ent >= s_ext, (
        "save_state 写盘段未互斥：fast 在 slow 的 dump 中途插入 "
        f"(slow {s_ent:.3f}-{s_ext:.3f}, fast enter {f_ent:.3f})——锁被摘或没包住整段")
