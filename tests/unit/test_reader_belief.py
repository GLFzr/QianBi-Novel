# -*- coding: utf-8 -*-
"""B3/WA3-b 读者认知三段式册（app/core/reader_belief.py + state_card 第 6 栏升级）

- 误知登记：belief/truth 必填（goink 预校验同款，缺即拒绝）/同名活跃原位更新
- resolve_misconception：揭穿置 resolved_ch；已回收不重复命中
- due_query：payoff 到期未兑现 → fail 候选（计划章已过才报，超期章数降序）
- 第 6 栏三段压缩版：已知常驻≤5/悬念≤5/误知≤3、段预算 ≤1.2KB≈12KB 的 10%、
  超限丢弃序 设定型known→误知→悬念；sidecar 缺失 → 状态卡逐字不变
全部 tmp_path 真实文件，纯本地零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project
from app.core import reader_belief as rb
from app.core import state_card


def _proj(tmp_path, name="书"):
    proj = str(tmp_path / name)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    return proj


def test_record_mention_upsert_and_kind_immutable(tmp_path):
    """known 登记/提及刷新：同文推进 last_mention_ch 取最大；kind 首登记生效不降级"""
    proj = _proj(tmp_path)
    e = rb.record_mention(proj, 1, "张三身份是捕快", kind=rb.KIND_SETTING)
    assert e["created_ch"] == 1 and e["last_mention_ch"] == 1 and e["kind"] == "setting"
    e = rb.record_mention(proj, 5, "张三身份是捕快", kind=rb.KIND_EVENT)
    assert e["last_mention_ch"] == 5 and e["kind"] == "setting"      # 不降级改类
    data = rb.load(proj)
    assert len(data["known"]) == 1 and data["version"] == 1
    # 事件型照常登记（近三章速记语义载体）
    rb.record_mention(proj, 6, "当铺失火")
    kinds = {e["kind"] for e in rb.load(proj)["known"]}
    assert kinds == {"setting", "event"}


def test_misconception_register_validation_and_update(tmp_path):
    """误知登记：三字段缺一拒绝不落盘；同名活跃原位更新 created_ch 不变"""
    proj = _proj(tmp_path)
    e, err = rb.register_misconception(proj, 6, "李四投敌", "读者以为李四背叛了主角",
                                       "李四是卧底", payoff_planned_ch=20)
    assert e and not err and e["created_ch"] == 6 and e["resolved_ch"] is None
    # 预校验拒绝（goink：misconception 必须带 related_truth）
    for bad in (("m", "只有信念", ""), ("m", "", "只有真相"), ("", "b", "t")):
        got, err = rb.register_misconception(proj, 7, *bad)
        assert got is None and err
    assert len(rb.load(proj)["misconceptions"]) == 1          # 拒绝不落盘
    # 同名活跃重复登记 → 原位更新
    e, err = rb.register_misconception(proj, 8, "李四投敌", "改口信念", "真相反转", payoff_planned_ch=22)
    assert not err and e["created_ch"] == 6 and e["payoff_planned_ch"] == 22
    assert len(rb.load(proj)["misconceptions"]) == 1
    # 已回收同名可再种（新一轮误知）
    rb.resolve_misconception(proj, "李四投敌", 20)
    e2, err = rb.register_misconception(proj, 25, "李四投敌", "二轮", "二轮真相")
    assert not err and len(rb.load(proj)["misconceptions"]) == 2


def test_resolve_misconception_and_active_isolation(tmp_path):
    proj = _proj(tmp_path)
    rb.register_misconception(proj, 6, "李四投敌", "读者以为李四背叛了主角", "李四是卧底")
    rb.register_misconception(proj, 7, "珠钗是赃物", "读者以为珠钗来路不正", "珠钗是御赐")
    assert rb.resolve_misconception(proj, "李四投敌", 20) is True
    assert rb.resolve_misconception(proj, "李四投敌", 21) is False     # 已回收不再命中
    assert rb.resolve_misconception(proj, "不存在", 21) is False
    data = rb.load(proj)
    states = {e["name"]: e["resolved_ch"] for e in data["misconceptions"]}
    assert states == {"李四投敌": 20, "珠钗是赃物": None}              # 记录保留（goink 语义）


def test_due_query_overdue_only(tmp_path):
    """due_query 到期断言：计划章当章不报、次章起报超期；已回收/无窗口不报"""
    proj = _proj(tmp_path)
    rb.register_misconception(proj, 6, "李四投敌", "读者以为李四背叛了主角", "李四是卧底",
                              payoff_planned_ch=20)
    rb.register_misconception(proj, 2, "无窗误知", "b", "t")            # 无 payoff 窗口
    rb.register_suspense(proj, 3, "谁杀了村长", truth="王大锤", due_ch=22)
    # 计划章当章：尚未超期 → 恒空
    assert rb.due_query(proj, 20) == []
    # 次章起：误知超期入清单
    due = rb.due_query(proj, 21)
    assert len(due) == 1 and due[0]["kind"] == "misconception"
    assert due[0]["name"] == "李四投敌" and due[0]["overdue_by"] == 1
    assert due[0]["claim"] == "读者以为李四背叛了主角" and due[0]["truth"] == "李四是卧底"
    # 悬念窗口同口径（due_ch 次章起报）；清单按超期章数降序
    due = rb.due_query(proj, 25)
    assert [(d["kind"], d["overdue_by"]) for d in due] == [
        ("misconception", 5), ("suspense", 3)]
    # 揭穿后出清
    rb.resolve_misconception(proj, "李四投敌", 21)
    assert [d["kind"] for d in rb.due_query(proj, 25)] == ["suspense"]


def test_resolve_suspense_closes_window(tmp_path):
    """悬念回收：resolved 置章后出清 due_query；重复回收与未登记返回 False"""
    proj = _proj(tmp_path)
    rb.register_suspense(proj, 3, "谁杀了村长", truth="王大锤", due_ch=12)
    assert rb.resolve_suspense(proj, "谁杀了村长", 20) is True
    assert rb.resolve_suspense(proj, "谁杀了村长", 21) is False
    assert rb.resolve_suspense(proj, "不存在", 21) is False
    assert rb.due_query(proj, 30) == []
    e = rb.load(proj)["suspense"][0]
    assert e["resolved_ch"] == 20 and e["truth"] == "王大锤"   # 记录保留（goink 语义）
    # 同文已回收后可再种新悬念
    rb.register_suspense(proj, 25, "谁杀了村长", truth="另有其人", due_ch=40)
    assert len(rb.load(proj)["suspense"]) == 2


def test_three_part_items_caps_order_and_budget(tmp_path):
    """三段版：显示序 已知→悬念→误知；段上限 5/5/3；合计 ≤1.2KB（≈12KB 预算 10%）"""
    proj = _proj(tmp_path)
    for i in range(8):
        rb.record_mention(proj, i + 1, "设定事实%02d号条目内容" % i, kind=rb.KIND_SETTING)
    for i in range(7):
        rb.register_suspense(proj, i + 1, "悬念问题%02d号谁是幕后真凶" % i, due_ch=30 + i)
    for i in range(5):
        rb.register_misconception(proj, i + 1, "误知%02d号" % i, "读者以为%02d号是好人" % i,
                                  "实为%02d号是内鬼" % i, payoff_planned_ch=40 + i)
    items = rb.three_part_items(proj, 10)
    known = [x for x in items if x.startswith("〔已知〕")]
    susp = [x for x in items if x.startswith("〔悬念〕")]
    mis = [x for x in items if x.startswith("〔误知〕")]
    assert len(known) == 5 and len(susp) == 5 and len(mis) == 3
    assert items[:5] == known and items[5:10] == susp and items[10:] == mis   # 显示序
    total = sum(len(x.encode("utf-8")) for x in items)
    assert 0 < total <= rb.SEGMENT_BUDGET
    # 临期悬念排前（due 升序）
    assert "悬念问题00" in susp[0] and "悬念问题04" in susp[4]
    # 误知行带 belief→truth 对账面
    assert "→实为：" in mis[0]


def test_three_part_budget_trim_order(tmp_path, monkeypatch):
    """超限丢弃序：设定型 known → 误知 → 悬念（悬念保到最後）"""
    proj = _proj(tmp_path)
    rb.record_mention(proj, 1, "设定甲", kind=rb.KIND_SETTING)
    rb.record_mention(proj, 2, "设定乙", kind=rb.KIND_SETTING)
    rb.register_suspense(proj, 1, "悬念甲", due_ch=9)
    rb.register_suspense(proj, 2, "悬念乙", due_ch=9)
    rb.register_misconception(proj, 1, "误知甲", "信念甲", "真相甲")
    rb.register_misconception(proj, 2, "误知乙", "信念乙", "真相乙")
    monkeypatch.setattr(rb, "SEGMENT_BUDGET", 1)      # 逼到极限 → 全部丢弃（fail-open 优先于塞垃圾）
    assert rb.three_part_items(proj, 5) == []
    # 逐档放宽：预算 60 → 只剩临期悬念甲；预算 120 → 悬念两条都在，误知/已知被丢
    monkeypatch.setattr(rb, "SEGMENT_BUDGET", 60)
    items = rb.three_part_items(proj, 5)
    assert len(items) == 1 and items[0].startswith("〔悬念〕悬念甲")
    monkeypatch.setattr(rb, "SEGMENT_BUDGET", 120)
    items = rb.three_part_items(proj, 5)
    assert all(x.startswith("〔悬念〕") for x in items) and len(items) == 2


def test_state_card_column6_upgrade_and_absent_identity(tmp_path):
    """第 6 栏：三段条目在场且位于近三章速记栏；无读者认知册 → 状态卡逐字不变"""
    base = _proj(tmp_path, "base")
    seeded = _proj(tmp_path, "seeded")
    for proj in (base, seeded):
        with open(os.path.join(proj, "追踪", "章节摘要.md"), "a", encoding="utf-8") as f:
            f.write("- 第1章《过场》：第1章发生了一些事。\n")
    rb.record_mention(seeded, 1, "蓝晶是贵重晶体", kind=rb.KIND_SETTING)
    rb.register_suspense(seeded, 1, "黑袍人是谁", truth="先祖", due_ch=12)
    rb.register_misconception(seeded, 2, "陆云舟是盟友", "读者以为陆云舟可信",
                              "内鬼", payoff_planned_ch=15)
    card_base = state_card.build_state_card(base, 3, proj_io=project)
    card_seeded = state_card.build_state_card(seeded, 3, proj_io=project)
    col = card_seeded.split("## 近三章速记(读者已知)")[1].split("## ")[0]
    assert "〔已知〕蓝晶是贵重晶体（第1章起）" in col
    assert "〔悬念〕黑袍人是谁" in col and "计划第12章前揭示" in col
    assert "〔误知〕读者以为陆云舟可信→实为：内鬼" in col
    # 近三章速记语义保留：摘要行在三段之后（超限最先被裁的尾部位置）
    assert col.index("〔已知〕") < col.index("第1章《过场》")
    # 无读者认知册 → 第 6 栏与 0.22 逐字一致（无三段标记）
    assert "〔已知〕" not in card_base and "〔悬念〕" not in card_base
    assert card_base == ("# 续写状态卡（第3章）\n\n## 当前位置\n- 已定稿至第0章；下一章第3章。"
                         "\n\n## 连贯性风险\n- 第3章细纲未生成（承诺栏为大纲回退，开写前宜先补细纲）"
                         "\n\n## 近三章速记(读者已知)\n- 第1章《过场》：第1章发生了一些事。\n")
