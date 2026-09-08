# -*- coding: utf-8 -*-
"""1:1 复现 V6 冒烟路径：真 cmd_run（mock LLM）后卷栈必须落盘

2026-09-09 冒烟异常：v_smoke3 跑完 3 章（exit 0）但无 会话/卷N_messages.jsonl。
本测试走 cost_bench.cmd_run 的真实代码路径（仅 mock LLMClient 三个入口），
若复现则可就地调试；若通过则冒烟异常为环境性。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))

import pytest


@pytest.fixture()
def mock_llm(monkeypatch):
    from app.llm.client import LLMClient
    monkeypatch.setattr(LLMClient, "chat",
                        lambda self, *a, **k: "无问题。", raising=True)
    monkeypatch.setattr(LLMClient, "chat_stream",
                        lambda self, *a, **k: "无问题。", raising=True)
    monkeypatch.setattr(LLMClient, "chat_turn",
                        lambda self, messages, **k: "无问题。", raising=True)


def test_cmd_run_smoke_persists_volume_stack(mock_llm, tmp_path):
    import scripts.cost_bench as cb
    from app.core.volume_session import volume_messages_path
    variant = "v_repro"
    cb.cmd_run(variant=variant, chapters=1, preset_params=None,
               writing={"volume_session": True,
                        "s4_static_freeze": True,
                        "tracking_delta": True,
                        "review_in_system": True,
                        "chapter_word_target": 60},
               fast_path=False, user_id="qianbi-repro",
               flash_conn="bailian-flash")
    proj = os.path.join(cb.BENCH, variant, "bench", cb.BOOK)
    assert os.path.exists(volume_messages_path(proj, 1)), \
        "cmd_run 后卷栈必须落盘——冒烟缺失的正是这一步"
