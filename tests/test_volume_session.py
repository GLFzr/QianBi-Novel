# -*- coding: utf-8 -*-
"""卷级会话消息栈（VolumeSession，S1）+ stages 最小集成 单元测试

覆盖（任务 ①-⑥ + 断点播种）：
①  flag 关闭：chapter_microcycle 构造的仍是 ChapterSession，system = project_header
    + chapter_header 双层前缀，首轮不带开幕声明（请求体字节不变锁）；
②  flag 开启：system 只含 project_header，章头 + 开幕声明进本章开幕轮；
③  两章连跑：消息栈单调增长，第 2 章各轮请求都能看到第 1 章历史；
④  持久化 round-trip：save → load 后消息逐字节一致（服务端缓存继续有效）；
⑤  rollback_to 跨章回退：回退到上一章末尾后栈被正确截断、章开幕状态作废；
⑥  append-only 落盘：save 两次不重写历史行，增量只追加。
另：open_chapter 待固化语义（失败不固化）/ 同章重入截断 / restart_with_prose
不清栈 / 卷号解析 / 断点续跑播种（卷栈缺本章历史时并入盘上草稿）。

全部使用内存假件 + 临时项目目录，禁止任何真实 API 调用。
"""
import hashlib
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from app import project as pj
from app.core import memory as mem
from app.core import state as st
from app.core.chapter_session import ChapterSession
from app.core.shared_prefix import chapter_header, project_header
from app.core.volume_session import (VolumeSession, chapter_of_opening,
                                     opening_marker, resolve_volume_number,
                                     volume_messages_path)


# ---------------- 假件（对齐 tests/test_chapter_session.py） ----------------

class FakeClient:
    """chat_turn 替身：记录调用参数，按脚本依次返回（或恒抛错）"""

    def __init__(self, replies=None, error=None):
        self.calls = []   # [(messages, kwargs), ...]
        self.replies = list(replies) if replies is not None else ["回复"]
        self.error = error

    def chat_turn(self, messages, *, on_chunk=None, on_reasoning=None,
                  phase="", temperature=None, abort=None):
        self.calls.append((messages, dict(on_chunk=on_chunk, on_reasoning=on_reasoning,
                                          phase=phase, temperature=temperature,
                                          abort=abort)))
        if self.error is not None:
            raise self.error
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


class FlakyClient:
    """第一次调用抛错、之后成功：验证失败不固化、待固化内容保留"""

    def __init__(self):
        self.calls = []

    def chat_turn(self, messages, **kw):
        self.calls.append(messages)
        if len(self.calls) == 1:
            raise RuntimeError("第一次调用失败")
        return "恢复回复"


def _prose_fixture(num: int, target: int = 60) -> str:
    """构造能过字数闸门与去味扫描的正文替身（count_chars 精确凑到 target）"""
    base = (f"# 第{num}章 开端\n\n雨停了。少年收起纸伞，沿巷口往东走。\n"
            "他数着脚下的青石板，第七块有一道裂缝。")
    pad = target - pj.count_chars(base)
    if pad > 0:
        base += "云" * pad
    return base


class CycleClient:
    """chapter_microcycle 假客户端：chat_turn=会话轮（逐次记录 messages），
    chat_stream/chat=单轮旁路（清算等）。回复按相位路由，不触网。"""

    def __init__(self, word_target=60):
        self.turn_calls = []      # [(messages, phase), ...]
        self.stream_prompts = []  # 单发旁路（canon_audit）
        self.prose_n = 0
        self.word_target = word_target

    def chat_turn(self, messages, *, on_chunk=None, on_reasoning=None,
                  phase="", temperature=None, abort=None):
        self.turn_calls.append(([dict(m) for m in messages], phase))
        return self._reply(phase)

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, phase="",
                    temperature=None, **kw):
        self.stream_prompts.append(prompt)
        return "（清算输出非 JSON）"

    def chat(self, prompt, phase="", **kw):
        return "（无）"

    def _reply(self, phase):
        if phase == "prose":
            self.prose_n += 1
            return _prose_fixture(self.prose_n, self.word_target)
        if phase == "chapter_summary":
            return f"第{self.prose_n}章：少年在巷口拾到玉简。"
        if phase == "global_summary":
            return "少年获得玉简，修行起步。"
        return "（无）"


