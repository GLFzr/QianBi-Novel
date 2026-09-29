# -*- coding: utf-8 -*-
"""Orchestrator.run 五条主路径冒烟网（B4/C02，B3 切段安全网）

钉住 orchestrator.run（:339-529）的五条出口语义：
  1. 全绿 done     —— 所有产物齐备时循环退出 → 状态 done + sig_finished("done")
  2. G1 回退       —— 设定门回退（gate 返回 None）→ 设定归档清除 + sig_finished("stopped")
  3. G9 同章重跑   —— 定稿门回退 → done_nums 丢弃本章，循环以相同章号重跑后放行
  4. 中停          —— stop() 置位后下一个 checkpoint 抛 PipelineStopped → 落盘 + stopped
  5. 异常 dump     —— 任意异常 → pipeline_debug 失败现场 + sig_failed

门与 stage 用脚本替身（与 test_chapter_resume 的假件同思路）：被测对象是 run()
的分支与收尾逻辑，不是门线程机制与 stage 内部。除被脚本替身的两个接缝外，
state/project/diagnostics/信号收尾全部真身。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app import project as pj
from app.core import state as st
from app.core import stages
from app.core.orchestrator import Orchestrator as _Orch


# ---------- 假件 ----------

class _SigCollector:
    """信号收集（同线程直连，emit 即同步到达）"""

    def __init__(self, orch):
        self.finished, self.failed, self.stage_keys, self.logs = [], [], [], []
        orch.sig_finished.connect(self.finished.append)
        orch.sig_failed.connect(self.failed.append)
        orch.sig_stage.connect(self.stage_keys.append)
        orch.sig_log.connect(lambda lvl, msg: self.logs.append((lvl, msg)))


class _ScriptedOrchestrator(_Orch):
    """门/checkpoint 脚本化的 Orchestrator 子类。

    只拦两个接缝：gate() 按脚本放行/回退（None 时调真身 _apply_rollback，
    与真 gate 回退语义一致）；checkpoint() 可在第 N 次调用时走真身 stop()。
    其余（信号收尾/state/project/diagnostics）全部真身。
    """

    def __init__(self, proj, cfg, gate_script=None, stop_at_ckpt=0):
        super().__init__(proj, cfg)
        self._gate_script = {k: list(v) for k, v in (gate_script or {}).items()}
        self._stop_at_ckpt = stop_at_ckpt
        self._ckpt_calls = 0
        self.gate_calls = []

    def gate(self, key, summary="", chapter=0):
        self.gate_calls.append((key, chapter))
        seq = self._gate_script.get(key) or []
        if seq:
            ret = seq.pop(0)
            if ret is None:
                self._apply_rollback(key, chapter)
                return None
            return ret
        return ""

    def checkpoint(self):
        self._ckpt_calls += 1
        if self._stop_at_ckpt and self._ckpt_calls >= self._stop_at_ckpt:
            self.stop()                # 真身停止语义：置位 + 唤醒所有等待点
        super().checkpoint()           # 真身：_stop 置位 → raise PipelineStopped


def _mk_proj(tmp_path, *, setting=True, outline=True, worldbook=True,
             ch_outline=True, chapter=False, total=1):
    proj = str(tmp_path / "冒烟书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    if setting:
        pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    if outline:
        pj.write_file(os.path.join(proj, "大纲", "大纲.md"), "## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n")
    if worldbook:
        pj.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n边陲小城，灵气稀薄。\n")
    if ch_outline:
        pj.write_file(pj.get_outline_path(proj, 1),
                      "### 第 1 章：开端\n- 核心事件：少年拾到玉简\n")
    if chapter:
        pj.write_file(pj.get_chapter_path(proj, 1, "开端"),
                      "## 第1章 开端\n\n" + "正文内容。" * 100)
    state = st.load_state(proj)
    state["total_chapters"] = total
    st.save_state(proj, state)
    return proj


def _cfg():
    return {"connections": [{"id": "t1", "name": "fake", "provider": "custom",
                             "base_url": "http://fake.invalid", "api_key": "sk-t",
                             "model": "fake-model"}],
            "slots": {"writing": "t1", "helper": "t1", "review": "t1"},
            "writing": {"chapter_word_target": 600},
            "gates": {"review_enabled": False},
            "llm": {"max_retries": 0}}


# ---------- 1. 全绿 done ----------

def test_run_all_green_finishes_done(tmp_path):
    proj = _mk_proj(tmp_path, chapter=True)
    orch = _ScriptedOrchestrator(proj, _cfg())
    sig = _SigCollector(orch)
    orch.run()
    assert sig.finished == ["done"], f"全绿应发 done，实发 {sig.finished}"
    assert sig.failed == []
    assert st.load_state(proj).get("stage") == st.STAGE_DONE
    assert orch.gate_calls == [], "续跑全绿路径不应停靠任何决策门"


# ---------- 2. G1 回退 ----------

def test_run_g1_rollback_stops_and_rearchives_setting(tmp_path, monkeypatch):
    proj = _mk_proj(tmp_path, setting=False)   # 设定缺失 → 走阶段① → G1
    monkeypatch.setattr(stages, "stage_core_setting",
                        lambda ctx: pj.write_file(
                            os.path.join(ctx.proj, "设定", "题材定位.md"),
                            "## 主要角色表\n- 陈青山：凡人少年（本波生成）\n"),
                        raising=True)
    orch = _ScriptedOrchestrator(proj, _cfg(), gate_script={"G1": [None]})
    sig = _SigCollector(orch)
    orch.run()
    assert sig.finished == ["stopped"], "G1 回退应归一收尾 stopped（P0-2）"
    assert sig.failed == []
    assert st.load_state(proj).get("stage") == st.STAGE_SETTING, "回退后状态停在设定阶段（缺失即重跑）"
    assert not os.path.exists(os.path.join(proj, "设定", "题材定位.md")), "回退应归档并清除核心设定"
    assert ("G1", 0) in orch.gate_calls
    roll_root = os.path.join(proj, "pipeline_debug", "rollback")
    archived = [os.path.join(r, f) for r, _d, fs in os.walk(roll_root)
                for f in fs] if os.path.isdir(roll_root) else []
    assert any("题材定位" in p for p in archived), "被清除的设定应有归档副本"


# ---------- 3. G9 同章重跑 ----------

def test_run_g9_rollback_reruns_same_chapter(tmp_path, monkeypatch):
    proj = _mk_proj(tmp_path)   # 第1章缺失 → 微循环 → G9 首次回退 → 同章重跑
    calls = []

    def fake_micro(ctx, num, guidance="", ideas=None):
        calls.append(num)
        pj.write_file(pj.get_chapter_path(proj, num, "开端"),
                      "## 第1章 开端\n\n" + "重跑落库正文。" * 100)
        return {"num": num, "title": "开端", "words": 600,
                "review_blocking": 0, "status": "pass"}

    monkeypatch.setattr(stages, "chapter_microcycle", fake_micro, raising=True)
    orch = _ScriptedOrchestrator(proj, _cfg(), gate_script={"G9": [None, ""]})
    sig = _SigCollector(orch)
    orch.run()
    assert calls == [1, 1], f"G9 回退后应以相同章号重跑微循环，实跑 {calls}"
    assert ("G9", 1) in orch.gate_calls and orch.gate_calls.count(("G9", 1)) == 2
    assert sig.finished == ["done"], "第二次放行后应正常完本"
    assert st.load_state(proj).get("stage") == st.STAGE_DONE
    assert len(pj.list_chapters(proj)) == 1, "同章重跑不产生重复章文件"


# ---------- 4. 中停 ----------

def test_run_midrun_stop_saves_progress(tmp_path, monkeypatch):
    proj = _mk_proj(tmp_path)   # 第1章缺失，停在章循环第一个 checkpoint
    monkeypatch.setattr(stages, "chapter_microcycle",
                        lambda ctx, num, guidance="", ideas=None: (_ for _ in ()).throw(
                            AssertionError("中停后不许进入微循环")), raising=True)
    orch = _ScriptedOrchestrator(proj, _cfg(), stop_at_ckpt=1)
    sig = _SigCollector(orch)
    orch.run()
    assert sig.finished == ["stopped"], "中停应发 stopped"
    assert sig.failed == []
    assert any("进度已保存" in msg for _lvl, msg in sig.logs), "停止回执必须带「进度已保存」"
    # WP-25：说落盘就真落盘——状态文件可解析往返
    state = st.load_state(proj)
    assert isinstance(state, dict) and "total_chapters" in state
    assert pj.chapter_nums(proj) == set(), "停在章循环起点，本章不应已落库"


# ---------- 5. 异常 dump ----------

def test_run_exception_dumps_failure(tmp_path, monkeypatch):
    proj = _mk_proj(tmp_path, worldbook=False)   # 世界书缺失 → 阶段②.5 抛异常
    def boom(ctx):
        raise RuntimeError("世界书生成爆炸")
    monkeypatch.setattr(stages, "stage_worldbook_gen", boom, raising=True)
    orch = _ScriptedOrchestrator(proj, _cfg())
    sig = _SigCollector(orch)
    orch.run()
    assert sig.finished == [], "异常路径不发 finished"
    assert len(sig.failed) == 1 and "世界书生成爆炸" in sig.failed[0]
    debug_dir = os.path.join(proj, "pipeline_debug")
    dumps = [os.path.join(debug_dir, f) for f in os.listdir(debug_dir)
             if f.startswith("failure_")] if os.path.isdir(debug_dir) else []
    assert dumps, "异常必须落失败现场文件"
    with open(dumps[0], encoding="utf-8") as fh:
        assert "世界书生成爆炸" in fh.read(), "失败现场应包含异常信息"
