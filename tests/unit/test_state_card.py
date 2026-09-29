# -*- coding: utf-8 -*-
"""卡9-P2 续写状态卡（app/core/state_card.py，移植 proto/p2_state_card.py）

- 常规形态：七栏齐备、≤12288B、零裁剪零审计（原型实测常规 2015~4130B）
- 压力形态：解除结构性上限后 12KB 硬上限触发、按 P5→P1 优先级整项裁剪、
  审计日志逐项留痕、P0（当前位置/下一章承诺）永不丢
- 原型三坑回归：区间计划回收、角色只认登记名、「（暂无）」占位容忍
全部 tmp_path 真实文件，纯本地零 API。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project
from app.core import memory, state_card, tracking_store


def _proj(tmp_path):
    proj = str(tmp_path / "书")
    for d in ("追踪", "正文", "大纲", "设定"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    return proj


def _seed_regular(proj):
    """五章书 + 全套追踪：角色册/伏笔表（含超期与无窗口）/摘要链/细纲/正则 must"""
    for n in range(1, 6):
        with open(os.path.join(proj, "正文", "第%03d章_过场.md" % n), "w",
                  encoding="utf-8") as f:
            f.write("# 第%d章\n%s在灯下翻看账册，陆云舟提到了黑袍人的令牌。" % (n, "沈孤灯" if n % 2 else "阿蓟"))
        memory.append_chapter_summary(proj, n, "过场%d" % n, "第%d章发生了一些事。" % n)
    with open(os.path.join(proj, "追踪", "角色状态.md"), "w", encoding="utf-8") as f:
        f.write("# 角色状态追踪\n\n## 沈孤灯\n"
                "- **当前身份**：守夜人\n- **当前能力**：点灯改命\n"
                "- **关键关系**：阿蓟（搭档）\n- **公众形象**：孤僻\n"
                "- **待回收伏笔**：无\n- **状态变更记录**：（暂无）\n\n"
                "## 阿蓟\n- **当前身份**：拾骨人\n- **当前能力**：辨认残骸\n"
                "- **关键关系**：沈孤灯（搭档）\n- **公众形象**：沉默\n"
                "- **待回收伏笔**：无\n- **状态变更记录**：（暂无）\n")
    with open(os.path.join(proj, "追踪", "伏笔.md"), "w", encoding="utf-8") as f:
        f.write("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                "|------|------|----------|------|----------|------|\n"
                "| 黑袍人的令牌 | 物 | 第1章 | 已埋 | 第3章 | 区间坑①用例改单章 |\n"
                "| 前朝账册的下落 | 物 | 第2章 | 已埋 | 第5-10章 | 区间计划回收 |\n"
                "| 老掌柜的旧债 | 事 | 第2章 | 已埋 | 第N单元 | 无窗口 |\n"
                "| 已收的珠钗 | 物 | 第1章 | 已回收 | 第2章 | 第2章回收 |\n")
    with open(os.path.join(proj, "大纲", "细纲_第006章.md"), "w", encoding="utf-8") as f:
        f.write("#### 情节安排\n- 主线推进：沈孤灯当众验账，揭穿假账册。\n\n"
                "#### 结尾设定和钩子\n- 章尾钩子：门外传来三长两短的叩门声。\n\n"
                "- 字数目标：3000\n")
    with open(os.path.join(proj, "设定", "正则.md"), "w", encoding="utf-8") as f:
        f.write("# 正则\n\n- 规则：禁止出现现代物品与网络用语｜level: must｜scope: 全书\n"
                "- 规则：每章至少一处具体物件描写｜level: should｜scope: 全书\n")


def test_regular_card_seven_sections_under_budget(tmp_path):
    proj = _proj(tmp_path)
    _seed_regular(proj)
    card, audit = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert len(card.encode("utf-8")) <= state_card.BYTE_BUDGET
    assert audit == []                       # 常规书远未到 12KB，零裁剪
    for header in ("当前位置", "下一章承诺", "活跃伏笔(作者真相)", "核心角色状态",
                   "长期约束(正则must)", "近三章速记(读者已知)", "连贯性风险"):
        assert "## %s" % header in card
    # 承诺栏吃细纲（字段名跨项目容忍：主线推进/章尾钩子/字数目标）
    assert "揭穿假账册" in card and "叩门声" in card and "3000" in card
    # 活跃伏笔：已回收条目不进卡；无窗口条目照进（作者真相栏不裁数据，风险栏才追责）
    assert "黑袍人的令牌" in card and "已收的珠钗" not in card
    assert "老掌柜的旧债" in card
    # 角色：近 3 章出场频次排序（近3章=第3/4/5章：沈孤灯 2 次 > 阿蓟 1 次）
    assert card.index("沈孤灯") < card.index("阿蓟")
    # must 栏只收 must 级
    assert "禁止出现现代物品" in card and "should" not in card
    # 风险栏：区间计划回收取 [min,max]（坑①：第5-10章在 cur=5 时不算逾期）
    assert "前朝账册的下落" not in card.split("## 连贯性风险")[1]


def test_overdue_and_zero_mention_risks(tmp_path):
    proj = _proj(tmp_path)
    _seed_regular(proj)
    card, _ = state_card.build_state_card_detail(proj, 6, proj_io=project)
    risks = card.split("## 连贯性风险")[1]
    # 黑袍人的令牌计划第3章，cur=5 → 超期2章（确定性风险，与卡2 引擎同源）
    assert "黑袍人的令牌" in risks and "超期" in risks
    # 题材定位角色表未登记且近3章零出场的注册角色 → 行踪提示（阿蓟近3章出现过2次不提示；
    # 沈孤灯出现过——构造第三名零出场角色验证）
    tracking_store.apply_character_updates(
        proj, 1, [], [],
        new_chars=[{"id": "白面掌柜", "当前身份": "当铺掌柜", "record": "登场"}])
    card2, _ = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert "白面掌柜" in card2.split("## 连贯性风险")[1]
    assert "再登场需交代行踪" in card2


def test_stress_trim_under_budget_with_audit(tmp_path):
    """压力形态（移植原型：解除结构性上限模拟 200 章涨满）——裁剪后 ≤12288B 且审计逐项留痕"""
    proj = _proj(tmp_path)
    _seed_regular(proj)
    long_desc = "身份层层嵌套；" + "线索盘根错节，" * 60            # ≈420 字/角色
    new_chars = [{"id": "角色%02d" % i, "当前身份": long_desc, "当前能力": long_desc,
                  "record": "登场"} for i in range(30)]
    tracking_store.apply_character_updates(proj, 1, [], [], new_chars=new_chars)
    rows = [{"伏笔": "压力伏笔%02d号线索" % i, "类别": "物", "埋设章节": "第1章",
             "状态": "已埋", "计划回收": "第%d章" % (i + 10), "备注": "压力样本"}
            for i in range(24)]
    with open(os.path.join(proj, "追踪", "伏笔表.json"), "w", encoding="utf-8") as f:
        import json
        json.dump({"version": 1, "rows": rows}, f, ensure_ascii=False)

    card, audit = state_card.build_state_card_detail(proj, 6, stress=True, proj_io=project)
    assert len(card.encode("utf-8")) <= state_card.BYTE_BUDGET
    assert audit, "压力样本必须触发裁剪并留审计"
    # 裁剪顺序 P5→P4→P3→P2→P1：第一条审计必是近三章速记
    assert audit[0].startswith("裁剪 [近三章速记(读者已知)]")
    # 整项取舍不截半句：审计里每条都带完整前缀标记
    assert all(a.startswith("裁剪 [") for a in audit)
    # P0 永不丢：当前位置与下一章承诺仍在卡上
    assert "## 当前位置" in card and "揭穿假账册" in card
    # 常规模式（结构性上限在）同一数据源依旧远小于预算、零审计
    card_norm, audit_norm = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert audit_norm == [] and len(card_norm.encode("utf-8")) <= state_card.BYTE_BUDGET
    # 公共入口与 detail 一致
    assert state_card.build_state_card(proj, 6, stress=True, proj_io=project) == card


def test_placeholder_and_missing_data_fail_open(tmp_path):
    """坑③：「（暂无）」占位与全套缺失 → 空卡不炸、字节为零级开销"""
    proj = _proj(tmp_path)
    with open(os.path.join(proj, "追踪", "上下文.md"), "w", encoding="utf-8") as f:
        f.write("（暂无）")
    card = state_card.build_state_card(proj, 1, proj_io=project)
    assert "已定稿至第0章；下一章第1章" in card
    assert "进度速记" not in card            # 占位剥掉不注入
    assert "## 近三章速记(读者已知)" not in card
