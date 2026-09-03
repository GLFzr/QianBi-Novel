# -*- coding: utf-8 -*-
"""剧情反哺写回层：七段解析、世界书追加分区幂等（含实体演进/世界观揭示）、伏笔表增量补丁"""
import os

from app import project
from app.core import memory


BACKFLOW_OUT = """
===新实体===
- 柳三更｜人物｜深夜替人付透析费的灰袍灯客，来历不明
- 铜哨｜道具｜吹响可暂时驱散低阶夜秽
===新规则===
- 灯下禁言令｜灯盟规定执灯人不得在灯阵内交谈
===实体演进===
- 陈更｜余额｜1700→0
- 陈更｜伤势｜右手骨折→已接骨
===世界观揭示===
- 灯盟十三坊｜灯盟按灯坊划分辖区，每坊设执灯人一名
===伏笔变动===
- 新增｜柳三更的账本｜道具谜团｜第12章
- 回收｜妹妹透析费缺口1700元，由柳三更代付
===偏离点===
- 细纲要求本章以雨夜开场，实际正文改为雪夜
===一句话摘要===
陈更在医院偶遇柳三更，对方垫付了妹妹的透析费。
"""


def _mk_proj(tmp_path, worldbook="## 世界书\n\n### 一、夜秽图鉴\n\n怨念絮。\n"):
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), worldbook)
    project.write_file(project.get_tracking_path(proj, "伏笔"),
                       "| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                       "|------|------|----------|------|----------|------|\n"
                       "| 妹妹透析费缺口1700元 | 数字倒计时 | 第1章 | 新设 | 第30-40章 |  |\n")
    return proj


# ---- 七段解析 ----

def test_parse_backflow_full():
    r = memory.parse_backflow(BACKFLOW_OUT)
    assert r["entities"] == [
        ("柳三更", "人物", "深夜替人付透析费的灰袍灯客，来历不明"),
        ("铜哨", "道具", "吹响可暂时驱散低阶夜秽"),
    ]
    assert r["rules"] == [("灯下禁言令", "灯盟规定执灯人不得在灯阵内交谈")]
    assert r["evolutions"] == [("陈更", "余额", "1700→0"), ("陈更", "伤势", "右手骨折→已接骨")]
    assert r["revelations"] == [("灯盟十三坊", "灯盟按灯坊划分辖区，每坊设执灯人一名")]
    assert r["foreshadow_adds"] == [("柳三更的账本", "道具谜团", "第12章")]
    assert r["foreshadow_payoffs"] == ["妹妹透析费缺口1700元，由柳三更代付"]
    assert r["deviations"] == ["细纲要求本章以雨夜开场，实际正文改为雪夜"]
    assert r["summary"].startswith("陈更在医院")


def test_parse_backflow_missing_sections_and_garbage():
    r = memory.parse_backflow("===新实体===\n（无）\n\n废话行不在任何段内")
    assert r["entities"] == [] and r["rules"] == []
    assert r["evolutions"] == [] and r["revelations"] == []
    assert r["foreshadow_adds"] == [] and r["foreshadow_payoffs"] == []
    assert r["summary"] == ""
    r2 = memory.parse_backflow("")          # 空输出不抛
    assert r2["entities"] == []
    r3 = memory.parse_backflow(None)        # None 不抛
    assert r3["summary"] == ""


def test_parse_entity_rules_reused_on_tracking_output():
    text = "===角色状态===\n陈更：受伤。\n===新实体===\n铜哨｜道具｜驱散夜秽"
    ents, rules = memory.parse_entity_rules(text)
    assert ents == [("铜哨", "道具", "驱散夜秽")]
    assert rules == []


def test_parse_evolution_reveals_and_two_part_fallback():
    text = ("===实体演进===\n- 陈更｜余额｜1700→0"
            "\n- 柳三更｜重伤垂危"                      # 两段 → 字段默认「状态」
            "\n===世界观揭示===\n- 灯盟十三坊｜按灯坊划分辖区")
    evos, revs = memory.parse_evolution_reveals(text)
    assert evos == [("陈更", "余额", "1700→0"), ("柳三更", "状态", "重伤垂危")]
    assert revs == [("灯盟十三坊", "按灯坊划分辖区")]
    evos2, revs2 = memory.parse_evolution_reveals("")   # 空不抛
    assert evos2 == [] and revs2 == []


