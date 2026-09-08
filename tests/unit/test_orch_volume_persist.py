# -*- coding: utf-8 -*-
"""真 Orchestrator 集成：volume_session 开启时微循环必须把卷栈落盘

V6 冒烟（2026-09-09）异常：同配置下 CycleCtx 假件路径一切正常，真机跑却没有
会话/卷1_messages.jsonl——本测试用真 Orchestrator（monkeypatch LLM 输出）复现或排除。
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_orch_vol_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from app import project as pj

CANNED_REVIEW = """```json
{"dimensions": [], "blocking": [], "advisory": [], "verdict": "PASS"}
```"""


@pytest.fixture()
def orch_env(tmp_path, monkeypatch):
    from app.core.orchestrator import Orchestrator
    from app.llm.client import LLMClient

    home = str(tmp_path / "home")
    proj = os.path.join(home, "测试书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"),
                  "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(os.path.join(proj, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：边陲（3万字，8章）\n")
    pj.write_file(pj.get_outline_path(proj, 1),
                  "### 第 1 章：开端\n- 核心事件：少年拾到玉简\n- 字数目标：60\n")
    monkeypatch.setattr(LLMClient, "chat", lambda self, *a, **k: "无问题。", raising=True)
    monkeypatch.setattr(LLMClient, "chat_stream",
                        lambda self, *a, **k: iter([]) if False else "无问题。",
                        raising=True)
    monkeypatch.setattr(LLMClient, "chat_turn",
                        lambda self, messages, **k: "无问题。", raising=True)
    cfg = {
        "connections": [{"id": "t1", "name": "fake", "provider": "custom",
                         "base_url": "http://fake.invalid", "api_key": "sk-t",
                         "model": "fake-model", "max_tokens": 1024}],
        "slots": {"writing": "t1", "helper": "t1", "review": "t1"},
        "writing": {"volume_session": True, "chapter_word_target": 60},
        "gates": {"review_enabled": True, "review_votes": 1,
                  "deslop_max_rounds": 1, "strategy": "mark_continue"},
    }
    orch = Orchestrator(proj, cfg)
    return orch, proj


def test_orchestrator_microcycle_persists_volume_stack(orch_env):
    from app.core import stages
    from app.core.volume_session import volume_messages_path
    orch, proj = orch_env
    record = stages.chapter_microcycle(orch, 1)
    assert record["num"] == 1
    assert isinstance(getattr(orch, "volume_sessions", None), dict), \
        "orchestrator 必须持有 volume_sessions 缓存表"
    assert orch.volume_sessions, "卷会话实例应被创建并挂到缓存表"
    assert os.path.exists(volume_messages_path(proj, 1)), \
        "微循环收尾必须把卷栈落盘（V6 冒烟缺失的就是这一步）"
