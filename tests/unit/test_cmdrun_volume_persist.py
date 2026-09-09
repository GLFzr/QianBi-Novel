# -*- coding: utf-8 -*-
"""1:1 复现 V6 冒烟路径：真 cmd_run（mock LLM）后卷栈必须落盘

2026-09-09 冒烟异常：v_smoke3 跑完 3 章（exit 0）但无 会话/卷N_messages.jsonl。
本测试走 cost_bench.cmd_run 的真实代码路径（仅 mock LLMClient 三个入口），
若复现则可就地调试；若通过则冒烟异常为环境性。

⚠️ 本测试必须**自带夹具**，不能依赖本机才有的东西——原版本在两处会只在开发机上绿：
  1. `cmd_run` 缺省种子取模块级 `BASE_DIR`（＝`tests_output/bench/bench_base`，由
     `--prepare` 生成）。`tests_output/` 在 .gitignore 里 ⇒ 干净检出上必然
     `AssertionError: 先跑 --prepare`（2026-09-08 起 GitHub Actions 的 Tests 三连红就是它）。
  2. `_load_key` 走 Windows 凭据管理器 + 真机 config.json，CI 上没有。
  ⇒ 种子工程在 tmp 里造，凭据用替身；顺手存回被 cmd_run 改写的 USERPROFILE/HOME
    （它把 fake home 写进进程环境，不还就会污染同会话后面的测试）。
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))

import pytest

from app import project as pj

FAKE_CONN = {"key": "sk-fake", "base": "http://fake.invalid", "model": "fake-model"}


@pytest.fixture()
def mock_llm(monkeypatch):
    from app.llm.client import LLMClient
    monkeypatch.setattr(LLMClient, "chat",
                        lambda self, *a, **k: "无问题。", raising=True)
    monkeypatch.setattr(LLMClient, "chat_stream",
                        lambda self, *a, **k: "无问题。", raising=True)
    monkeypatch.setattr(LLMClient, "chat_turn",
                        lambda self, messages, **k: "无问题。", raising=True)


def _make_seed(base: str) -> None:
    """造 `--prepare` 产出的最小形状：设定/大纲(含细纲)/正文/追踪 + state"""
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    pj.ensure_tracking_files(base)
    pj.write_file(os.path.join(base, "设定", "选题信息.md"), "# 选题\n都市悬疑（主）\n")
    pj.write_file(os.path.join(base, "设定", "题材定位.md"),
                  "## 主要角色表\n- 陈默：凡人\n")
    pj.write_file(os.path.join(base, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：旧物（3万字，6章）\n")
    pj.write_file(pj.get_outline_path(base, 1),
                  "### 第 1 章：单号\n- 核心事件：拾到旧物\n- 字数目标：60\n")


@pytest.fixture()
def bench_home(tmp_path, monkeypatch):
    """BENCH / BASE_DIR 指到 tmp，凭据走替身，并把 cmd_run 改掉的环境变量还回去"""
    import scripts.cost_bench as cb
    bench = str(tmp_path / "bench")
    seed = os.path.join(bench, "bench_base")
    os.makedirs(bench, exist_ok=True)
    _make_seed(seed)
    monkeypatch.setattr(cb, "BENCH", bench, raising=True)
    monkeypatch.setattr(cb, "BASE_DIR", seed, raising=True)
    monkeypatch.setattr(cb, "_load_key", lambda prefer_id="", pro_conn="": (dict(FAKE_CONN), None),
                        raising=True)
    saved = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    yield bench
    for k, v in saved.items():          # cmd_run 把 fake home 写进了进程环境
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(bench, ignore_errors=True)


def test_cmd_run_smoke_persists_volume_stack(mock_llm, bench_home):
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
               flash_conn="whatever-ignored-by-stub")
    proj = os.path.join(cb.BENCH, variant, "bench", cb.BOOK)
    assert os.path.exists(volume_messages_path(proj, 1)), \
        "cmd_run 后卷栈必须落盘——冒烟缺失的正是这一步"


def test_cmd_run_fixture_covers_ci_gaps(bench_home):
    """夹具要挡住 CI 上原先炸掉的两件事：没有 --prepare 产物、没有凭据库"""
    import scripts.cost_bench as cb
    assert os.path.isdir(os.path.join(cb.BASE_DIR, "大纲")), "种子必须自带，不能靠本机 bench_base"
    assert cb._load_key(prefer_id="anything") == (dict(FAKE_CONN), None), "凭据必须走替身"