# ---- 世界书追加分区 ----

def test_upsert_creates_section_and_is_idempotent(tmp_path):
    proj = _mk_proj(tmp_path)
    before = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    ents = [("柳三更", "人物", "灰袍灯客")]
    r1 = memory.upsert_worldbook_entries(proj, 4, ents, [])
    assert r1 == {"added": 1, "updated": 0, "skipped": 0, "evolved": 0, "proposed": 0}
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert "## 追加登记" in doc
    assert "- **柳三更**（人物）：灰袍灯客 ｜ 首见第4章" in doc
    assert doc.startswith(before.rstrip("\n"))   # 分区外原内容保持在前、未被改动

    # 重跑同一批：不再新增，行数不变
    lines_before = doc.count("\n")
    r2 = memory.upsert_worldbook_entries(proj, 4, ents, [])
    doc2 = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert r2["added"] == 0
    assert doc2.count("\n") == lines_before

    extra = memory.read_worldbook_additional(proj)
    assert "柳三更" in extra and "## 追加登记" not in extra


def test_upsert_updates_in_place_keeps_first_seen(tmp_path):
    proj = _mk_proj(tmp_path)
    memory.upsert_worldbook_entries(proj, 4, [("柳三更", "人物", "灰袍灯客")], [])
    r = memory.upsert_worldbook_entries(proj, 9, [("柳三更", "人物", "私灯党余孽")], [])
    assert r == {"added": 0, "updated": 1, "skipped": 0, "evolved": 0, "proposed": 0}
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert "私灯党余孽" in doc
    assert "首见第4章" in doc and "首见第9章" not in doc


def test_upsert_skips_names_already_in_worldbook(tmp_path):
    proj = _mk_proj(tmp_path, worldbook="## 世界书\n\n顾拾遗属灯盟保守派末代。\n")
    r = memory.upsert_worldbook_entries(
        proj, 4, [("顾拾遗", "人物", "重复登记")], [("灯盟", "千年传承")])
    assert r == {"added": 0, "updated": 0, "skipped": 2, "evolved": 0, "proposed": 0}
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert "追加登记" not in doc     # 全部跳过 → 不落分区


def test_worldbook_text_keeps_backflow_under_truncation(tmp_path):
    proj = _mk_proj(tmp_path, worldbook="## 世界书\n\n" + "正文占位。" * 400)
    memory.upsert_worldbook_entries(proj, 4, [("柳三更", "人物", "灰袍灯客")], [])
    out = project.worldbook_text(proj, max_chars=2000)
    assert "柳三更" in out and len(out) <= 2100
    assert "…（截断）" in out


# ---- 实体演进 / 世界观揭示 ----

def test_evolution_merges_in_place_keeps_desc_and_first_seen(tmp_path):
    proj = _mk_proj(tmp_path)
    memory.upsert_worldbook_entries(proj, 4, [("柳三更", "人物", "灰袍灯客")], [])
    r = memory.upsert_worldbook_entries(
        proj, 9, [], [], evolutions=[("柳三更", "余额", "500→300")])
    assert r == {"added": 0, "updated": 0, "skipped": 0, "evolved": 1, "proposed": 0}
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert "- **柳三更**（人物）：灰袍灯客；第9章 余额 500→300 ｜ 首见第4章" in doc
    # 同章重复演进不叠加（幂等键：名称+字段）
    r2 = memory.upsert_worldbook_entries(
        proj, 9, [], [], evolutions=[("柳三更", "余额", "500→300"),
                                     ("柳三更", "余额", "500→250")])
    assert r2["evolved"] == 1
    # 完全不认识的实体演进：不进分区也不进提案（无法判断）→ 跳过
    r3 = memory.upsert_worldbook_entries(proj, 9, [], [], evolutions=[("无名氏", "余额", "1→0")])
    assert r3 == {"added": 0, "updated": 0, "skipped": 1, "evolved": 0, "proposed": 0}


