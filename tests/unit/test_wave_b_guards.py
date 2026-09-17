# -*- coding: utf-8 -*-
"""Wave B 前置守卫：H-12 自然语言兜底链双死修复 + H-5 伪「作者已放行」封死。

H-12（评审实测双死）：
- `bridge._ui_tool_dispatch` 裸用未导入的全局 agent_tools ⇒ 首次派发即 NameError；
- `_parse_instruction_llm_safe` 取 Bridge 上永不存在的 self.router ⇒ LLM 兜底恒死。
H-5：gate_preset=off（出厂默认）+ 人工审校 ⇒ ctx.gate("G8") 自动放行返回空串
⇒ 首轮落伪「作者已放行」、六维零执行——组合非法必须拒绝并转人工。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def bridge():
    from app.ui.bridge import Bridge
    return Bridge()


def test_ui_tool_dispatch_no_nameerror(bridge):
    """H-12②：派发面不得再裸用未导入的 agent_tools（旧代码此处必 NameError）。"""
    try:
        bridge._ui_tool_dispatch("cw_deslop")
    except NameError as e:
        pytest.fail(f"_ui_tool_dispatch 仍裸用未导入全局（H-12 复发）：{e}")
    except Exception:
        pass   # 无项目/非共写档的业务提示不算失败——NameError 消失即修复


def test_llm_fallback_router_alive(bridge):
    """H-12①：LLM 兜底解析必须拿得到 router（旧代码 Bridge 上永不存在的
    self.router 让兜底恒死）。调用后 router 必须已被懒建。"""
    bridge.proj = ""
    out = bridge._parse_instruction_llm_safe("把下一章字数改到两千五")
    assert getattr(bridge, "router", None) is not None, (
        "调用后 router 仍未建立——自然语言兜底 LLM 解析仍是死链（H-12）")
    assert out is None or isinstance(out, tuple)


def test_manual_review_rejects_gate_off_combo(tmp_path, monkeypatch, caplog):
    """H-5：门预置不含 G8 + 人工审校 ⇒ 明确拒绝转人工，不落「作者已放行」。"""
    from app.core import stages

    class Ctx:
        proj = str(tmp_path / "book")
        cfg = {"gates": {}, "writing": {"chapter_word_target": 200}}

        def log(self, *a, **k):
            pass

        def gate(self, *a, **k):
            return ""   # gate_preset=off 时门被自动放行返回空串（伪放行入口）

        def gate_enabled(self, key):
            return key != "G8"   # 出厂预置不含 G8 的形态

    ctx = Ctx()
    os.makedirs(ctx.proj, exist_ok=True)
    monkeypatch.setattr(stages.st, "mark_chapter_need_human",
                        lambda p, s, n: None)
    monkeypatch.setattr(stages.st, "load_state", lambda p: {})
    blocking, advisory, verdict, prose = stages._author_review_entry(
        ctx, 3, "正文" * 100, gates_cfg={})
    assert verdict != "AUTHOR_PASS", "伪「作者已放行」仍然产生（H-5 未封死）"
    assert verdict == "" and not blocking


def test_manual_review_works_when_gate_on(tmp_path, monkeypatch):
    """对照：G8 接线时人工审校循环照常（首轮空串=作者放行）。"""
    from app.core import stages

    class Ctx:
        proj = str(tmp_path / "book2")
        cfg = {"gates": {}, "writing": {"chapter_word_target": 200}}
        gate_calls = []

        def log(self, *a, **k):
            pass

        def gate(self, key, summary, chapter=0):
            self.gate_calls.append(key)
            return ""   # 作者留空 = 放行

        def gate_enabled(self, key):
            return True

    ctx = Ctx()
    os.makedirs(ctx.proj, exist_ok=True)
    monkeypatch.setattr(stages.st, "save_review_findings", lambda *a, **k: None)
    monkeypatch.setattr(stages.st, "load_state", lambda p: {})
    monkeypatch.setattr(stages.gates, "word_count_precheck", lambda *a, **k: ([], [], ""))
    blocking, advisory, verdict, prose = stages._author_review_entry(
        ctx, 3, "正文" * 100, gates_cfg={})
    assert verdict == "AUTHOR_PASS" and ctx.gate_calls == ["G8"]
