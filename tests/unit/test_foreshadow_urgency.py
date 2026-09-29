# -*- coding: utf-8 -*-
"""卡2/T3 伏笔到期引擎（app/core/tracking_store.py + memory.py + l0_checks.py）

- parse_recovery_window：「计划回收」列 → (min, max)（区间不取首数字，P2 原型坑①回归）
- foreshadow_urgency：超期排最前、排除已回收/已失效、无窗口殿后
- memory.unfished_foreshadows：超期带【超期N章】前缀且排首（四消费方共用注入源）
- l0_checks.foreshadow_findings：超期伏笔本批无回收/改期 → fail候选
全部 tmp_path 真实文件，纯本地零 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import tracking_store as ts
from app.core import memory
from app.core.l0_checks import foreshadow_findings


def test_parse_recovery_window():
    """四例主断言 + 边界：区间取 [min,max]、单元/待定无窗口、裸数字、混合分隔符"""
    assert ts.parse_recovery_window("第40-45章") == (40, 45)      # 区间不取首数字（坑①）
    assert ts.parse_recovery_window("第N单元") == (None, None)
    assert ts.parse_recovery_window("40") == (40, 40)
    assert ts.parse_recovery_window("第40章") == (40, 40)
    assert ts.parse_recovery_window("第5-10章") == (5, 10)
    assert ts.parse_recovery_window("40~45") == (40, 45)
    assert ts.parse_recovery_window("第40—45章") == (40, 45)
    assert ts.parse_recovery_window("待定") == (None, None)
    assert ts.parse_recovery_window("") == (None, None)
    assert ts.parse_recovery_window(None) == (None, None)


def _rows():
    return [
        {"伏笔": "远期甲", "类别": "物", "埋设章节": "第1章", "状态": "已埋",
         "计划回收": "第90章", "备注": ""},
        {"伏笔": "临期乙", "类别": "人", "埋设章节": "第2章", "状态": "已埋",
         "计划回收": "第42章", "备注": ""},
        {"伏笔": "超期丙", "类别": "事", "埋设章节": "第3章", "状态": "已埋",
         "计划回收": "第40-45章", "备注": ""},
        {"伏笔": "超期更久丁", "类别": "物", "埋设章节": "第4章", "状态": "已埋",
         "计划回收": "第20章", "备注": ""},
        {"伏笔": "无窗口戊", "类别": "事", "埋设章节": "第5章", "状态": "已埋",
         "计划回收": "第N单元", "备注": ""},
        {"伏笔": "已回收己", "类别": "物", "埋设章节": "第6章", "状态": "已回收",
         "计划回收": "第10章", "备注": "第10章回收"},
        {"伏笔": "已失效庚", "类别": "事", "埋设章节": "第7章", "状态": "已失效",
         "计划回收": "第30章", "备注": "作者裁决废弃：主线改道"},
    ]


def test_overdue_sorted_first_and_marked():
    """超期条目排最前（超期章数降序），tag 带【超期】语义；已回收/已失效不参与"""
    ranked = ts.foreshadow_urgency({"rows": _rows()}, cur_num=50)
    names = [r["伏笔"] for r, _tag in ranked]
    # 超期三位排最前：丁（超30章）> 乙（超8章）> 丙（超5章）；已回收己 / 已失效庚被排除
    assert names[:3] == ["超期更久丁", "临期乙", "超期丙"]
    assert "已回收己" not in names and "已失效庚" not in names
    tags = {r["伏笔"]: tag for r, tag in ranked}
    assert tags["超期更久丁"] == "超期30章"
    assert tags["临期乙"] == "超期8章"
    # 坑①：区间计划回收「第40-45章」按窗口末端判超期，超期 = 50 - 45 = 5
    assert tags["超期丙"] == "超期5章"
    assert tags["无窗口戊"] == "无窗口"
    assert tags["远期甲"] == ""               # 远期不标记


def test_overdue_ordering_and_no_window_last():
    """超期 > 临期 > 无窗口 > 远期 的全序（cur_num 未越过窗口时）"""
    ranked = ts.foreshadow_urgency(_rows(), cur_num=40)
    names = [r["伏笔"] for r, _tag in ranked]
    # cur=40：丁超期20章；乙剩2章；丙窗口 [40,45] 内剩5章；戊无窗口；甲远期
    assert names.index("超期更久丁") < names.index("临期乙") < names.index("超期丙") \
        < names.index("无窗口戊") < names.index("远期甲")
    tags = {r["伏笔"]: tag for r, tag in ranked}
    assert tags["超期更久丁"] == "超期20章"
    assert tags["临期乙"] == "剩2章"
    assert tags["超期丙"] == "剩5章"


def test_unfished_foreshadows_sorted_and_prefixed(tmp_path):
    """注入源排序：超期必在首且带【超期N章】前缀，无窗口带【无回收窗口】前缀"""
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    header = ("# 伏笔追踪\n\n> 状态：未埋 / 已埋 / 已回收 / 已失效\n\n"
              "| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
              "|------|------|----------|------|----------|------|\n")
    body = "".join("| %s | %s | %s | %s | %s | %s |\n" % (
        r["伏笔"], r["类别"], r["埋设章节"], r["状态"], r["计划回收"], r["备注"])
        for r in _rows())
    with open(os.path.join(proj, "追踪", "伏笔.md"), "w", encoding="utf-8") as f:
        f.write(header + body)
    with open(os.path.join(proj, "正文", "第0050章_锚.md"), "w", encoding="utf-8") as f:
        f.write("# 第50章\n正文")
    out = memory.unfished_foreshadows(proj)
    first_line = next(ln for ln in out.splitlines() if ln.startswith("|") and "超期" in ln)
    assert first_line.startswith("| 【超期30章】超期更久丁 |")
    assert "【无回收窗口】无窗口戊" in out
    assert "已回收己" not in out and "已失效庚" not in out
    # 超期行必须出现在无窗口/远期行之前
    assert out.index("超期更久丁") < out.index("无窗口戊") < out.index("远期甲")
    # 签名不变的 limit 截断依旧生效
    assert len(memory.unfished_foreshadows(proj, limit=60)) <= 60


_BATCH_SEG = """#### 伏笔推进
- 本章推进：{name}——线索在当铺账本里再次浮现
- 本章回收：{name}当众焚毁，令牌上的纹路认主
- 新埋设：无
"""


def test_batch_l0_requires_payoff_or_defer(tmp_path):
    """超期伏笔本批无回收/改期 → fail候选；安排了回收或带新窗口的挂起 → 不报"""
    proj = str(tmp_path / "书")
    os.makedirs(os.path.join(proj, "追踪"), exist_ok=True)
    with open(os.path.join(proj, "追踪", "伏笔表.json"), "w", encoding="utf-8") as f:
        f.write('{"version": 1, "rows": [{"伏笔": "黑袍人的令牌", "类别": "物", '
                '"埋设章节": "第12章", "状态": "已埋", "计划回收": "第40章", "备注": ""}]}')
    outlines = [(45, "过场", "#### 伏笔推进\n- 本章推进：无\n- 本章回收：无\n")]
    fs = foreshadow_findings(proj, outlines, cur_num=45)
    assert len(fs) == 1
    assert fs[0]["level"] == "fail候选" and fs[0]["check"] == "伏笔到期"
    assert "黑袍人的令牌" in fs[0]["text"]

    # 本批某章「伏笔推进」安排了回收 → 不报
    paid = [(45, "收网", _BATCH_SEG.format(name="黑袍人的令牌"))]
    assert foreshadow_findings(proj, paid, cur_num=45) == []

    # 显式改期（带新窗口的挂起）→ 不报
    deferred = [(45, "过场", "#### 伏笔推进\n- 本章推进：黑袍人的令牌，继续挂起（预计第60章）\n")]
    assert foreshadow_findings(proj, deferred, cur_num=45) == []

    # 裸「未定」不算交代 → 仍报（无声挂起零容忍）
    vague = [(45, "过场", "#### 伏笔推进\n- 本章推进：黑袍人的令牌，回收：未定\n")]
    assert len(foreshadow_findings(proj, vague, cur_num=45)) == 1

    # 无超期条目（cur_num 未越过窗口）→ 恒空（证据在场才检查）
    assert foreshadow_findings(proj, outlines, cur_num=38) == []
