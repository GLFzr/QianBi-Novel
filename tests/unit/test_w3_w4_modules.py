# -*- coding: utf-8 -*-
"""0.20.4 W3/W4 模块回归：style_anchor（代理实现）+ hook_carry + opening_score。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())

from app.core import hook_carry, opening_score, style_anchor


def _proj(tmp):
    d = str(tmp)
    for sub in ("设定", "正文", "追踪", "大纲"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def _write(path, text):
    open(path, "w", encoding="utf-8").write(text)


# ---- style_anchor ----

def test_style_anchor_lifecycle(tmp_path):
    d = _proj(tmp_path)
    doc = style_anchor.ensure_file(d)
    assert "文风指纹" in doc and style_anchor.ensure_file(d) == doc
    assert style_anchor.anchor_text(d) == ""          # 全占位
    body = "# 第1章 夜访\n" + "陈默推开值班室的门，登记簿摊在桌上。" * 4 \
           + "\n\n「你来干什么？」值班员问。他盯着对方看了很久。" * 4
    _write(os.path.join(d, "正文", "第001章_夜访.md"), body)
    assert style_anchor.backfill_from_chapter(d, 1) is True
    assert style_anchor.backfill_from_chapter(d, 1) is False   # 幂等
    assert len(style_anchor.anchor_text(d)) >= 100
    assert "带宽" in style_anchor.fingerprint_line(d)   # 返回节体（不含标题字样）
    assert style_anchor.stats_mirror(d) == ""        # 仅 1 章
    _write(os.path.join(d, "正文", "第002章_回声.md"),
           "# 第2章 回声\n" + "他又看了一眼登记簿，没有说话，只是把钢笔挪开。" * 12)
    assert "镜像" in style_anchor.stats_mirror(d)
    blk = style_anchor.assembly_block(d)
    assert "文风锚" in blk and "镜像" in blk


# ---- hook_carry ----

def test_hook_carry_detect_bands():
    hook = "黑车停在楼下，车窗里有人盯着陈默的房间看了一夜。"
    true_open = "陈默拉开窗帘，黑车还在。车窗里那道目光与他对上，他后退半步。"
    assert hook_carry.detect(true_open, hook) == "true"
    assert hook_carry.detect("清晨的阳光洒进厨房，他开始煎蛋。", hook) == "false"
    assert hook_carry.detect("", hook) == "unknown"


def test_hook_carry_pair_and_record(tmp_path):
    d = _proj(tmp_path)
    _write(os.path.join(d, "正文", "第001章_夜访.md"),
           "# 第1章 夜访\n陈默进门。\n\n" + "黑车停在楼下，车窗里有人盯着他看。" * 3)
    _write(os.path.join(d, "追踪", "钩子账本.json"),
           json.dumps([{"num": 1, "position": "章尾", "type": "危机迫近",
                        "summary": "黑车停在楼下，车窗里有人盯着他看"}],
                      ensure_ascii=False))
    _write(os.path.join(d, "正文", "第002章_回声.md"),
           "# 第2章 回声\n黑车还在。他拉开窗帘，与那道目光对上。")
    v = hook_carry.check_chapter_pair(d, 2)
    assert v in ("true", "partial")
    assert hook_carry.record_answer(d, 2, v) is True
    assert hook_carry.record_answer(d, 2, "true") is True   # 覆盖幂等
    assert hook_carry.answered_verdicts(d)["2"] == "true"
    assert hook_carry.check_chapter_pair(d, 1) == "unknown"


# ---- opening_score ----

def test_opening_score_dimensions():
    conflict = "门被踹开的瞬间，陈默先看到刀，再看清来人的脸——是死了三年的师兄。"
    weather = "清晨的阳光洒进厨房，天气很好，他慢慢收拾着碗筷，想着昨天的琐事。"
    assert opening_score.score(conflict) > opening_score.score(weather)
    prev_tail = "黑车停在楼下，车窗里有人盯着陈默的房间看了一夜。"
    recap = "黑车停在楼下，车窗里有人盯着陈默的房间看了一夜。陈默想起来就后怕。"
    assert opening_score.score(recap, prev_tail) < opening_score.score(recap)  # 复述惩罚


def test_opening_best_of():
    cands = ["清晨阳光很好，他散步。", "刀先进门，人后到——陈默的瞳孔骤然收缩。"]
    assert opening_score.best_of(cands) == 1
    assert opening_score.best_of([]) == -1
    assert opening_score.best_of(["仅一稿"]) == 0
