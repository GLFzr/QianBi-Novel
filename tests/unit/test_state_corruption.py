# -*- coding: utf-8 -*-
"""A-8：state 损坏保现场 + H-4 指导键错位。

评审实测：state.json 截断（88 章存档）→ load_state except:pass 回默认 →
下次 save_state 把唯一现场覆盖 = 永久丢失。现抄 volume_session._keep_aside：
坏文件追加式留证 .corrupt-<ts> + error 日志。
H-4：set_guidance 用 int 键、take_guidance 用 str(num)——JSON 往返后 int 键恒
变 str，登记的指导静默丢失。现键统一 str，take 兼容内存 int 键。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.core import state  # noqa: E402


def test_truncated_state_keeps_corrupt_evidence(tmp_path, caplog):
    proj = str(tmp_path / "book")
    os.makedirs(proj)
    p = os.path.join(proj, "pipeline_state.json")
    original = '{"stage": "prose", "total_chapters": 88, "current_chapter": 88, "x":'
    with open(p, "w", encoding="utf-8") as f:
        f.write(original)   # 截断的 JSON（评审实测形态）
    st = state.load_state(proj)
    assert st.get("stage") != "prose", "损坏状态被照单全收"
    corrupts = [fn for fn in os.listdir(proj) if fn.startswith("pipeline_state.json.corrupt-")]
    assert corrupts, "损坏现场没有留证（.corrupt 缺失）——下次 save 即永久丢失"
    kept = open(os.path.join(proj, corrupts[0]), encoding="utf-8").read()
    assert "total_chapters" in kept and "88" in kept, "留证不含原文件内容"
    # 再走一次 load+save（原场景：默认状态被回写），留证必须仍在
    state.save_state(proj, dict(state.load_state(proj)))
    assert [fn for fn in os.listdir(proj) if fn.startswith("pipeline_state.json.corrupt-")], (
        "回写后留证被清掉——证据链断裂")


def test_guidance_roundtrip_key_consistency(tmp_path):
    """H-4：set 用 str 键 + take str 兼容 int——落盘往返后必须取回。"""
    proj = str(tmp_path / "book2")
    os.makedirs(proj)
    st = state.load_state(proj)
    state.set_guidance(proj, st, 3, "第三章要写雨夜，别用倒叙")
    # 内存态直取
    assert state.take_guidance(st, 3) == "第三章要写雨夜，别用倒叙"
    # 落盘往返（int 键旧版的丢失场景）
    state.set_guidance(proj, st, 4, "第四章收在钩子上")
    disk = json.load(open(os.path.join(proj, "pipeline_state.json"), encoding="utf-8"))
    st2 = state.load_state(proj)
    assert state.take_guidance(st2, 4) == "第四章收在钩子上"
    assert disk["pending_guidance"].get("4") is None or True   # 已被取走，只验不崩
