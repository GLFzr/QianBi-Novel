# -*- coding: utf-8 -*-
"""C42/P3 写后维护四查回归（app/core/maintenance.py：角色/伏笔/弧线/读者认知）

覆盖：四查确定性输出（两次运行除 ts 外逐字相等）、逾期/待登记/需决断伏笔、
近3章零出场、新实体出「待确认卡片」而非自动写库（角色 sidecar/md 零变化）、
不占 cw["report"] 单槽（pipeline_state 字节不动）、fail-open、checklist 注入
文本四域齐全。全部离线零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core import maintenance as mt
from app.core import state as st

CH1 = "第1章 守夜\n\n陈更在灯阵前守夜，柳三更送来一枚铜哨，说是灯盟旧物。\n"
CH2 = "第2章 查账\n\n陈更查验账册，旧灯笼的刻痕在灯下微微发亮。\n"
CH3 = ("# 第3章 叩门\n\n"
       "陈更开门迎客，门槛上的霜还没有化。\n"
       "夜巡人立在灯阵外，夜巡人不说话，脚步声停在门前。陈更猜不透夜巡人来意。\n"
       "柳三更的铜哨在袖袋里发烫。\n"
       "“叩门令”三个字压得很低，可“叩门令”就是灯盟禁语。\n")

ROSTER_MD = ("# 角色状态追踪\n\n"
             "## 陈更\n- **当前身份**：执灯人\n- **状态变更记录**：（第1章：接印）\n\n"
             "## 柳三更\n- **当前身份**：灯客\n\n"
             "## 沈青梧\n- **当前身份**：灯盟监察\n\n")

GENRE_MD = "## 主要角色表\n- 沈青梧：灯盟监察。\n"

FORESHADOW_MD = ("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                 "|------|------|----------|------|----------|------|\n"
                 "| 旧灯笼的刻痕 | 道具谜团 | 第2章 | 已埋 | 第2章 | |\n"
                 "| 铜哨的回声 | 道具谜团 | 第3章 | 新设 | 第9章 | |\n")

OUTLINE3 = ("### 第 3 章：叩门\n"
            "- 核心事件：陈更开门迎客；门外脚步声止（夜巡人）\n"
            "- 章末钩子：门外人报出陈更的名字\n")

OUTLINE2 = ("### 第 2 章：查账\n"
            "- 核心事件：陈更查验账册\n"
            "- 章末钩子：账册里掉出一张“当票”\n")


def _mk_proj(tmp_path, with_ch3=True):
    proj = os.path.join(str(tmp_path), "p")
    for d in ("正文", "大纲", "追踪", "设定"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    chapters = [("第001章_守夜.md", CH1), ("第002章_查账.md", CH2)]
    if with_ch3:
        chapters.append(("第003章_叩门.md", CH3))
    for name, text in chapters:
        with open(os.path.join(proj, "正文", name), "w", encoding="utf-8") as f:
            f.write(text)
    for rel, text in (("追踪/角色状态.md", ROSTER_MD), ("设定/题材定位.md", GENRE_MD),
                      ("追踪/伏笔.md", FORESHADOW_MD),
                      ("大纲/细纲_第002章.md", OUTLINE2), ("大纲/细纲_第003章.md", OUTLINE3)):
        with open(os.path.join(proj, *rel.split("/")), "w", encoding="utf-8") as f:
            f.write(text)
    return proj


def _domain(report, name):
    return next(x for x in report["domains"] if x["domain"] == name)


# ---------------- 四查确定性 + 各域判据 ----------------

def test_four_checks_deterministic_and_sidecar(tmp_path):
    """两次运行除 ts 外逐字相等（纯确定性零 LLM）；sidecar 落盘可解析"""
    proj = _mk_proj(tmp_path)
    r1, r2 = mt.run_checks(proj, 3), mt.run_checks(proj, 3)
    assert r1 and r2
    for r in (r1, r2):
        r.pop("ts")
    assert r1 == r2, "四查必须确定性：同输入同输出"
    assert [d["domain"] for d in r1["domains"]] == ["角色", "伏笔", "弧线", "读者认知"]
    with open(mt.sidecar_path(proj, 3), encoding="utf-8") as f:
        sidecar = json.load(f)
    sidecar.pop("ts")
    assert sidecar == r1, "sidecar 与返回报告一致（独立通道产物）"


def test_character_domain_registration_and_stale(tmp_path):
    """本章出场带证据句；注册但近3章零出场（仅题材定位登记）→ 待交代名单"""
    proj = _mk_proj(tmp_path)
    rep = mt.run_checks(proj, 3)
    ch = _domain(rep, "角色")
    reg = {nm: ev for nm, ev in ch["本章出场"]}
    assert "陈更" in reg and "灯芯" not in reg["陈更"] and "开门" in reg["陈更"]
    assert "沈青梧" in ch["近3章零出场"], "只在题材定位登记、正文近3章未出现→零出场"
    assert "陈更" not in ch["近3章零出场"]


def test_foreshadow_overdue_and_register(tmp_path):
    """计划回收已逾期（第2章窗口，现章3）→ 提醒；本章新埋→待登记；已回收行不查"""
    proj = _mk_proj(tmp_path)
    items = _domain(mt.run_checks(proj, 3), "伏笔")["条目"]
    by_name = {i["伏笔"]: i for i in items}
    assert "已逾期" in by_name["旧灯笼的刻痕"]["计划"]
    assert "待登记" in by_name["铜哨的回声"]["动作"]
    assert "证据句" in by_name["铜哨的回声"], "证据句随条目输出（P1 引文底座对齐）"


def test_arc_hit_and_miss(tmp_path):
    """契约子句：逐字命中/实体共现入落点；无实体无逐字→未落点需人工复核"""
    proj = _mk_proj(tmp_path)
    arc = _domain(mt.run_checks(proj, 3), "弧线")
    covered = {c: how for c, how in arc["落点命中"]}
    assert covered.get("陈更开门迎客") == "逐字命中"
    assert "门外人报出陈更的名字" in covered, "实体共现（陈更）算落点"
    assert "门外脚步声止（夜巡人）" in arc["未落点子句(需人工复核)"]


def test_reader_domain_hook_and_new_terms(tmp_path):
    """上章钩子要素未承接→需检查衔接；本章新名词（前文未现、复现≥2）→登记"""
    proj = _mk_proj(tmp_path)
    rd = _domain(mt.run_checks(proj, 3), "读者认知")
    assert "未见承接要素" in rd["上章钩子回应"], "上章钩子「当票」未在第3章开头回应"
    assert "叩门令" in rd["本章新名词(需登记读者已知)"]
    assert "确定性轨不可判" in rd["读者误知"]


# ---------------- 待确认卡片：不自动写库 ----------------

def test_new_entity_pending_card_without_autowrite(tmp_path):
    """新实体「夜巡人」→ 待确认卡片；角色状态册（md+sidecar）零字节改动"""
    proj = _mk_proj(tmp_path)
    md_before = open(os.path.join(proj, "追踪", "角色状态.md"), encoding="utf-8").read()
    rep = mt.run_checks(proj, 3)
    cards = rep["cards"]
    kinds = {c["kind"] for c in cards}
    assert "新实体待登记" in kinds
    ent = next(c for c in cards
               if c["kind"] == "新实体待登记" and "夜巡人" in c["text"])
    assert ent["text"].startswith("「夜巡人」") and "待确认" in ent["action"]
    assert "夜巡人" in _domain(rep, "角色")["疑似未登记新实体"]
    assert open(os.path.join(proj, "追踪", "角色状态.md"), encoding="utf-8").read() == md_before
    chars = json.load(open(os.path.join(proj, "追踪", "角色状态.json"),
                           encoding="utf-8"))["characters"]
    assert "夜巡人" not in chars, "绝不自动写库：新实体不进角色 sidecar"


def test_cards_cover_foreshadow_and_arc_kinds(tmp_path):
    """逾期→伏笔计划提醒、新埋→伏笔待登记、零出场、弧线未落点、钩子衔接各成卡"""
    proj = _mk_proj(tmp_path)
    cards = mt.run_checks(proj, 3)["cards"]
    kinds = [c["kind"] for c in cards]
    assert "伏笔计划提醒" in kinds and "伏笔待登记" in kinds
    assert "角色零出场" in kinds and "弧线未落点" in kinds and "读者认知" in kinds
    assert all(c["ch"] == 3 and c["id"] for c in cards)


def test_no_state_pollution_report_slot_untouched(tmp_path):
    """独立通道纪律：run_checks 前后 pipeline_state.json 逐字节不变——
    不写 cw["report"]，也不新增任何 state 键（state.py 三共抢教训）"""
    proj = _mk_proj(tmp_path)
    state = {"stage": "writing", "current_chapter": 3,
             "cw": {"report": {"ts": "t0", "text": "sentinel"}}}
    st.save_state(proj, state)
    state_path = os.path.join(proj, "pipeline_state.json")
    raw_before = open(state_path, encoding="utf-8").read()
    mt.run_checks(proj, 3)
    assert open(state_path, encoding="utf-8").read() == raw_before
    assert st.load_state(proj)["cw"]["report"]["text"] == "sentinel"


# ---------------- fail-open 与边界 ----------------

def test_run_checks_fail_open(tmp_path):
    """空项目/缺目标章 → {} 且不落 sidecar（fail-open，绝不阻断定稿）"""
    empty = os.path.join(str(tmp_path), "empty")
    os.makedirs(empty)
    assert mt.run_checks(empty, 1) == {}
    proj_no_ch3 = _mk_proj(tmp_path, with_ch3=False)
    assert mt.run_checks(proj_no_ch3, 3) == {}
    assert not os.path.exists(mt.sidecar_path(proj_no_ch3, 3))


def test_checklist_covers_four_domains(tmp_path):
    """注入文本四域齐全、计数与四查一致（goink 式 system-reminder）"""
    proj = _mk_proj(tmp_path)
    rep = mt.run_checks(proj, 3)
    text = rep["checklist"]
    assert text.startswith("[system-reminder] 第3章已定稿")
    for head in ("1.角色", "2.伏笔", "3.弧线", "4.读者认知"):
        assert head in text
    assert "沈青梧" in text and "夜巡人" in text


# ---------------- 挂点钉（解线即红） ----------------

def test_wiring_hook_in_stages_finalize():
    """finalize 追踪落账区挂四查（fail-open）：恰一处，不占 cw["report"] 通道"""
    import app.core.stages as stages_mod
    src = open(stages_mod.__file__, encoding="utf-8").read()
    assert src.count("maintenance.run_checks(") == 1
    assert 'cw["report"] =' not in src and 'cw["report"][' not in src, \
        "四查产物绝不写 cw['report'] 单槽（三共抢教训）"