class CycleCtx:
    """chapter_microcycle 假 ctx：决策门全放行、无轨迹容器；volume_sessions
    对齐 orchestrator.run 持有的按卷缓存（S1 生命周期挂在 ctx 上）。"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.last_prompt = ""
        self.stopped = False
        self.volume_sessions = {}
        self.logs = []

    def log(self, level, msg):
        self.logs.append((level, msg))

    def step(self, num, step_key):
        pass

    def checkpoint(self):
        pass

    def gate(self, key, summary="", chapter=0):
        return ""

    def consume_gate_idea(self):
        return ""

    def stream_stage(self, label):
        pass

    def stream_chunk(self, text):
        pass

    def stream_reasoning(self, text):
        pass


class _FakeRouter:
    def __init__(self, client):
        self._client = client

    def client(self, slot):
        return self._client


SYS = "全书前缀P"     # 卷会话 system：只含 project_header（替身语境）


# ---------------- Part A：VolumeSession 消息栈语义 ----------------

def test_open_chapter_composes_opening_turn_and_stack_grows():
    """②（单元面）：system 只含传入前缀；章头+开幕声明并入开幕 user 轮"""
    c = FakeClient(["第2章正文稿"])
    s = VolumeSession(c, SYS, proj="")
    assert s.enabled is True
    assert s.system_text == SYS
    opening = s.open_chapter("【第 2 章共享上下文】细纲摘要", "写第2章正文", chapter_num=2)
    # open_chapter 只合成不推栈：开幕轮在下次 ask 成功时原子固化
    assert s.snapshot() == [{"role": "system", "content": SYS}]
    assert opening.startswith("【第 2 章开幕：以下为本章共享上下文与写作指令，"
                              "本章正文以本次回复为准】\n\n【第 2 章共享上下文】")
    assert opening.endswith("\n\n写第2章正文")
    out = s.ask("写第2章正文")
    assert out == "第2章正文稿"
    # 请求 = 栈 + 开幕轮（开幕轮顶替 ask 的 user_text，不产生两条 user）
    assert c.calls[0][0] == [{"role": "system", "content": SYS},
                             {"role": "user", "content": opening}]
    assert s.snapshot() == [{"role": "system", "content": SYS},
                            {"role": "user", "content": opening},
                            {"role": "assistant", "content": "第2章正文稿"}]
    assert s.turn_count() == 1 and s.current_chapter == 2
    assert chapter_of_opening(opening) == 2


def test_two_chapters_stack_monotonic_and_ch2_sees_ch1_history():
    """③（单元面）：两章连跑栈单调增长，第 2 章请求可见第 1 章历史"""
    c = FakeClient(["1章稿", "1章审校结论", "2章稿"])
    s = VolumeSession(c, SYS, proj="")
    t1_open = s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")
    s.ask("审校第1章")                       # 第 1 章的追加相位轮
    ch1_msgs = s.snapshot()
    t2_open = s.open_chapter("章头2", "写第2章", chapter_num=2)
    s.ask("写第2章")
    msgs = s.snapshot()
    # 单调增长：开幕轮与回复只追加、不改写历史
    assert len(msgs) == len(ch1_msgs) + 2
    assert msgs[:len(ch1_msgs)] == ch1_msgs
    # 第 2 章的首轮请求带着第 1 章全部历史（前缀逐字节复用）
    req = c.calls[2][0]
    assert req[0] == {"role": "system", "content": SYS}
    assert {"role": "user", "content": t1_open} in req
    assert {"role": "assistant", "content": "1章稿"} in req
    assert {"role": "assistant", "content": "1章审校结论"} in req
    assert req[-1] == {"role": "user", "content": t2_open}
    assert "章头1" in t1_open and "章头2" in t2_open


def test_open_chapter_retry_failure_keeps_pending():
    """ask 失败不固化任何轮；开幕轮保留（重试仍带）——章会话异常安全同纪律"""
    c = FlakyClient()
    s = VolumeSession(c, SYS, proj="")
    opening = s.open_chapter("章头1", "写第1章", chapter_num=1)
    with pytest.raises(RuntimeError):
        s.ask("写第1章")
    assert s.snapshot() == [{"role": "system", "content": SYS}]
    assert s.turn_count() == 0
    out = s.ask("写第1章")                 # 重试仍以开幕轮为 user 内容
    assert out == "恢复回复"
    assert c.calls[1][-1]["content"] == opening   # FlakyClient.calls 存的是消息列表
    assert s.turn_count() == 1


def test_open_chapter_same_chapter_reroll_truncates_previous_attempt():
    """同章重入（G9 重写本章）：先截回本章开幕前，上一轮尝试不留进历史"""
    c = FakeClient(["旧稿", "新稿"])
    s = VolumeSession(c, SYS, proj="")
    s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")                        # ch1：1 轮
    before_ch2 = s.turn_count()
    s.open_chapter("章头2", "写第2章", chapter_num=2)
    s.ask("写第2章")                        # ch2 第一次尝试
    assert s.turn_count() == before_ch2 + 1
    opening2 = s.open_chapter("章头2", "写第2章", chapter_num=2)   # 同章重开
    assert s.turn_count() == before_ch2     # 旧尝试已截断
    assert all("第 2 章开幕" not in m["content"] for m in s.snapshot())
    s.ask("写第2章")
    assert s.turn_count() == before_ch2 + 1
    assert c.calls[2][0][-1]["content"] == opening2
    assert s.snapshot()[-1] == {"role": "assistant", "content": "新稿"}


def test_rollback_across_chapters_truncates_and_voids_opening():
    """⑤：跨章回退到上一章末尾——栈截断正确、本章开幕状态作废"""
    c = FakeClient(["1章稿", "2章稿"])
    s = VolumeSession(c, SYS, proj="")
    s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")
    ch1_end = s.turn_count()
    ch1_msgs = s.snapshot()
    s.open_chapter("章头2", "写第2章", chapter_num=2)
    s.ask("写第2章")
    assert s.turn_count() == ch1_end + 1 and s.current_chapter == 2
    s.rollback_to(ch1_end)                  # 回退到上一章末尾（跨章）
    assert s.turn_count() == ch1_end
    assert s.snapshot() == ch1_msgs         # 与第 1 章结束时逐字节一致
    assert s.current_chapter == 0           # 第 2 章开幕已随截断作废
    assert all("第 2 章开幕" not in m["content"] for m in s.snapshot())
    with pytest.raises(ValueError):
        s.rollback_to(ch1_end + 1)          # 越界守卫与章会话一致
    assert s.snapshot() == ch1_msgs         # 越界拒绝不破坏栈


def test_commit_turn_and_snapshot_semantics_inherited():
    """commit_turn/snapshot 深拷贝语义与 ChapterSession 完全一致（继承复用）"""
    c = FakeClient()
    s = VolumeSession(c, SYS, proj="")
    s.commit_turn("投票", "胜出稿")
    snap = s.snapshot()
    snap[1]["content"] = "篡改"
    snap.append({"role": "user", "content": "注入"})
    assert s.snapshot() == [{"role": "system", "content": SYS},
                            {"role": "user", "content": "投票"},
                            {"role": "assistant", "content": "胜出稿"}]


def test_restart_with_prose_keeps_cross_chapter_history():
    """restart_with_prose（卷栈语义）：不清栈，种子并入下一次 ask"""
    c = FakeClient(["1章稿", "续跑审校"])
    s = VolumeSession(c, SYS, proj="")
    s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")
    stack_after_ch1 = s.snapshot()
    s.restart_with_prose("盘上正文")        # 断点续跑：不重置 1..N-1 章
    assert s.snapshot() == stack_after_ch1
    s.ask("审校")
    assert c.calls[1][0][-1]["content"] == "## 本章正文\n盘上正文\n\n审校"
    assert s.snapshot()[-2]["content"].startswith("## 本章正文\n盘上正文")


def test_seed_prose_same_chapter_reroll_truncates_first():
    """seed_prose 对同章重入先截回章开幕前，防双份正文进历史"""
    c = FakeClient(["旧稿", "审校结论"])
    s = VolumeSession(c, SYS, proj="")
    s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")
    base = s.turn_count()
    s.open_chapter("章头2", "写第2章", chapter_num=2)
    s.ask("写第2章")
    s.seed_prose("盘上第2章稿", chapter_num=2)   # 同章重入：先截断旧尝试
    assert s.turn_count() == base
    assert all("第 2 章开幕" not in m["content"] for m in s.snapshot())
    s.ask("审校")
    assert c.calls[2][0][-1]["content"].startswith("## 本章正文\n盘上第2章稿")


def test_disabled_session_contract():
    s = VolumeSession(FakeClient(), SYS, proj="", enabled=False)
    assert s.enabled is False
    with pytest.raises(RuntimeError):
        s.ask("u")
    assert s.snapshot() == [{"role": "system", "content": SYS}]


def test_client_without_chat_turn_disables_session():
    class LegacyClient:
        def chat_stream(self, *a, **k):
            return "旧路径"

    s = VolumeSession(LegacyClient(), SYS, proj="", enabled=True)
    assert s.enabled is False
    with pytest.raises(RuntimeError):
        s.ask("u")


def test_volume_session_is_chapter_session_subclass():
    """rollback/commit/snapshot 语义与 ChapterSession 完全一致的实现方式：继承"""
    assert issubclass(VolumeSession, ChapterSession)


# ---------------- Part A：持久化（④⑥）与卷号解析 ----------------

def _build_two_chapter_stack(tmp_path):
    path = volume_messages_path(str(tmp_path), 1)
    c = FakeClient(["1章稿", "1章审校", "2章稿"])
    s = VolumeSession(c, SYS, volume=1, proj=str(tmp_path))
    assert s.messages_path == path
    s.open_chapter("章头1", "写第1章", chapter_num=1)
    s.ask("写第1章")
    s.ask("审校第1章")
    s.open_chapter("章头2", "写第2章", chapter_num=2)
    s.ask("写第2章")
    return s, path


def test_save_load_roundtrip_byte_identical(tmp_path):
    """④：save → load 后消息逐字节一致（服务端前缀缓存继续有效）"""
    s, path = _build_two_chapter_stack(tmp_path)
    assert s.save() == path
    raw1 = open(path, "rb").read()
    s.save()                                 # 幂等：无新消息不写盘
    assert open(path, "rb").read() == raw1
    # 新进程语境：同 system 构造空栈后 load 恢复
    s2 = VolumeSession(FakeClient(), SYS, volume=1, proj=str(tmp_path))
    assert s2.load(path) is True
    assert json.dumps(s2.snapshot(), ensure_ascii=False) == \
        json.dumps(s.snapshot(), ensure_ascii=False)
    assert s2.turn_count() == s.turn_count()
    assert s2.current_chapter == s.current_chapter == 2
    assert s2.snapshot()[1]["content"].startswith(opening_marker(1)[:12])
    # 恢复后的会话可继续追加：请求前缀与旧栈逐字节一致（缓存不 miss）
    c2 = s2._client
    s2.ask("审校第2章")
    req = c2.calls[0][0]
    assert req[:-1] == s.snapshot()


def test_save_is_append_only_history_lines_never_rewritten(tmp_path):
    """⑥：save 两次不重写历史行；增量只追加（旧内容是新内容的严格前缀）"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    lines1 = open(path, "r", encoding="utf-8").read().splitlines()
    assert len(lines1) == len(s.snapshot())
    assert all(json.loads(ln)["role"] in ("system", "user", "assistant")
               for ln in lines1)
    assert json.loads(lines1[0])["content"] == SYS
    s.ask("审校第2章")                       # 追加一轮后再 save
    s.save()
    lines2 = open(path, "r", encoding="utf-8").read().splitlines()
    assert lines2[:len(lines1)] == lines1    # 历史行逐字节不动
    assert len(lines2) == len(lines1) + 2    # 只追加新轮的两条消息


