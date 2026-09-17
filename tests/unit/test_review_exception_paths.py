# -*- coding: utf-8 -*-
"""A-7：审校异常不许变假 PASS。

v4 评审实测：stages._chapter_review 的 `except Exception` 吞掉停止/网络/解析
异常后返回空票 → 上游记「审校通过」并定稿落库（C-2）。本组用例钉死：
① 抛 PipelineStopped → 原样上抛（停止优先）；
② 抛 RuntimeError（网络/解析类）→ 本章 mark_chapter_need_human（转人工），
   不返回"通过"口径，且不落空票定稿。
变异验证：把 `except PipelineStopped: raise` 删掉 ⇒ ①红；把转人工分支改回
`return [], [], ""`（无标记）⇒ ②红。
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import stages  # noqa: E402


class _Ctx:
    proj = ""
    # 字数目标与细纲一致（200）：否则「偏差过大按配置执行」会打回 3000、
    # 字数预检拦在审校之前，用例就够不到 review_with_votes
    cfg = {"gates": {}, "writing": {"chapter_word_target": 200}}

    def log(self, *a, **k):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import project
    proj = str(tmp_path / "book")
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
    # 细纲登记小目标：让字数预检放行（否则走不到审校调用）
    project.write_file(project.get_outline_path(proj, 3), "字数目标：200\n核心事件：测试。\n")
    marked = {}
    monkeypatch.setattr(stages.st, "mark_chapter_need_human",
                        lambda proj, state, num: marked.setdefault("num", num))
    monkeypatch.setattr(stages.st, "load_state", lambda proj: {})
    ctx = _Ctx()
    ctx.proj = proj
    return proj, ctx, marked


def test_pipeline_stopped_reraises(env, monkeypatch):
    proj, ctx, marked = env
    monkeypatch.setattr(stages, "review_with_votes",
                        lambda *a, **k: (_ for _ in ()).throw(stages.PipelineStopped()))
    with pytest.raises(stages.PipelineStopped):
        stages._chapter_review(ctx, 3, "正文" * 500)
    assert "num" not in marked, "停止被当成审校异常转了人工——语义错位"


def test_review_exception_goes_unreviewed_not_pass(env, monkeypatch):
    proj, ctx, marked = env
    monkeypatch.setattr(stages, "review_with_votes",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("解析炸了")))
    blocking, advisory, verdict = stages._chapter_review(ctx, 3, "正文" * 500)
    assert marked.get("num") == 3, "审校异常未转人工（假 PASS：空票会被当通过定稿）"
    assert verdict != "PASS" and not blocking
