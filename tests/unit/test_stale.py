# -*- coding: utf-8 -*-
"""陈旧防护：审校结论过期判定（mtime vs ts）+ 反哺新鲜度 + 强锁留痕"""
import os
import time

from app.core import state as st


def _mk_proj(tmp_path, prose="第四章正文。" * 10):
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    path = os.path.join(proj, "正文", "第004章_柳三更.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prose)
    return proj, path


def _state_with_findings(ts):
    return {"review_findings": {"4": {"verdict": "PASS_WITH_NOTES", "items": [],
                                       "blocking": [], "advisory": [], "ts": ts}}}


def test_stale_when_file_modified_after_verdict(tmp_path):
    proj, path = _mk_proj(tmp_path)
    state = _state_with_findings("2026-09-01 10:35:23")
    st.save_state(proj, state)
    os.utime(path, (time.time(), time.time()))     # 文件比结论新
    assert st.is_review_stale(proj, st.load_state(proj), 4) is True


def test_fresh_when_verdict_newer_than_file(tmp_path):
    proj, path = _mk_proj(tmp_path)
    past = time.time() - 3600
    os.utime(path, (past, past))                   # 文件比结论旧
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state = _state_with_findings(ts)
    st.save_state(proj, state)
    assert st.is_review_stale(proj, st.load_state(proj), 4) is False


def test_legacy_data_without_ts_never_stale(tmp_path):
    proj, _path = _mk_proj(tmp_path)
    state = {"review_findings": {"4": {"verdict": "PASS", "items": [],
                                        "blocking": [], "advisory": []}}}
    st.save_state(proj, state)
    assert st.is_review_stale(proj, st.load_state(proj), 4) is False
    # 完全没有 findings / 没有正文文件也不误报
    st.save_state(proj, {})
    assert st.is_review_stale(proj, st.load_state(proj), 4) is False
    assert st.is_review_stale(proj, st.load_state(proj), 9) is False


def test_same_second_write_within_tolerance(tmp_path):
    """ts 截断到秒：结论与正文同秒落盘不得误判陈旧"""
    proj, path = _mk_proj(tmp_path)
    state = _state_with_findings(
        time.strftime("%Y-%m-%d %H:%M:%S"))        # 结论=现在
    st.save_state(proj, state)                     # 文件刚写完，同秒
    assert st.is_review_stale(proj, st.load_state(proj), 4) is False


def test_backflow_freshness(tmp_path):
    proj, path = _mk_proj(tmp_path)
    state = st.load_state(proj)
    assert st.backflow_is_fresh(proj, state, 4) is False   # 未登记 → 不新鲜
    st.mark_backflowed(proj, state, 4, "登记2实体")
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    assert st.backflow_is_fresh(proj, st.load_state(proj), 4) is True
    os.utime(path, (time.time() + 3600, time.time() + 3600))   # 登记后又改了
    assert st.backflow_is_fresh(proj, st.load_state(proj), 4) is False


def test_record_forced_lock(tmp_path):
    proj, _path = _mk_proj(tmp_path)
    state = st.load_state(proj)
    st.record_forced_lock(proj, state, 4, "[字数] 实际2407<下限2700")
    rec = st.load_state(proj)["forced_locks"]["4"]
    assert "字数" in rec["reason"] and rec["ts"]