def test_save_after_rollback_rewrites_truncated_file(tmp_path):
    """回退到已落盘游标之下：落盘整文重写为截断后的栈（防恢复读回废稿）"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    ch1_end = s.turn_count() - 1
    s.rollback_to(ch1_end)                   # rollback 内部已触发落盘重写
    lines = open(path, "r", encoding="utf-8").read().splitlines()
    assert len(lines) == len(s.snapshot())
    assert json.loads(lines[-1])["content"] == "1章审校"


def test_load_rejects_changed_system_and_missing_file(tmp_path):
    """W-3：system（全书前缀）变化 / 文件缺失 → 拒绝恢复，原因记在 sess.reject"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    s2 = VolumeSession(FakeClient(), "另一套全书前缀", volume=1, proj=str(tmp_path))
    assert s2.load(path) is False
    assert s2.snapshot() == [{"role": "system", "content": "另一套全书前缀"}]
    assert s2.turn_count() == 0
    assert s2.reject["event"] == "system_mismatch"
    s4 = VolumeSession(FakeClient(), SYS, volume=1, proj=str(tmp_path))
    assert s4.load(os.path.join(str(tmp_path), "会话", "不存在.jsonl")) is False
    assert s4.reject["event"] == "stack_missing"
    assert s4.turn_count() == 0


