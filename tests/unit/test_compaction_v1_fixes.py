# -*- coding: utf-8 -*-
"""V1-a/b 压缩组件修复回归（T 轮报告 §9-A 卷号错位 / §9-B 压缩比口径 / 陈旧块复用）

T2 实测事故的三个根源，各自钉死：
1. 写侧卷号：卷内装配的交接块必须落在 upto 的**真实卷**文件（旧代码被调用方
   传 `cur-1 or cur` 污染 → 卷 2 的块写成 交接块_卷1.json）；
2. 读侧复用：块只在其 to_chapter ≥ num-1（完整覆盖到本章前一章）时复用——
   陈旧块（T2 的 ch25 复用 ch21 块、丢 21-24 章记忆）必须落到现场重装配；
3. replaced 口径：被顶替量按调用方传入的会话栈实测（replaced_hint），
   单章正文口径只是无 hint 时的兜底。
全部 tmp_path 真实项目树，零 LLM、零网络（夹具风格对齐 test_history_compaction.py）。
"""
import json
import os

import pytest

from app import project as pj
from app.core import history_compaction as hc
from tests.unit.test_history_compaction import CFG_ON, _make_home

TWO_VOLUMES = ("## 卷级大纲\n\n### 第一卷：边陲（3万字，12章）\n\n"
               "### 第二卷：长夜（3万字，12章）\n")


@pytest.fixture(autouse=True)
def _isolate_real_usage(tmp_path, monkeypatch):
    from app import usage as usage_mod
    monkeypatch.setattr(usage_mod, "FILE", str(tmp_path / "_no_real_usage.jsonl"))


def _write_block(proj: str, volume: int, to_chapter: int, text="陈旧块正文"):
    """直接落一份指定 to_chapter 的交接块 json（模拟历史遗留产物）"""
    path = hc.handoff_json_path(proj, volume)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"kind": hc.ARTIFACT_KIND, "version": hc.ARTIFACT_VERSION,
                   "volume": volume, "from_chapter": 1, "to_chapter": to_chapter,
                   "trigger": "manual", "text": text, "tokens": 100,
                   "replaced_tokens": 900, "shrink_ratio": 0.111}, f, ensure_ascii=False)
    return path


def test_in_volume_assembly_lands_on_true_volume(tmp_path):
    """卷内装配（cur=2, upto=24）：块必须落 卷2 文件——旧代码落 卷1（§9-A 写侧）"""
    _home, proj = _make_home(tmp_path, chapters=24, volumes=TWO_VOLUMES)
    assert hc.resolve_volume(proj, 24) == 2
    ob = hc.opening_block(proj, 25, cfg=CFG_ON, volume=2)
    assert ob.contributed and ob.reason.startswith("assembled")
    assert os.path.exists(hc.handoff_json_path(proj, 2)), "块必须落在真实卷 2"
    assert not os.path.exists(hc.handoff_json_path(proj, 1)), "不许再污染卷 1 文件"


def test_stale_block_is_not_reused(tmp_path):
    """to_chapter < num-1 的陈旧块不许复用（§9-A 读侧）：必须现场重装配到 24"""
    _home, proj = _make_home(tmp_path, chapters=24, volumes=TWO_VOLUMES)
    _write_block(proj, 2, to_chapter=20, text="ch21 写的陈旧块")
    ob = hc.opening_block(proj, 25, cfg=CFG_ON, volume=2)
    assert ob.contributed and ob.reason.startswith("assembled"), \
        "陈旧块（覆盖到 20）必须触发重装配，而不是直接复用"
    assert "陈旧块正文" not in ob.text


def test_covering_block_is_reused(tmp_path):
    """to_chapter ≥ num-1 的覆盖块照常复用（幂等：不重复装配）"""
    _home, proj = _make_home(tmp_path, chapters=24, volumes=TWO_VOLUMES)
    _write_block(proj, 2, to_chapter=24, text="新鲜块正文")
    ob = hc.opening_block(proj, 25, cfg=CFG_ON, volume=2)
    assert ob.contributed and ob.reason == "handoff_卷2"
    assert "新鲜块正文" in ob.text


def test_volume_boundary_reads_previous_volume_block(tmp_path):
    """卷界（ch13 属卷 1 → num=13? 此处 ch24=卷2 末）：上一卷的覆盖块可复用"""
    _home, proj = _make_home(tmp_path, chapters=24, volumes=TWO_VOLUMES)
    _write_block(proj, 1, to_chapter=12, text="卷一终交接块")
    ob = hc.opening_block(proj, 13, cfg=CFG_ON, volume=1)
    assert ob.contributed and ob.reason == "handoff_卷1"
    assert "卷一终交接块" in ob.text


def test_replaced_hint_is_the_real_basis(tmp_path):
    """replaced_hint 生效：replaced_tokens/shrink_ratio 按会话栈实测计（§9-B）"""
    _home, proj = _make_home(tmp_path, chapters=4, volumes=TWO_VOLUMES)
    res = hc.build_handoff_block(proj, cfg=CFG_ON, upto=4, replaced_hint=280000)
    assert res.ok and res.replaced_tokens == 280000
    assert res.shrink_ratio == pytest.approx(res.tokens / 280000, abs=1e-4)
    assert res.shrink_ratio < 0.05   # 2k 块 vs 28 万 tok 历史 → 真实压缩比量级
    # 落盘 json 同口径（幂等复用时读回的 replaced_tokens 不再失真）
    d = hc.load_handoff(proj, hc.resolve_volume(proj, 4))
    assert int(d.get("replaced_tokens") or 0) == 280000


def test_replaced_fallback_without_hint(tmp_path):
    """无 hint 时退回单章正文口径（兜底路径不破坏）——小夹具里块/单章比超阈值，
    保险丝①按该口径 fail-open 拒绝（这正是它在失真尺子上的正确行为）"""
    _home, proj = _make_home(tmp_path, chapters=4, volumes=TWO_VOLUMES)
    res = hc.build_handoff_block(proj, cfg=CFG_ON, upto=4)
    assert res.ok is False and res.shrunk is False
    assert "保险丝①" in (res.reason or "")
    assert res.replaced_tokens == hc.han_tokens(hc.chapter_prose(proj, 1, 4))
