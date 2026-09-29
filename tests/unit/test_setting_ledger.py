# -*- coding: utf-8 -*-
"""B2/WA3-a 设定名词账本（app/core/setting_ledger.py + state_card 适配）

- register 登记：首现自动填、首现不变、真相/类别空位补齐
- 归并：同名/别名/既有名词出现在新条目别名里 → entries 去重为一条
- query 三态：揭示前读者未知(hidden)/到达计划揭示章未揭示(due)/揭示后已知(known)
- fail-open：sidecar 损坏按空账本重建；state_card 无账本时输出逐字不变
全部 tmp_path 真实文件，纯本地零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project
from app.core import setting_ledger as sl
from app.core import state_card


def _proj(tmp_path, name="书"):
    proj = str(tmp_path / name)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    return proj


def test_register_first_chapter_auto_and_immutable(tmp_path):
    """登记：首现自动填；同名再登记首现不变，空位补齐、非空保留（真相不变纪律）"""
    proj = _proj(tmp_path)
    e, created = sl.register(proj, 1, "蓝晶", category="物品",
                             truth="储存记忆的载体", reveal_planned_ch=8)
    assert created and e["first_chapter"] == 1 and e["reader_known_chapter"] is None
    # 第 4 章再次登记同名：首现不变；空 truth/类别由本次补齐，既有真相保留
    e, created = sl.register(proj, 4, "蓝晶", category="物品", truth="", aliases=["蓝晶石"])
    assert not created and e["first_chapter"] == 1
    assert e["truth"] == "储存记忆的载体" and e["aliases"] == ["蓝晶石"]
    # sidecar roundtrip：version + entries 落盘
    data = sl.load(proj)
    assert data["version"] == 1 and len(data["entries"]) == 1
    with open(os.path.join(proj, "追踪", "设定账本.json"), encoding="utf-8") as f:
        assert json.load(f)["entries"][0]["name"] == "蓝晶"


def test_alias_merge_three_paths(tmp_path):
    """归并三路径：同名 / 以别名当名词登记 / 既有名词出现在新条目别名里"""
    proj = _proj(tmp_path)
    sl.register(proj, 1, "蓝晶", aliases=["蓝晶石", "苍蓝结晶"])
    # 路径①：以别名当名词再来 → 归并进同一条，不新增行
    e, created = sl.register(proj, 5, "蓝晶石", truth="别名登记")
    assert not created and len(sl.load(proj)["entries"]) == 1
    # 路径②：新名词的别名命中既有名词 → 归并，既有名变别名
    e, created = sl.register(proj, 6, "秘蓝", aliases=["蓝晶"])
    assert not created and len(sl.load(proj)["entries"]) == 1
    entry = sl.load(proj)["entries"][0]
    assert entry["name"] == "蓝晶"
    aliases = {sl._norm(a) for a in entry["aliases"]}
    assert {sl._norm("蓝晶石"), sl._norm("苍蓝结晶"), sl._norm("秘蓝")} <= aliases
    assert sl._norm("蓝晶") not in aliases          # 自名不出现在别名里
    # 归并后 query_one 用别名可查
    assert sl.query_one(proj, "秘蓝", 6)["name"] == "蓝晶"
    # 三条目Once归并完，别名查询三态字段同源
    assert sl.query_one(proj, "苍蓝结晶", 6)["state"] == "hidden"


def test_query_three_states(tmp_path):
    """按章查询三态：揭示前 hidden → 到达计划章 due → 揭示兑现 known"""
    proj = _proj(tmp_path)
    sl.register(proj, 1, "蓝晶", truth="储存记忆的载体", reveal_planned_ch=8)
    q5 = sl.query_one(proj, "蓝晶", 5)
    assert q5["state"] == "hidden" and q5["reader_known"] is False
    assert q5["truth"] == "储存记忆的载体" and q5["reveal_planned_ch"] == 8
    # 到达计划揭示章仍未揭示 → due
    q8 = sl.query_one(proj, "蓝晶", 8)
    assert q8["state"] == "due" and q8["reader_known"] is False
    # 揭示兑现（第 9 章更新读者已知）→ 第 9 章起 known，第 8 章仍 due
    sl.mark_reader_known(proj, "蓝晶", 9)
    assert sl.query_one(proj, "蓝晶", 9)["state"] == "known"
    assert sl.query_one(proj, "蓝晶", 9)["reader_known"] is True
    assert sl.query_one(proj, "蓝晶", 8)["state"] == "due"
    # 重复兑现取最早章（读者第一次知道为准）
    sl.mark_reader_known(proj, "蓝晶石", 12)
    assert sl.query_one(proj, "蓝晶", 12)["reader_known_chapter"] == 9


def test_update_truth_and_set_reveal(tmp_path):
    proj = _proj(tmp_path)
    sl.register(proj, 1, "蓝晶")
    assert sl.update_truth(proj, "蓝晶", "储存记忆的载体")["truth"] == "储存记忆的载体"
    assert sl.set_reveal(proj, "蓝晶", 8)["reveal_planned_ch"] == 8
    assert sl.query_one(proj, "蓝晶", 3)["reveal_planned_ch"] == 8
    # 未登记名词：操作静默返回 None（fail-open，不抛不写）
    assert sl.mark_reader_known(proj, "不存在", 2) is None
    assert sl.update_truth(proj, "不存在", "x") is None


def test_corrupt_sidecar_fail_open(tmp_path):
    """sidecar 损坏 → 空账本、读零副作用、写时重建；空名登记拒绝"""
    proj = _proj(tmp_path)
    with open(os.path.join(proj, "追踪", "设定账本.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert sl.load(proj) == {"version": 1, "entries": []}
    e, created = sl.register(proj, 2, "蓝晶", truth="t")
    assert created and len(sl.load(proj)["entries"]) == 1
    assert sl.register(proj, 3, "  ") == (None, False)


def _seed_book(tmp_path, name, with_ledger):
    """最小书夹具：两个除设定账本外逐字节相同的工程"""
    proj = _proj(tmp_path, name)
    for n in (1, 2):
        with open(os.path.join(proj, "追踪", "章节摘要.md"), "a", encoding="utf-8") as f:
            f.write("- 第%d章《过场》：第%d章发生了一些事。\n" % (n, n))
    if with_ledger:
        sl.register(proj, 1, "蓝晶", category="物品", truth="储存记忆的载体",
                    reveal_planned_ch=3)
        sl.register(proj, 1, "远期石", category="物", truth="x", reveal_planned_ch=40)
        sl.register(proj, 2, "已知杯", category="物", truth="y", reveal_planned_ch=2)
        sl.mark_reader_known(proj, "已知杯", 2)
    return proj


def test_state_card_lines_due_only(tmp_path):
    """state_card_lines：只收未揭示且窗口临期/超期的条目，已揭示与远期不进"""
    proj = _proj(tmp_path, "书")
    sl.register(proj, 1, "蓝晶", category="物品", truth="储存记忆的载体", reveal_planned_ch=5)
    sl.register(proj, 1, "远期石", truth="x", reveal_planned_ch=40)      # 超出 horizon
    sl.register(proj, 1, "已知杯", truth="y", reveal_planned_ch=2)
    sl.mark_reader_known(proj, "已知杯", 2)                               # 已揭示
    lines = sl.state_card_lines(proj, 5)
    assert len(lines) == 1 and lines[0].startswith("〔设定〕「蓝晶」")
    assert "物品" in lines[0] and "储存记忆的载体" in lines[0]
    assert "计划第5章揭示（到期）" in lines[0] and "首现第1章" in lines[0]
    # 超期 tag
    sl.set_reveal(proj, "蓝晶", 3)
    assert "已超2章" in sl.state_card_lines(proj, 5)[0]
    # 空账本 → 恒空
    assert sl.state_card_lines(_proj(tmp_path, "空书"), 5) == []


def test_state_card_adapter_absent_ledger_byte_identical(tmp_path):
    """只加适配不改结构：无设定账本 → 状态卡与 0.22 逐字节一致；有账本 → 活跃伏笔栏多设定行"""
    base = _seed_book(tmp_path, "base", with_ledger=False)
    with_ledger = _seed_book(tmp_path, "ledger", with_ledger=True)
    card_base = state_card.build_state_card(base, 3, proj_io=project)
    card_ledger = state_card.build_state_card(with_ledger, 3, proj_io=project)
    assert "〔设定〕" not in card_base
    assert "〔设定〕「蓝晶」" in card_ledger
    # 设定行落在「活跃伏笔(作者真相)」栏内
    sec = card_ledger.split("## 活跃伏笔(作者真相)")[1].split("## ")[0]
    assert "〔设定〕「蓝晶」" in sec and "储存记忆的载体" in sec
    # 七栏结构不变：账本卡相对基线卡新增的栏只有「活跃伏笔(作者真相)」自身
    def _titles(card):
        return {chunk.splitlines()[0].strip() for chunk in card.split("## ")[1:]}
    assert _titles(card_ledger) == _titles(card_base) | {"活跃伏笔(作者真相)"}
