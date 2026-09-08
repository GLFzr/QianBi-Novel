# -*- coding: utf-8 -*-
"""cost_bench 续写能力（T2 压缩 A/B 的地基）回归

T2 要求两臂从**同一个卷终态**出发续写第 21-26 章：
  --seed-home 把种子从 bench_base 换成既有变体的工程目录；
  --start 让微循环区间从第 N 章开始（start>1 必须配 seed-home，否则会静默跳章）；
  --outlines-only 先单独补齐 21-26 细纲，两臂再共读同一批细纲——
    否则先到的一臂现场生成细纲、后到的白捡，成本与细纲两侧都不可比。

另锁一条 2026-09-07 实测踩到的地基：卷会话恢复要求首条 system 与当前全书前缀**逐字节
一致**，而题材预设名就渲染在里面。续写时若按新变体名重铸标签（"实验 <变体>"），旧栈必被拒、
**静默退回空栈**——"从 20 章终态续写"的 T2 两臂会当场变成两次从零起跑，测不到长栈行为。
"""
import json
import os

import pytest

from scripts.cost_bench import (BOOK, SEED_STEPS, _parse_args, _seed_preset_name,
                                _seed_proj)


def _stack(proj, label, gen=1):
    """写一卷会话栈，首条 system 里带上「【题材预设：X】」"""
    sess = os.path.join(str(proj), "会话")
    os.makedirs(sess, exist_ok=True)
    system = ("【项目设定基准（全书共享）】\n\n## 题材预设\n【题材预设：%s】\n\n"
              "## 核心设定节选\n" % label)
    with open(os.path.join(sess, "卷%d_messages.jsonl" % gen), "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "system", "content": system}, ensure_ascii=False) + "\n")


@pytest.fixture()
def bench_dir(tmp_path, monkeypatch):
    """造一个假的 tests_output/bench/<变体>/bench/种子书/{正文,大纲}"""
    d = tmp_path / "bench"
    proj = d / "t1_long20" / "bench" / BOOK
    (proj / "正文").mkdir(parents=True)
    (proj / "大纲").mkdir()
    monkeypatch.setattr("scripts.cost_bench.BENCH", str(d))
    return str(d)


def test_seed_proj_resolves_variant_name(bench_dir):
    got = _seed_proj("t1_long20")
    assert got == os.path.join(bench_dir, "t1_long20", "bench", BOOK)


def test_seed_proj_accepts_explicit_directory(bench_dir):
    direct = os.path.join(bench_dir, "t1_long20", "bench", BOOK)
    assert _seed_proj(direct) == direct


def test_seed_proj_rejects_state_without_body(bench_dir):
    with pytest.raises(SystemExit):
        _seed_proj("nope_missing")


def test_parse_args_defaults_keep_legacy_behaviour():
    a = _parse_args(["--variant", "s1_volume", "--chapters", "6"])
    assert (a.start, a.seed_home, a.outlines_only) == (1, "", False)


def test_parse_args_reads_continuation_flags():
    a = _parse_args(["--variant", "t2b_compact", "--seed-home", "t1_long20",
                     "--start", "21", "--chapters", "26", "--outlines-only"])
    assert (a.start, a.seed_home, a.chapters, a.outlines_only) == (
        21, "t1_long20", 26, True)


def test_seed_label_is_read_from_the_stack(tmp_path):
    """权威标签在栈的 system 里，不在 state 的 genre_preset 名里（后者每 seed 一跳就被换掉）"""
    proj = tmp_path / "t2_outline" / "bench" / BOOK
    (proj / "正文").mkdir(parents=True)
    _stack(proj, "实验 t1_long20")
    assert _seed_preset_name(str(proj)) == "实验 t1_long20"


def test_seed_label_prefers_latest_volume(tmp_path):
    proj = tmp_path / "seed" / "bench" / BOOK
    (proj / "正文").mkdir(parents=True)
    _stack(proj, "实验 卷一旧名", gen=1)
    _stack(proj, "实验 卷二现名", gen=2)
    assert _seed_preset_name(str(proj)) == "实验 卷二现名"


def test_seed_label_empty_without_stack(tmp_path):
    """无栈（首次起跑）→ 空串，调用方回落到 "实验 <变体>"，不影响全新变体的可读性"""
    proj = tmp_path / "fresh" / "bench" / BOOK
    (proj / "正文").mkdir(parents=True)
    assert _seed_preset_name(str(proj)) == ""


def test_parse_args_seed_drafts_from_defaults_to_finalize():
    """缺省断点必须仍是 finalize——否则历史 --seed-drafts 跑批的语义会静默改变"""
    a = _parse_args(["--variant", "x", "--seed-drafts", "/tmp/d"])
    assert a.seed_drafts_from == "finalize"


def test_parse_args_seed_drafts_from_reads_step():
    a = _parse_args(["--variant", "t4a", "--seed-drafts", "/tmp/d", "--seed-drafts-from", "draft"])
    assert a.seed_drafts_from == "draft"


def test_seed_steps_match_pipeline_order():
    """断点步名两边漂移 = 雷稿静默跑错步（T4a/T4b 的地基）：与 stages._ORDER 必须逐项同序"""
    from app.core import stages as st_mod
    import inspect
    src = inspect.getsource(st_mod)
    recorded = [s for s in SEED_STEPS if s in src]
    assert len(recorded) == len(SEED_STEPS), "SEED_STEPS 里有 stages 不认的步名"
    order = src[src.index("_ORDER = ["):]
    for step in reversed(SEED_STEPS):          # 在源码切片里从后往前逐个出现即同序
        assert f'"{step}"' in order, "缺步名 %s" % step
        order = order[:order.index(f'"{step}"')]