def _session_events(tmp_path):
    p = os.path.join(str(tmp_path), "追踪", "session_events.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def test_load_truncates_at_corrupt_line_keeps_prefix(tmp_path):
    """W-3 核心：中途一行坏 → 只丢该行之后，前缀完好部分照恢复（旧行为=全栈弃）

    截断结果必须原子写回文件：否则后续 append 落在坏行**之后**，这段历史再也读不回。
    """
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    good = open(path, encoding="utf-8").read().splitlines()
    assert len(good) == 7
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(good[:3]) + "\n{broken json\n" + good[3] + "\n")
    s2 = VolumeSession(FakeClient(), SYS, volume=1, proj=str(tmp_path))
    assert s2.load(path) is True
    assert s2.turn_count() == 1                     # 只保住坏行之前那一轮
    assert [m["content"] for m in s2.snapshot()] == \
        [json.loads(ln)["content"] for ln in good[:3]]
    assert open(path, encoding="utf-8").read().splitlines() == good[:3]
    assert "{broken json" in open(path + ".corrupt", encoding="utf-8").read()
    ev = _session_events(tmp_path)
    assert [e["event"] for e in ev] == ["stack_truncated"]
    assert ev[0]["dropped_lines"] == 2 and ev[0]["kept"] == 3
    # 恢复后的栈照常追加，且新行紧接好前缀 → 再 load 不受坏行影响
    s2.ask("续写第2章")
    s2.save()
    s3 = VolumeSession(FakeClient(), SYS, volume=1, proj=str(tmp_path))
    assert s3.load(path) is True
    assert s3.turn_count() == 2


def test_load_rejects_when_first_line_corrupt(tmp_path):
    """首行就坏（连 system 都读不出）→ 无段可保，仍拒绝恢复并记事件"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    good = open(path, encoding="utf-8").read().splitlines()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("{broken json\n" + "\n".join(good[1:]) + "\n")
    s2 = VolumeSession(FakeClient(), SYS, volume=1, proj=str(tmp_path))
    assert s2.load(path) is False
    assert s2.reject["event"] == "stack_first_line_corrupt"
    assert s2.turn_count() == 0
    assert open(path, encoding="utf-8").read().splitlines() == ["{broken json"] + good[1:]


def test_system_mismatch_reject_reports_discarded_volume(tmp_path):
    """W-3：整栈作废的告警必须带体积——丢几轮、约多少 tok、一次全量 miss 多少钱"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    s2 = VolumeSession(FakeClient(), "另一套全书前缀", volume=1, proj=str(tmp_path))
    assert s2.load(path) is False
    r = s2.reject
    assert r["turns"] == 3 and r["tok"] > 0
    assert r["cost"] == pytest.approx(r["tok"] / 1e6 * 1.584, abs=1e-4)
    ev = _session_events(tmp_path)
    assert ev and ev[-1]["event"] == "system_mismatch"
    assert ev[-1]["turns"] == 3 and ev[-1]["cost"] == r["cost"]


def test_rollback_rewrite_leaves_no_half_file(tmp_path):
    """W-3：回退触发的整文重写走 tmp+os.replace ⇒ 目录里不留 .tmp 半文件"""
    s, path = _build_two_chapter_stack(tmp_path)
    s.save()
    s.rollback_to(1)
    d = os.path.dirname(path)
    assert sorted(os.listdir(d)) == ["卷1_messages.jsonl"]
    assert json.loads(open(path, encoding="utf-8").read().splitlines()[-1])["content"] == \
        s.snapshot()[-1]["content"]


def test_acquire_volume_session_failure_is_counted(tmp_path, monkeypatch):
    """W-3：取卷会话异常不再静默——告警带异常类名，且落 acquire_failed 事件可数

    实例：fd7b8fe 前缺一个导出符号 → AttributeError 被吞 → v7_long13 整卷无会话，
    跑完都看不出来。
    """
    from app.core import stages as sg
    import app.core.volume_session as vs

    def boom(*a, **kw):
        raise AttributeError("module 'prompts' has no attribute 'review_static_tail'")

    monkeypatch.setattr(vs, "resolve_volume_number", boom)

    class Ctx:
        def __init__(self):
            self.volume_sessions = {}
            self.logs = []

        def log(self, level, msg):
            self.logs.append((level, msg))

    ctx = Ctx()
    assert sg._acquire_volume_session(ctx, str(tmp_path), 7) is None
    assert any(lvl == "warn" and "AttributeError" in msg and "无会话" in msg
               for lvl, msg in ctx.logs)
    ev = _session_events(tmp_path)
    assert [e["event"] for e in ev] == ["acquire_failed"]
    assert ev[0]["chapter"] == 7 and "AttributeError" in ev[0]["err"]


def test_resolve_volume_number_from_outline(tmp_path):
    """章号→卷号：按大纲卷级「N章」声明累计切分；无声明回退卷 1"""
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
    outline = os.path.join(proj, "大纲", "大纲.md")
    with open(outline, "w", encoding="utf-8") as f:
        f.write("## 卷级大纲\n\n### 第一卷：边陲凡尘（约15万字，50章）\n- 功能：起步\n"
                "\n### 第二卷：风起（约9万字，30章）\n- 功能：扩张\n")
    assert resolve_volume_number(proj, 1) == 1
    assert resolve_volume_number(proj, 50) == 1
    assert resolve_volume_number(proj, 51) == 2
    assert resolve_volume_number(proj, 80) == 2
    assert resolve_volume_number(proj, 999) == 2   # 超出声明 → 最后一卷兜底
    with open(outline, "w", encoding="utf-8") as f:
        f.write("# 全书大纲（自由体，无卷声明）\n")
    assert resolve_volume_number(proj, 7) == 1     # 解析失败回退卷 1
    assert volume_messages_path(proj, 3).endswith(
        os.path.join("会话", "卷3_messages.jsonl"))


