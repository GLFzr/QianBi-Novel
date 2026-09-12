# -*- coding: utf-8 -*-
"""S2 清算入会话（canon_audit.in_session 旗标）单测

- 旗标开 + 会话可用 + 客户端同源：预扫走 session.ask 追加轮，prompt 剥 project_header
  前缀、带 SCOPE_LINE；JSON 解析成功 → 跳过独立单发循环、cascade.in_session=True
- 解析失败/退化：回退独立单发，且废轮被 rollback（会话栈回到调用前）
- 客户端异构（N2）：不走会话，直接独立单发
- 旗标关（默认）：S2 跳过；S1b（v16 5.3）同域重试轮骑会话+废轮回滚，
  cascade.in_session 仍为 False（它只标 S2 通道）
无真实 API：monkeypatch canon_audit._client_for 注入假客户端，会话用假替身。
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_audit_session_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import app.core.canon_audit as ca
from app.core.canon_audit import audit_chapter

VALID = json.dumps({
    "violations": [{"quote": "他推开了西角的铁门", "why": "底册无此门",
                    "canon_ref": "底册无此条", "severity": "硬伤"}],
    "adoptions": [], "ledger_updates": {}, "beat_check": {},
}, ensure_ascii=False)
DEGENERATE = json.dumps({
    "violations": [{"quote": "a", "why": "同一句", "severity": "软伤"},
                   {"quote": "b", "why": "同一句", "severity": "软伤"},
                   {"quote": "c", "why": "同一句", "severity": "软伤"}],
    "adoptions": [], "ledger_updates": {},
}, ensure_ascii=False)

DS = ("https://api.deepseek.com", "deepseek-v4-flash")


class FakeClient:
    def __init__(self, base_url=DS[0], model=DS[1], output=VALID):
        self.base_url, self.model, self.output = base_url, model, output
        self.calls = []

    def chat_stream(self, prompt, temperature=None, phase="", on_chunk=None, **kw):
        self.calls.append(prompt)
        if on_chunk:
            on_chunk(self.output)
        return self.output


class FakeSession:
    def __init__(self, client, enabled=True, output=VALID):
        self._client = client
        self.enabled = enabled
        self.output = output
        self.turns = 0
        self.asked = []
        self.rolled_back = 0

    def ask(self, user_text, *, client=None, phase="", on_chunk=None, **kw):
        self.asked.append((user_text, phase))
        if on_chunk:
            on_chunk(self.output)
        self.turns += 1
        return self.output

    def rollback_to(self, n):
        self.rolled_back += 1
        self.turns = n

    def turn_count(self):
        return self.turns


def _proj(tmp):
    os.makedirs(os.path.join(tmp, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "设定"), exist_ok=True)
    return tmp


def _flags_via_preset(proj, in_session):
    """用真实 presets 管线注入 canon_audit 旗标（state 必须写在 proj——audit 读的就是它）"""
    from app import presets as gp
    from app.core import state as st
    pid = "t_audit_s2"
    gp.save_preset({"id": pid, "name": "t", "version": 2,
                    "stage_params": ({"canon_audit": {"in_session": True}} if in_session
                                     else {"canon_audit": {"thinking": "enabled",
                                                           "reasoning_effort": "low"}})})
    st.save_state(proj, {"genre_preset": pid})


def test_in_session_used_and_header_stripped(tmp_path, monkeypatch):
    proj = _proj(str(tmp_path))
    _flags_via_preset(proj, True)
    solo = FakeClient()                       # _client_for 的产物 = 栈基座同源
    s = FakeSession(solo, output=VALID)
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=s)
    assert len(s.asked) == 1 and solo.calls == []       # 走了会话，没走单发
    body, phase = s.asked[0]
    assert phase == "canon_audit"
    assert body.startswith("（作用域")                   # SCOPE_LINE 打头
    assert "你是网文世界观的合规审校" in body            # 审计指令体在
    assert "【项目设定基准" not in body                  # project_header 已剥
    assert "## 核心设定节选" not in body                 # V1-④：header 正文段也剥净
    assert "题材预设" not in body                        # （旧 split 只剥 36 字标题行，
    #   余下 ~3.0k 字符每章重复计价——浅标记断言让该 bug 潜伏了一轮，此两条钉死）
    assert "他推开了西角的铁门，门后有风" not in body      # S2：正文不再重复注入
    assert "最近一条完整的章正文消息" in body              # 已换历史引用
    assert rep["cascade"]["in_session"] is True
    assert rep["violations"][0]["severity"] == "硬伤"
    assert rep["failed"] is False


def test_header_stripped_even_with_preamble(tmp_path, monkeypatch):
    """W-2 加固：header 不在开头也必须剥——旧写法要求 startswith，版式一动就静默失配

    t3b 卷2 实测：失配时每章多骑 ~6.3k 字（其中 2,521 han 字与 system 逐字节相同），
    24 章就是 15 万字的历史噪声，且这部分**带复利**（入栈后每章都被重读）。"""
    proj = _proj(str(tmp_path))
    _flags_via_preset(proj, True)
    solo = FakeClient()
    s = FakeSession(solo, output=VALID)
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    monkeypatch.setattr(ca, "AUDIT_PROMPT", "【清算 v2 前导行】\n\n" + ca.AUDIT_PROMPT)
    audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                  router=None, session=s)
    body, _phase = s.asked[0]
    assert "【清算 v2 前导行】" in body                    # 前导行照留
    assert "【项目设定基准" not in body and "## 核心设定节选" not in body
    assert "你是网文世界观的合规审校" in body              # 指令体没被误剥
    assert "他推开了西角的铁门，门后有风" not in body


def test_degenerate_falls_back_and_rolls_back(tmp_path, monkeypatch):
    proj = _proj(str(tmp_path))
    _flags_via_preset(proj, True)
    solo = FakeClient(output=VALID)
    s = FakeSession(solo, output=DEGENERATE)
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=s)
    assert s.rolled_back >= 1                            # 废轮回滚
    assert rep["cascade"]["in_session"] is False        # 最终结果是单发产物
    assert rep["violations"][0]["severity"] == "硬伤"


def test_cross_provider_client_skips_session(tmp_path, monkeypatch):
    proj = _proj(str(tmp_path))
    _flags_via_preset(proj, True)
    solo = FakeClient()                                  # 同源 DeepSeek（单发路径）
    sess_client = FakeClient(base_url="https://dashscope.aliyuncs.com",
                             model="qwen-flash", output=VALID)
    s = FakeSession(sess_client, output=VALID)
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=s)
    assert s.asked == []                                 # N2：没进会话
    assert solo.calls                                    # 走了单发
    assert rep["cascade"]["in_session"] is False


def test_flag_off_retry_rides_session(tmp_path, monkeypatch):
    """旗标关（S2 跳过）：预扫不作为 S2 会话轮；但 S1b（v16 5.3）——同域重试轮
    骑会话（cascade.in_session 仍为 False，它只标 S2 通道）。"""
    proj = _proj(str(tmp_path))
    _flags_via_preset(proj, False)
    solo = FakeClient(output=VALID)
    s = FakeSession(solo, output=VALID)
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=s)
    assert len(s.asked) == 1                    # 重试轮骑会话
    assert solo.calls == []                     # 没有独立单发
    assert rep["cascade"]["in_session"] is False
    assert rep["violations"]
