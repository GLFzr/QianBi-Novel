# -*- coding: utf-8 -*-
"""B4/WA4 伏笔补链（app/core/tracking_store.py：advance 语义+plant 前置校验+重写回补）

- 三态迁移：未埋/已埋 → 推进中 → 已回收（终态不推进；同章去重；推进中照常
  按活跃参与卡2 urgency 排序——不推翻只补态）
- plant 前置校验：回收窗口字段合法性只警示不阻断（fail-open），更新行不校验
- 重写回补：章重写后撤销该章推进（后续章已接续的不动状态，日志清零可重登记）
卡2 原五例（test_foreshadow_urgency）保持绿。
全部 tmp_path 真实文件，纯本地零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import tracking_store as ts


def _proj(tmp_path, name="书"):
    proj = str(tmp_path / name)
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    return proj


def _seed_rows(proj, rows):
    with open(os.path.join(proj, "追踪", "伏笔表.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "rows": rows}, f, ensure_ascii=False)


def _status(proj, name):
    for r in ts.load_foreshadow(proj).get("rows") or []:
        if r.get("伏笔") == name:
            return str(r.get("状态") or "")
    return None


def test_advance_three_state_transition(tmp_path):
    """三态迁移：已埋→推进中→已回收；未埋也可推进；终态拒绝；同章去重幂等"""
    proj = _proj(tmp_path)
    _seed_rows(proj, [
        {"伏笔": "黑袍人的令牌", "类别": "物", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "第40章", "备注": ""},
        {"伏笔": "已回收的珠钗", "类别": "物", "埋设章节": "第1章", "状态": "已回收",
         "计划回收": "第10章", "备注": ""},
        {"伏笔": "无名刻痕", "类别": "物", "埋设章节": "第20章", "状态": "",
         "计划回收": "第50章", "备注": ""},
    ])
    out = ts.advance_foreshadow(proj, 30, ["黑袍人的令牌"])
    assert out == {"advanced": ["黑袍人的令牌"], "skipped": []}
    assert _status(proj, "黑袍人的令牌") == "推进中"
    # 同章重复推进 → 幂等跳过；终态拒绝；模糊名唯一命中
    out = ts.advance_foreshadow(proj, 30, ["黑袍人的令牌", "已回收的珠钗", "令牌"])
    assert out["advanced"] == []
    assert ("黑袍人的令牌", "本章已登记推进") in out["skipped"]
    assert ("已回收的珠钗", "已回收") in out["skipped"]
    assert len(ts.load_foreshadow(proj).get("advances")) == 1      # 日志不重复
    # 未登记/空名 → 跳过不臆造
    out = ts.advance_foreshadow(proj, 31, ["查无此伏笔", ""])
    assert out["advanced"] == [] and ("查无此伏笔", "未登记") in out["skipped"]
    # 空状态行按未埋推进（from 记 未埋）
    out = ts.advance_foreshadow(proj, 31, ["无名刻痕"])
    assert out["advanced"] == ["无名刻痕"]
    log = ts.load_foreshadow(proj)["advances"]
    assert {"name": "无名刻痕", "ch": 31, "from": "未埋", "to": "推进中"} in log
    # 推进中 → 已回收（回收走既有 upsert 通道，advance 对终态让位）
    ts.apply_foreshadow_upserts(proj, [{"伏笔": "黑袍人的令牌", "状态": "已回收"}])
    out = ts.advance_foreshadow(proj, 32, ["黑袍人的令牌"])
    assert out["advanced"] == [] and ("黑袍人的令牌", "已回收") in out["skipped"]


def test_advance_participates_in_urgency_as_active(tmp_path):
    """「推进中」不在排除集——照常按活跃参与卡2 urgency 排序（不推翻只补态）"""
    proj = _proj(tmp_path)
    _seed_rows(proj, [
        {"伏笔": "推进中的甲", "类别": "物", "埋设章节": "第1章", "状态": "推进中",
         "计划回收": "第10章", "备注": ""},
        {"伏笔": "已失效乙", "类别": "事", "埋设章节": "第2章", "状态": "已失效",
         "计划回收": "第5章", "备注": ""},
    ])
    ranked = ts.foreshadow_urgency(ts.load_foreshadow(proj), cur_num=13)
    names = [r["伏笔"] for r, _tag in ranked]
    assert names == ["推进中的甲"] and ranked[0][1] == "超期3章"
    # 派生视图 legend 含中间态
    md = ts.render_foreshadow_md(proj)
    assert "推进中" in md.splitlines()[2] and "| 推进中的甲 |" in md


def test_validate_plant_window_and_plant_fail_open(tmp_path):
    """plant 前置校验：窗口早于埋设=唯一非法态；警示不阻断（fail-open）；更新行不校验"""
    # 纯函数三档
    assert ts.validate_plant_window("第40-45章", 12) == (True, "")
    assert ts.validate_plant_window("待定", 12) == (True, "无窗口")
    assert ts.validate_plant_window("第N单元", 12) == (True, "无窗口")
    assert ts.validate_plant_window("", None) == (True, "无窗口")
    ok, reason = ts.validate_plant_window("第5章", 12)
    assert not ok and reason == "计划回收第5章早于埋设第12章"
    # plant 通道：非法窗口仍登记（fail-open）+ warnings 留证
    proj = _proj(tmp_path)
    out = ts.plant_foreshadow(proj, 12, [
        {"伏笔": "倒挂窗口", "类别": "物", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "第5章", "备注": ""},
        {"伏笔": "正常窗口", "类别": "事", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "第40-45章", "备注": ""},
        {"伏笔": "待定窗口", "类别": "物", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "待定", "备注": ""},
    ])
    assert out["changed"] == ["倒挂窗口", "正常窗口", "待定窗口"]
    assert out["warnings"] == [{"伏笔": "倒挂窗口", "reason": "计划回收第5章早于埋设第12章"}]
    assert _status(proj, "倒挂窗口") == "已埋"                      # 原样落表不阻断
    # 埋设章节缺省 → 以登记章号代埋设章
    out = ts.plant_foreshadow(proj, 30, [
        {"伏笔": "缺埋设行", "类别": "物", "状态": "已埋", "计划回收": "第8章", "备注": ""}])
    assert out["warnings"][0]["reason"] == "计划回收第8章早于埋设第30章"
    # 既有行更新（改期/回收）不校验
    out = ts.plant_foreshadow(proj, 31, [
        {"伏笔": "倒挂窗口", "类别": "物", "埋设章节": "第12章", "状态": "已回收",
         "计划回收": "第1章", "备注": "改期回收"}])
    assert out["warnings"] == [] and _status(proj, "倒挂窗口") == "已回收"


def test_rewrite_rollback_restores_pre_rewrite_state(tmp_path):
    """重写回补：该章推进回滚到重写前；后续章接续推进/回收的不动状态；日志清零可重登记"""
    proj = _proj(tmp_path)
    _seed_rows(proj, [
        {"伏笔": "甲令牌", "类别": "物", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "第40章", "备注": ""},
        {"伏笔": "乙刻痕", "类别": "物", "埋设章节": "第12章", "状态": "已埋",
         "计划回收": "第45章", "备注": ""},
    ])
    # 第 12 章旧版：推进甲、乙；第 13 章接续推进甲（跨章链）
    ts.advance_foreshadow(proj, 12, ["甲令牌", "乙刻痕"])
    ts.advance_foreshadow(proj, 13, ["甲令牌"])
    assert _status(proj, "甲令牌") == "推进中" and _status(proj, "乙刻痕") == "推进中"
    # 重写第 12 章：乙回滚到已埋；甲因第 13 章已接续推进，状态不动
    rolled = ts.rollback_foreshadow_advances(proj, 12)
    assert rolled == ["乙刻痕"]
    assert _status(proj, "乙刻痕") == "已埋" and _status(proj, "甲令牌") == "推进中"
    log = ts.load_foreshadow(proj)["advances"]
    assert [e["ch"] for e in log] == [13]                      # 第 12 章日志清零
    # 重写后重定稿：同章再推进不再被去重挡住（幂等键随日志清零释放）
    out = ts.advance_foreshadow(proj, 12, ["乙刻痕"])
    assert out["advanced"] == ["乙刻痕"] and _status(proj, "乙刻痕") == "推进中"
    # 已回收不受回补影响（终态不被旧章日志改写）
    ts.apply_foreshadow_upserts(proj, [{"伏笔": "乙刻痕", "状态": "已回收"}])
    assert ts.rollback_foreshadow_advances(proj, 12) == []
    assert _status(proj, "乙刻痕") == "已回收"
    # 无日志/损坏条目 fail-open
    assert ts.rollback_foreshadow_advances(_proj(tmp_path, "空书"), 12) == []


def test_card2_original_five_cases_stay_green(tmp_path):
    """卡2 引擎回归锚：parse_recovery_window/urgency 排序在补态后行为不变"""
    assert ts.parse_recovery_window("第40-45章") == (40, 45)
    assert ts.parse_recovery_window("第N单元") == (None, None)
    rows = [
        {"伏笔": "超期丙", "类别": "事", "埋设章节": "第3章", "状态": "已埋",
         "计划回收": "第40-45章", "备注": ""},
        {"伏笔": "已回收己", "类别": "物", "埋设章节": "第6章", "状态": "已回收",
         "计划回收": "第10章", "备注": ""},
        {"伏笔": "推进中庚", "类别": "物", "埋设章节": "第7章", "状态": "推进中",
         "计划回收": "第20章", "备注": ""},
    ]
    ranked = ts.foreshadow_urgency({"rows": rows}, cur_num=50)
    assert [r["伏笔"] for r, _t in ranked] == ["推进中庚", "超期丙"]
    assert ranked[0][1] == "超期30章" and ranked[1][1] == "超期5章"