def _write_outline(tmp_path, text):
    os.makedirs(os.path.join(str(tmp_path), "大纲"), exist_ok=True)
    with open(os.path.join(str(tmp_path), "大纲", "大纲.md"), "w",
              encoding="utf-8") as f:
        f.write(text)
    return str(tmp_path)


def test_resolve_volume_number_range_form(tmp_path):
    """W-1：「（第14-25章…）」的 25 是本卷**末章号**，不是章数——按绝对章号切卷界

    旧解析把区间末章号当章数累加 ⇒ t3_long60 的真卷界 13/25/37/46/50 被算成
    13/38/75/121/171 ⇒ 26 章起永不换栈（栈长实测 88 万 tok）。"""
    proj = _write_outline(tmp_path, (
        "## 卷级大纲\n\n"
        "## 第一卷：空页（第1-13章，约2.6万字）\n"
        "## 第二卷：旧账（第14-25章，约2.4万字）\n"
        "## 第三卷：墨痕（第26-37章，约2.4万字）\n"
        "## 第四卷：收账（第38-46章，约1.8万字）\n"
        "## 第五卷：不可贪（第47-50章，约0.8万字）\n"))
    for n in (1, 12, 13):
        assert resolve_volume_number(proj, n) == 1
    for n in (14, 24, 25):
        assert resolve_volume_number(proj, n) == 2
    for n in (26, 37):                        # 旧实现此处返回 2
        assert resolve_volume_number(proj, n) == 3
    for n in (38, 46):                        # 旧实现返回 2
        assert resolve_volume_number(proj, n) == 4
    for n in (47, 50, 51, 60):                # 旧实现返回 3；超出末卷兜底
        assert resolve_volume_number(proj, n) == 5


def test_resolve_volume_number_range_form_chapter_style(tmp_path):
    """「第1章-第60章」逐章写法同样取末章号（旧实现会抓到 1 当章数）"""
    proj = _write_outline(tmp_path, (
        "### 第一卷：杂役之怒（第1章-第60章，约15万字）\n"
        "### 第二卷：坊市风波（第61章-第150章，约20万字）\n"))
    assert resolve_volume_number(proj, 60) == 1
    assert resolve_volume_number(proj, 61) == 2
    assert resolve_volume_number(proj, 150) == 2


def test_resolve_volume_number_mixed_range_and_count(tmp_path):
    """混合大纲：区间声明给绝对边界，其后的章数声明从上一卷末章 +1 续算"""
    proj = _write_outline(tmp_path, (
        "## 第一卷：空页（第1-13章）\n"
        "## 第二卷：旧账（第14-25章）\n"
        "## 第三卷：墨痕（约2.4万字，12章）\n"
        "## 第四卷：无名\n"))                   # 无任何章号声明 → 跳过
    assert resolve_volume_number(proj, 25) == 2
    assert resolve_volume_number(proj, 26) == 3
    assert resolve_volume_number(proj, 37) == 3   # 25 + 12 = 37
    assert resolve_volume_number(proj, 38) == 3   # 无声明的卷不成边界 → 末卷兜底


def test_resolve_volume_number_count_form_unchanged(tmp_path):
    """章数式旧写法结果与 W-1 之前逐字节一致（累计求和语义不变）"""
    proj = _write_outline(tmp_path, (
        "### 第一卷：边陲凡尘（约15万字，50章）\n"
        "### 第二卷：初入江湖（约20万字，67章）\n"))
    assert resolve_volume_number(proj, 50) == 1
    assert resolve_volume_number(proj, 51) == 2
    assert resolve_volume_number(proj, 117) == 2
    assert resolve_volume_number(proj, 999) == 2


# ---------------- Part B：stages 集成（chapter_microcycle 端到端，假客户端） ----------------

