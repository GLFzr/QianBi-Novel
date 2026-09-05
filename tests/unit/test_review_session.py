# -*- coding: utf-8 -*-
"""章会话在 review_with_votes 中的集成行为（v0.19）

覆盖点：
- 会话生效时：首票经 ask 固化（历史含正文），副本票以快照并行、不进正史；
- 会话关闭/客户端不支持 chat_turn 时：回退单轮 chat_stream，行为与旧版一致；
- turn_count==0（断点续跑）时先播种正文再投票。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import project
from app.core.chapter_session import ChapterSession
from app.core import stages


class _FakeClient:
    """同时支持单轮与多轮的假客户端（脚本化回复）"""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.stream_calls = 0
        self.turn_calls = 0
        self.turn_messages = []

    def chat_stream(self, prompt, on_chunk=None, temperature=None, **kw):
        self.stream_calls += 1
        return self.scripts.pop(0)

    def chat_turn(self, messages, on_chunk=None, temperature=None, **kw):
        self.turn_calls += 1
        self.turn_messages.append(messages)
        return self.scripts.pop(0)


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _FakeCtx:
    def __init__(self, proj, client, votes=3):
        self.proj = proj
        self.cfg = {"gates": {"review_votes": votes, "review_temperature": 0.2},
                    "writing": {"regex_semantics": "logic", "chapter_session": True}}
        self.router = _FakeRouter(client)
        self.last_prompt = ""
        self.review_raw = None
        self.review_v2 = None
        self.stopped = False
        self.logs = []

    def stream_chunk(self, t):
        pass

    def stream_reasoning(self, t):
        pass

    def stream_stage(self, label):
        pass

    def log(self, level, msg):
        self.logs.append((level, msg))


def _report(fail_line):
    return (f"===A_GOLDEN_OPEN=== pass 合标\n{fail_line}\n"
            f"===C_FINGER=== pass\n===E_CHARACTER=== pass\n===F_HOOK=== pass\n"
            f"===WORST_QUOTES===\n- [D] \"他忍了忍，决定改日再说\"\n===TOTAL===\n"
            f"- fail 项数：1\n- marginal 项数：0\n- 总评：PASS_WITH_NOTES\n===END===\n"
            f"===VERDICT===\nPASS_WITH_NOTES\n===END===")


def _make_proj(tmp_path):
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, "大纲", "细纲_第002章.md"), "核心事件：反击")
    return proj


_PROSE = "他忍了忍，决定改日再说。" * 50
_FAIL_LINE = '===D_PLOT=== fail 未演【原文引证："他忍了忍，决定改日再说"】 → root: ROOT_PROSE'


def test_session_votes_first_turn_persists_replicas_not(tmp_path):
    proj = _make_proj(tmp_path)
    client = _FakeClient([_report(_FAIL_LINE)] * 3)
    ctx = _FakeCtx(proj, client, votes=3)
    session = ChapterSession(client, system_text="SYSTEM_BLOCK")
    merged = stages.review_with_votes(ctx, 2, _PROSE, votes=3, session=session)
    assert client.turn_calls == 3          # 首票 ask + 两张副本票全部经 chat_turn
    assert client.stream_calls == 0
    # 副本票的消息栈=首票请求快照+[user]：不含首票回复（不含正史第 4 条）
    solo_msgs, *replica_msgs = client.turn_messages
    assert len(solo_msgs) == 2             # [system, user]
    for m in replica_msgs:
        assert len(m) == 2 and m[0]["content"] == "SYSTEM_BLOCK"
    assert session.turn_count() == 1       # 只有首票轮固化
    roles = [m["role"] for m in session.snapshot()]
    assert roles == ["system", "user", "assistant"]
    assert "SYSTEM_BLOCK" in session.snapshot()[0]["content"]
    # 首票 user 轮不含正文全文（正文经 restart 种子进 user 轮首段）
    user_content = session.snapshot()[1]["content"]
    assert "## 本章正文" in user_content
    assert merged["summary"]["fail"] == 1


def test_session_disabled_falls_back_to_stream(tmp_path):
    proj = _make_proj(tmp_path)
    client = _FakeClient([_report(_FAIL_LINE)] * 3)
    ctx = _FakeCtx(proj, client, votes=3)
    session = ChapterSession(client, system_text="S", enabled=False)
    merged = stages.review_with_votes(ctx, 2, _PROSE, votes=3, session=session)
    assert client.stream_calls == 3        # 全部走旧单轮流式
    assert client.turn_calls == 0
    assert merged["summary"]["fail"] == 1


def test_client_without_chat_turn_falls_back(tmp_path):
    proj = _make_proj(tmp_path)
    class _LegacyClient(_FakeClient):
        chat_turn = None   # 旧客户端：不支持多轮（callable 检查为假）

    client = _LegacyClient([_report(_FAIL_LINE)] * 3)
    ctx = _FakeCtx(proj, client, votes=3)
    session = ChapterSession(client, system_text="S")
    assert session.enabled is False
    merged = stages.review_with_votes(ctx, 2, _PROSE, votes=3, session=session)
    assert client.stream_calls == 3
