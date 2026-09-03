# -*- coding: utf-8 -*-
"""P0b：场景卡工艺路线接线正文 + 预设「作者按」近端注入"""
import os
import subprocess
import sys

from app import project
from app.presets import author_note
from app.prompts import scene_cards
from app.prompts.writing import PROSE_WRITING_PROMPT

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _subs_with_seed(seed):
    """子进程里取子卡顺序：进程哈希种子不同 → set() 顺序就不同（回归护栏）"""
    code = ("import sys; sys.path.insert(0, %r);"
            "from app.prompts.scene_cards import chapter_to_cards;"
            "print(chapter_to_cards('擂台比武里有疑点，也有对话')[1])" % _ROOT)
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=_ROOT)
    return out.stdout.strip()


def test_sub_card_order_is_deterministic_across_processes():
    a, b = _subs_with_seed(0), _subs_with_seed(7)
    assert a == b and "lowkey" in a, (a, b)


def test_craft_block_routes_and_stays_short():
    block = scene_cards.craft_block(3, 60, "擂台上三招交手，对手当场认输，围观者哗然")
    assert block.startswith("主卡·") and "本章演法" in block
    assert "回合制：目标→试探→交锋→代价→收束" in block or "铺垫压力≤爽点长度" in block
    assert block.count("\n") <= 12                       # 工艺路线不能变成第二份禁令
    assert "Chen Luo" not in block                        # 英文 example 不进注入块
    assert not any(l.startswith("#") for l in block.splitlines())   # 标题由模板给


def test_craft_block_axis_rotates_by_chapter():
    texts = {scene_cards.craft_block(n, 60, "擂台上三招交手") for n in (1, 2, 3)}
    assert len(texts) == 3                                # 同主卡也要给不同演法，防连章同型


def test_author_note_placeholders_exist_near_end():
    p = PROSE_WRITING_PROMPT
    assert "{craft_block}" in p and "{author_note}" in p
    assert p.index("20. **动静配比") < p.index("{craft_block}") < p.index("## 去 AI 味红线")
    assert p.index("{author_note}") > p.index("{tic_blacklist}")   # 作者按贴着输出格式（最末）


def test_author_note_reads_preset_field_and_defaults_empty(tmp_path, monkeypatch):
    """author_note 是预设字段：不填返回空串（装配层负责占位），且不进题材块"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    import json
    d = os.path.join(str(tmp_path), ".qianbi_novel", "presets")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "p0b.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "p0b", "name": "测试预设", "version": 2,
                   "author_note": "别让主角一个人想太多", "style_hint": "冷硬短句"}, f,
                  ensure_ascii=False)
    assert author_note("p0b") == "别让主角一个人想太多"
    assert author_note("") == ""
    from app.presets import genre_block
    assert "别让主角一个人想太多" not in genre_block("p0b")   # 只走近端口，不重复注入


def test_stages_helpers_have_placeholders(tmp_path):
    """装配层：无预设/无总章数也不能抛，且默认值可辨识"""
    from app.core import stages
    proj = project.create_project(str(tmp_path), "无预设书")
    assert stages._author_note(proj) == "（本章无作者按）"
    assert stages._total_chapters(proj, 3000) == project.planned_chapters(proj, 3000)