def _make_proj(tmp_path):
    proj = str(tmp_path / "测试书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"),
                  "## 主要角色表\n- 陈青山：凡人少年，灵根残缺\n")
    pj.write_file(os.path.join(proj, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：边陲凡尘（约3万字，2章）\n")
    for n in (1, 2, 3):
        pj.write_file(pj.get_outline_path(proj, n),
                      f"### 第 {n} 章：开端{n}\n- 核心事件：少年拾到玉简并反杀探子\n"
                      f"- 承接锚点：上一章结尾\n")
    return proj


def _run_microcycle(proj, cfg, client, num, ctx=None):
    from app.core import stages
    if ctx is None:
        ctx = CycleCtx(proj, cfg, client)
    record = stages.chapter_microcycle(ctx, num)
    return ctx, record


def test_flag_off_builds_chapter_session_with_two_layer_system(tmp_path):
    """①（字节不变锁）：flag 关闭时构造的仍是 ChapterSession——system 双层前缀、
    首轮为正文写作指令且不带任何开幕声明（与改造前请求体一致）"""
    proj = _make_proj(tmp_path)
    # 章头依赖追踪文件（微循环会改写它们）：期望值必须在跑之前取样
    expected_sys = f"{project_header(proj)}\n\n{chapter_header(proj, 1)}"
    cfg = {"writing": {"chapter_session": True, "chapter_word_target": 60},
           "gates": {"review_enabled": False}}
    client = CycleClient()
    ctx, record = _run_microcycle(proj, cfg, client, 1)
    assert record["num"] == 1
    assert len(client.turn_calls) >= 1
    sys_msg, first_user = client.turn_calls[0][0][0], client.turn_calls[0][0][1]
    assert sys_msg == {"role": "system", "content": expected_sys}   # 字节不变锁
    assert first_user["role"] == "user"
    assert first_user["content"].startswith("（作用域：")       # session_turn_text 前缀
    assert "写作第 1 章正文" in first_user["content"]
    # 会话首轮不带章头/开幕声明（章头只在 system 里）
    assert "章开幕" not in first_user["content"]
    assert not any("章开幕" in msgs[-1]["content"] for msgs, _ph in client.turn_calls)
    # 卷缓存未被触碰、无落盘
    assert ctx.volume_sessions == {}
    assert not os.path.exists(volume_messages_path(proj, 1))


def test_flag_on_system_project_header_only_header_in_opening_turn(tmp_path):
    """②：flag 开启时 system 只含 project_header；章头 + 开幕声明进开幕轮"""
    proj = _make_proj(tmp_path)
    ch_header1 = chapter_header(proj, 1)     # 同上：跑之前取样
    ph = project_header(proj)
    cfg = {"writing": {"chapter_session": True, "volume_session": True,
                       "chapter_word_target": 60},
           "gates": {"review_enabled": False}}
    client = CycleClient()
    ctx, record = _run_microcycle(proj, cfg, client, 1)
    assert record["num"] == 1
    sys_msg = client.turn_calls[0][0][0]
    opening = client.turn_calls[0][0][1]["content"]
    assert sys_msg == {"role": "system", "content": ph}
    assert ch_header1 in opening              # 章头整体进了开幕轮
    assert opening.startswith("【第 1 章开幕：以下为本章共享上下文与写作指令，"
                              "本章正文以本次回复为准】\n\n")
    # 开幕轮之后的相位轮不再携带章头/开幕声明（历史前缀复用）
    for msgs, _ph in client.turn_calls[1:]:
        assert msgs[0] == {"role": "system", "content": ph}
        assert "章开幕" not in msgs[-1]["content"]
    # 同卷缓存命中：同一 VolumeSession 实例被复用
    assert 1 in ctx.volume_sessions
    sess = ctx.volume_sessions[1]
    assert isinstance(sess, VolumeSession)
    assert sess.current_chapter == 1 and sess.turn_count() == len(client.turn_calls)


def test_in_chapter_checkpoints_persist_stack_before_finalize(tmp_path, monkeypatch):
    """W-3 里程碑落盘：卷栈不再只在章末写一次——崩在章中最多回退到一个里程碑"""
    from app.core import stages as sg
    proj = _make_proj(tmp_path)
    cfg = {"writing": {"chapter_session": True, "volume_session": True,
                       "chapter_word_target": 60},
           "gates": {"review_enabled": True}}
    client = CycleClient()
    saves = []
    real = sg._save_session_checkpoint

    def spy(ctx, session, where=""):
        saves.append((where, session.turn_count() if session is not None else -1))
        return real(ctx, session, where)

    monkeypatch.setattr(sg, "_save_session_checkpoint", spy)
    ctx, _r = _run_microcycle(proj, cfg, client, 1)
    sess = ctx.volume_sessions[1]
    assert saves, "整章没有任何一次卷栈落盘"
    assert any(w == "enrich 后" for w, _n in saves), "enrich 后未落盘"
    assert any(w == "审校后" for w, _n in saves), "审校后未落盘"
    assert saves[-1][0] == "定稿后"
    # 章中那次落盘时栈还没长到最终长度 = 真增量，而不是同一状态写三遍
    assert any(n < sess.turn_count() for _w, n in saves[:-1])
    path = volume_messages_path(proj, 1)
    assert len(open(path, encoding="utf-8").read().splitlines()) == len(sess.snapshot())


def test_two_chapters_share_volume_stack_and_persist_per_chapter(tmp_path):
    """③：两章连跑——栈单调增长、第 2 章各轮可见第 1 章历史；逐章 append-only 落盘"""
    proj = _make_proj(tmp_path)
    cfg = {"writing": {"chapter_session": True, "volume_session": True,
                       "chapter_word_target": 60},
           "gates": {"review_enabled": False}}
    client = CycleClient()
    ctx, _r1 = _run_microcycle(proj, cfg, client, 1)
    path = volume_messages_path(proj, 1)
    assert os.path.exists(path)                          # 逐章落盘
    lines_after_ch1 = open(path, "r", encoding="utf-8").read().splitlines()
    assert len(client.turn_calls) == 4                   # 草稿/追踪/章摘要/全局摘要
    ch_header2 = chapter_header(proj, 2)     # 第 1 章产物已落盘；第 2 章开跑前取样

    ctx, _r2 = _run_microcycle(proj, cfg, client, 2, ctx=ctx)   # 同一 run：同 ctx 续跑
    assert ctx.volume_sessions[1] is ctx.volume_sessions[1]     # 同卷同实例
    calls = client.turn_calls
    assert len(calls) == 8                               # 栈单调增长，无重置
    # 每次请求 = 上次请求 + 本轮回复 + 下一条 user：前缀逐字节复用
    for k in range(len(calls) - 1):
        msgs_prev, msgs_cur = calls[k][0], calls[k + 1][0]
        assert len(msgs_cur) == len(msgs_prev) + 2
        assert msgs_cur[:-1] == msgs_prev + [
            {"role": "assistant", "content": calls[k + 1][0][len(msgs_prev)]["content"]}]
    # 第 2 章各轮都能看到第 1 章历史（第 1 章正文稿与开幕轮在栈内）
    ch1_prose = _prose_fixture(1, 60)
    for msgs, _ph in calls[4:]:
        assert any(m["role"] == "assistant" and m["content"] == ch1_prose
                   for m in msgs)
        assert any("第 1 章开幕" in m["content"] for m in msgs)
    # 第 2 章开幕轮声明本章正文归属
    ch2_opening = calls[4][0][-1]["content"]
    assert ch2_opening.startswith("【第 2 章开幕：")
    assert ch_header2 in ch2_opening
    # append-only：第 2 章落盘只追加
    lines_after_ch2 = open(path, "r", encoding="utf-8").read().splitlines()
    assert lines_after_ch2[:len(lines_after_ch1)] == lines_after_ch1
    assert len(lines_after_ch2) == len(lines_after_ch1) + 8
    # 盘上栈与会话栈逐字节一致
    sess = ctx.volume_sessions[1]
    disk = [json.loads(ln) for ln in lines_after_ch2]
    assert disk == sess.snapshot()


def test_volume_resume_seeds_draft_into_session(tmp_path):
    """断点续跑（卷会话）：卷栈缺本章历史时，盘上草稿经种子并入下一次会话调用"""
    proj = _make_proj(tmp_path)
    cfg = {"writing": {"chapter_session": True, "volume_session": True,
                       "chapter_word_target": 60},
           "gates": {"review_enabled": False}}
    client = CycleClient()
    _run_microcycle(proj, cfg, client, 1)                # 第 1 章完整跑完并落盘
    # 模拟第 2 章崩在中途：草稿在盘、章内断点登记（卷栈只到第 1 章末尾）
    draft = _prose_fixture(2, 60)
    pj.write_file(pj.chapter_draft_path(proj, 2), draft)
    outline = mem.sanitize_chapter_refs(pj.read_file(pj.get_outline_path(proj, 2)))
    fp = hashlib.sha1(outline.encode("utf-8")).hexdigest()[:12]
    st.save_chapter_step(proj, 2, step_done="enrich",
                         draft_path=os.path.relpath(pj.chapter_draft_path(proj, 2), proj),
                         votes=[], outline_fp=fp)
    # 新"进程"：全新 ctx/缓存，卷栈从 jsonl 恢复
    client2 = CycleClient()
    ctx2, record = _run_microcycle(proj, cfg, client2, 2)
    assert record["num"] == 2
    sess = ctx2.volume_sessions[1]
    assert len(client2.turn_calls) == 3                  # 草稿跳过：追踪/两段摘要
    assert sess.turn_count() == 4 + 3                    # 恢复 4 轮 + 本章 3 轮
    msgs0 = client2.turn_calls[0][0]
    # 恢复栈携带第 1 章历史；本次请求 = 恢复栈 + 播种轮
    assert msgs0[0] == {"role": "system", "content": project_header(proj)}
    assert any("第 1 章开幕" in m["content"] for m in msgs0[:-1])
    assert msgs0[-1]["content"].startswith("## 本章正文\n" + draft)
    assert sess.current_chapter == 2                     # 章归属已登记（重入可截断）


def test_orchestrator_holds_per_run_volume_session_cache(tmp_path):
    """orchestrator 接线：volume_sessions 缓存挂实例、flag 从 cfg 读取（生命周期）"""
    from app.core.orchestrator import Orchestrator
    proj = _make_proj(tmp_path)
    orch = Orchestrator(proj, {"writing": {"volume_session": True}})
    assert isinstance(orch.volume_sessions, dict) and orch.volume_sessions == {}
    assert orch.cfg.get("writing", {}).get("volume_session") is True


# ---------------- runner（直接 python 运行同 pytest 语义） ----------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------- Part C：接力压缩接线（writing.compaction，T6/T2 地基） ----------------

def _comp_cfg(threshold=10 ** 9, on=True):
    w = {"chapter_session": True, "volume_session": True, "chapter_word_target": 60}
    if on:
        w.update(compaction=True, compaction_token_threshold=threshold)
    return {"writing": w, "gates": {"review_enabled": False}}


def _handoff_json(proj, vol=1):
    return os.path.join(proj, "追踪", "交接块_卷%d.json" % vol)


def test_compaction_flag_off_never_reached(tmp_path, monkeypatch):
    """字节纪律：旗标关闭时 _compaction_step 绝不触达，也不产出任何压缩文件"""
    from app.core import stages as sg
    monkeypatch.setattr(sg, "_compaction_step",
                        lambda *a, **k: pytest.fail("writing.compaction 关闭不得触达压缩"))
    proj = _make_proj(tmp_path)
    ctx, _rec = _run_microcycle(proj, _comp_cfg(on=False), CycleClient(), 1)
    assert ctx.volume_sessions[1].gen == 0
    assert not os.path.isdir(os.path.join(proj, "会话")) or \
        not [f for f in os.listdir(os.path.join(proj, "会话")) if "_c" in f]
    assert not os.path.exists(_handoff_json(proj))


def test_empty_preface_is_byte_identical():
    """preface 缺省/全空白 → 开幕轮与压缩改造前逐字节一致（T6 字节不变锁）；
    给了块则插在开幕声明与章头之间（卷终状态在前、本章上下文在后）。"""
    s = VolumeSession(FakeClient(["x"]), SYS, proj="")
    legacy = s._opening_text("章头", "首轮", 3)
    assert s._opening_text("章头", "首轮", 3, "") == legacy
    assert s._opening_text("章头", "首轮", 3, "  \n ") == legacy
    assert s.open_chapter("章头", "首轮", chapter_num=3) == legacy
    mark = opening_marker(3)
    assert s._opening_text("章头", "首轮", 3, "【卷 1 终交接块】") == \
        "\n\n".join([mark, "【卷 1 终交接块】", "章头", "首轮"])


def test_messages_path_generation_names(tmp_path):
    """gen=0 沿用改造前文件名；gen>0 另起 卷V_cK（旧栈留盘作证据）"""
    assert volume_messages_path(str(tmp_path), 1) == volume_messages_path(str(tmp_path), 1, 0)
    assert volume_messages_path(str(tmp_path), 1, 0).endswith(os.path.join("会话", "卷1_messages.jsonl"))
    assert volume_messages_path(str(tmp_path), 2, 3).endswith(os.path.join("会话", "卷2_c3_messages.jsonl"))


def _always_fire(monkeypatch, at=(2,)):
    """把触发器换成"到指定章就点火"，压缩本体仍走真实装配（只放宽 shrink 门槛）"""
    from app.core import history_compaction as hc

    def fake(proj, num, *, cfg=None, manual=False, input_tokens=-1, volume=0):
        if num in at:
            return hc.Trigger("input_threshold", "测试点火：第%d章" % num)
        return hc.Trigger("", "未到点火章")
    monkeypatch.setattr(hc, "should_compact", fake)
    monkeypatch.setattr(hc, "_shrink_ok", lambda block, replaced: True)
    return hc


def test_compaction_resets_stack_and_seeds_opening_turn(tmp_path, monkeypatch):
    """点火章：装配交接块 → 另起一代栈（system 逐字节沿用）→ 块进本章开幕轮"""
    from app.core import stages as sg
    hc = _always_fire(monkeypatch, at=(2,))
    proj = _make_proj(tmp_path)
    cfg = _comp_cfg()
    client = CycleClient()
    ctx1, _ = _run_microcycle(proj, cfg, client, 1, CycleCtx(proj, cfg, client))
    old = ctx1.volume_sessions[1]
    ctx2, _ = _run_microcycle(proj, cfg, client, 2, ctx1)
    new = ctx2.volume_sessions[1]

    assert new is not old and new.gen == 1                 # 另起一代
    assert new.system_text == old.system_text              # 新前缀的共享段逐字节沿用
    prose_turns = [m for m, ph in client.turn_calls if ph == "prose"]
    assert "【卷 1 终交接块" in prose_turns[-1][-1]["content"]     # 块进了第 2 章开幕轮
    assert os.path.exists(volume_messages_path(proj, 1))           # 旧栈不删：压缩前证据
    assert os.path.exists(volume_messages_path(proj, 1, 1))        # 新栈落盘
    d = json.load(open(_handoff_json(proj), encoding="utf-8"))
    assert d["kind"] == "qianbi-volume-handoff" and d["to_chapter"] == 1
    assert any("接力压缩" in m for _lv, m in ctx2.logs)
    assert sg._live_stack_gen(proj, 1) == 1


def test_preface_given_once_then_rides_the_cache(tmp_path, monkeypatch):
    """交接块只在新栈首个开幕轮给一次；后续章不再重发（此后它随历史永久命中）"""
    _always_fire(monkeypatch, at=(2,))
    proj = _make_proj(tmp_path)
    cfg = _comp_cfg()
    client = CycleClient()
    ctx, _ = _run_microcycle(proj, cfg, client, 1, CycleCtx(proj, cfg, client))
    ctx, _ = _run_microcycle(proj, cfg, client, 2, ctx)
    ctx, _ = _run_microcycle(proj, cfg, client, 3, ctx)
    prose_turns = [m[-1]["content"] for m, ph in client.turn_calls if ph == "prose"]
    assert prose_turns[1].count("终交接块") == 1
    assert "终交接块" not in prose_turns[2]
    assert ctx.volume_sessions[1].gen == 1                 # 第 3 章没有再重置


def test_compaction_is_idempotent_on_rerun(tmp_path, monkeypatch):
    """同一章重入（崩溃续跑）不得二次压缩：交接块已覆盖到 num-1 即跳过"""
    hc = _always_fire(monkeypatch, at=(2, 3, 4, 5))
    proj = _make_proj(tmp_path)
    cfg = _comp_cfg()
    client = CycleClient()
    ctx, _ = _run_microcycle(proj, cfg, client, 1, CycleCtx(proj, cfg, client))
    ctx, _ = _run_microcycle(proj, cfg, client, 2, ctx)
    gen_after_2 = ctx.volume_sessions[1].gen
    covered = json.load(open(_handoff_json(proj), encoding="utf-8"))["to_chapter"]
    # 第 2 章重跑（断点续跑回到同一章）：covered == num-1 → 守卫拦住二次压缩
    assert covered == 1
    trig = hc.should_compact(proj, 2, cfg=cfg)
    from app.core import stages as sg
    ctx.volume_sessions[1]._handoff = ""
    sess, preface = sg._compaction_step(ctx, proj, 2, ctx.volume_sessions[1])
    assert preface == "" and sess.gen == gen_after_2


def test_compaction_fails_open_when_refused(tmp_path, monkeypatch):
    """保险丝拒绝（如 shrink 不显著）：沿用当前会话、不重置、不注入任何东西"""
    from app.core import history_compaction as hc
    _always_fire(monkeypatch, at=(2,))
    monkeypatch.setattr(hc, "opening_block",
                        lambda proj, num, *, cfg=None, volume=0, replaced_hint=0:
                        hc.OpeningBlock(reason="保险丝①拒绝：块未显著更小"))
    proj = _make_proj(tmp_path)
    cfg = _comp_cfg()
    client = CycleClient()
    ctx, _ = _run_microcycle(proj, cfg, client, 1, CycleCtx(proj, cfg, client))
    before = ctx.volume_sessions[1]
    ctx, _ = _run_microcycle(proj, cfg, client, 2, ctx)
    assert ctx.volume_sessions[1] is before and before.gen == 0
    assert not os.path.exists(_handoff_json(proj))
    assert "终交接块" not in [m[-1]["content"] for m, ph in client.turn_calls if ph == "prose"][-1]
    assert any("fail-open" in m for _lv, m in ctx.logs)