def test_evolution_of_manual_region_entity_writes_proposal(tmp_path):
    proj = _mk_proj(tmp_path, worldbook="## 世界书\n\n陈更是拾荒人，余额恒为1700。\n")
    before = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    r = memory.upsert_worldbook_entries(
        proj, 9, [], [], evolutions=[("陈更", "余额", "1700→0")])
    assert r == {"added": 0, "updated": 0, "skipped": 0, "evolved": 0, "proposed": 1}
    # 世界书本体逐字节不动（人工区条目不强改）
    assert project.read_file(os.path.join(proj, project.WORLDBOOK_PATH)) == before
    prop = project.read_file(os.path.join(proj, memory.PROPOSAL_PATH))
    assert "# 世界书修正提案" in prop and "## 第9章" in prop
    assert "[实体演进] 陈更｜余额｜1700→0" in prop
    # 再次演进：提案文件追加新章块，不覆盖旧内容
    memory.upsert_worldbook_entries(proj, 12, [], [], evolutions=[("陈更", "伤势", "骨折→已接骨")])
    prop2 = project.read_file(os.path.join(proj, memory.PROPOSAL_PATH))
    assert "## 第9章" in prop2 and "## 第12章" in prop2


def test_revelation_registered_as_worldview(tmp_path):
    proj = _mk_proj(tmp_path)
    r = memory.upsert_worldbook_entries(
        proj, 4, [], [], revelations=[("灯盟十三坊", "按灯坊划分辖区，每坊设执灯人一名")])
    assert r == {"added": 1, "updated": 0, "skipped": 0, "evolved": 0, "proposed": 0}
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    assert "- **灯盟十三坊**（世界观）：按灯坊划分辖区，每坊设执灯人一名 ｜ 首见第4章" in doc


# ---- 伏笔表增量补丁 ----

def test_foreshadow_add_and_dedupe(tmp_path):
    proj = _mk_proj(tmp_path)
    r = memory.apply_foreshadow_diff(proj, 4, [("柳三更的账本", "道具谜团", "第12章")], [])
    assert r == {"added": 1, "payoff": 0, "skipped": 0}
    text = project.read_file(project.get_tracking_path(proj, "伏笔"))
    assert "| 柳三更的账本 | 道具谜团 | 第4章 | 新设 | 第12章 | 反哺登记 |" in text
    # 重跑去重（含子串命中）
    r2 = memory.apply_foreshadow_diff(proj, 5, [("柳三更的账本", "道具谜团", "第12章")], [])
    assert r2 == {"added": 0, "payoff": 0, "skipped": 1}


def test_foreshadow_payoff_hits_and_misses(tmp_path):
    proj = _mk_proj(tmp_path)
    r = memory.apply_foreshadow_diff(
        proj, 4, [], ["妹妹透析费缺口1700元，由柳三更代付"])
    assert r == {"added": 0, "payoff": 1, "skipped": 0}
    text = project.read_file(project.get_tracking_path(proj, "伏笔"))
    assert "已回收" in text and "第4章回收（反哺）" in text
    # 已回收行不再命中；完全无关的回收描述不臆造
    r2 = memory.apply_foreshadow_diff(proj, 5, [], ["妹妹透析费缺口1700元"])
    assert r2["payoff"] == 0
    r3 = memory.apply_foreshadow_diff(proj, 5, [], ["根本不存在的伏笔"])
    assert r3 == {"added": 0, "payoff": 0, "skipped": 1}


def test_foreshadow_creates_table_when_absent(tmp_path):
    proj = str(tmp_path)
    project.write_file(project.get_tracking_path(proj, "伏笔"), "# 伏笔登记表\n")
    r = memory.apply_foreshadow_diff(proj, 4, [("新伏笔甲", "道具谜团", "")], [])
    assert r["added"] == 1
    text = project.read_file(project.get_tracking_path(proj, "伏笔"))
    assert "| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |" in text
    assert "新伏笔甲" in text
