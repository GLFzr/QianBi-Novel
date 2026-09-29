# -*- coding: utf-8 -*-
"""D4 写作规约反馈沉淀（app/core/writing_rules.py + state_card 规约段 + bridge 槽）

- add_rule 去重：归一化（NFKC+去空白+剥引号）精确/唯一包含相似 → 更新而非新增，
  歧义多命中不臆造合并；上限 100 条，超额按 hits 升序淘汰最久未命中者进归档
  （归档不删除）
- hits 命中计数：状态卡注入回写；disable 行为：停用不注入不计数，重新启用恢复
- 状态卡注入：第 3 段「写作规约(最高优先级)」（P0 之后、prio=0 永不裁——预算
  不够先裁设定不裁规约）；off 开关 writing.writing_rules_enabled（缺省 on）
  逐字对照：off 卡片与无规约 sidecar 卡片逐字节一致
- bridge 侧槽：addWritingRule——报告文本优先取【改写指令】、空文本拒收、
  去重合并、QML 报告区按钮钉扎
全部 tmp_path 真实文件，纯本地零 API。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project
from app.core import memory, state_card, writing_rules as wr


def _proj(tmp_path, name="书"):
    proj = str(tmp_path / name)
    for d in ("追踪", "正文", "大纲", "设定"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    return proj


def _rules_path(proj):
    return os.path.join(proj, "追踪", "写作规约.json")


def _read_rules(proj):
    with open(_rules_path(proj), encoding="utf-8") as f:
        return json.load(f)


# ---------------- 装载与去重 ----------------

def test_load_default_zero_side_effect(tmp_path):
    """缺失 sidecar → 空册，且读路径零副作用（不回写文件）"""
    proj = _proj(tmp_path)
    assert wr.load_rules(proj) == {"version": 1, "rules": [], "archived": [],
                                   "next_id": 1}
    assert not os.path.exists(_rules_path(proj))
    assert wr.card_items(proj) == []          # 无规约 → 零注入
    assert wr.rules_enabled(None) is True     # 开关缺省 on（cfg=None 亦 on）
    assert wr.rules_enabled({}) is True


def test_add_and_dedup_normalize(tmp_path):
    """add 去重：全半角引号/空差/句读归一化后相似 → 更新既有条目而非新增"""
    proj = _proj(tmp_path)
    r1 = wr.add_rule(proj, "不要写心理独白，用动作外化。", source_ch=5)
    assert r1["created"] is True and r1["rule"]["id"] == "R001"
    # 同义再沉淀：引号全半角互换 + 多余空白 + 句读差异 → 归一化相等
    r2 = wr.add_rule(proj, "“不要写心理独白” 用动作外化", source_ch=7)
    assert r2["created"] is False and r2["rule"]["id"] == "R001"
    data = _read_rules(proj)
    assert len(data["rules"]) == 1
    assert data["rules"][0]["content"] == "“不要写心理独白” 用动作外化"   # 以新表述为准
    assert data["rules"][0]["source_ch"] == 7                            # 来源章刷新
    assert data["rules"][0]["enabled"] is True
    # 唯一互相包含 → 同样合并；歧义多命中 → 不臆造，按新条目落库
    wr.add_rule(proj, "每章结尾必须留一个具体钩子")
    r3 = wr.add_rule(proj, "每章结尾必须留一个具体钩子，而且要可感知")
    assert r3["created"] is False                        # 唯一包含 → 更新
    assert len(wr.list_rules(proj)) == 2
    wr.add_rule(proj, "钩子必须具体可感知")               # 与既有互不包含 → 新条目
    wr.add_rule(proj, "可感知")                          # 同时被两条包含 → 歧义不合并
    assert len(wr.list_rules(proj)) == 4


def test_add_empty_and_length_cap(tmp_path):
    proj = _proj(tmp_path)
    assert wr.add_rule(proj, "   ") is None              # 空白 no-op
    assert not os.path.exists(_rules_path(proj))
    long_text = "规" * 500
    res = wr.add_rule(proj, long_text)
    assert len(res["rule"]["content"]) == wr.MAX_RULE_LEN   # 入库截断（一行一条纪律）


def test_enable_disable_roundtrip(tmp_path):
    """disable 行为：停用不注入不计数；重新启用恢复注入"""
    proj = _proj(tmp_path)
    rule = wr.add_rule(proj, "禁止出现现代物品", source_ch=2)["rule"]
    assert wr.set_enabled(proj, rule["id"], False)["enabled"] is False
    assert wr.card_items(proj) == []                     # 停用 → 不注入
    assert wr.card_items(proj) == []                     # 再构卡仍不注入
    assert _read_rules(proj)["rules"][0]["hits"] == 0    # 停用期间零计数
    assert wr.set_enabled(proj, rule["id"], True)["enabled"] is True
    assert wr.card_items(proj) == ["禁止出现现代物品"]
    assert wr.set_enabled(proj, "R999", True) is None    # 查无此 id → None


def test_cap_100_evict_to_archive(tmp_path):
    """100 条上限：超额按 hits 升序淘汰最久未命中者 → 归档（不删除）"""
    proj = _proj(tmp_path)
    for i in range(wr.MAX_RULES):
        wr.add_rule(proj, "规约条目%03d号：%s" % (i, "独" * i))   # 归一化互不相似
    assert len(wr.list_rules(proj)) == wr.MAX_RULES
    # 给 R005 攒 3 次命中、R010 攒 1 次（其余 0）——R005 最不该被淘汰
    wr.mark_hits(proj, ["R005"])
    wr.mark_hits(proj, ["R005"])
    wr.mark_hits(proj, ["R005", "R010"])
    res = wr.add_rule(proj, "全新的一条第101条规约")
    assert res["created"] is True and len(res["evicted"]) == 1
    active = wr.list_rules(proj)
    assert len(active) == wr.MAX_RULES
    assert "全新的一条第101条规约" in [r["content"] for r in active]
    evicted = res["evicted"][0]
    assert evicted["hits"] == 0                          # 淘汰的是 hits 最低者
    assert evicted["content"].startswith("规约条目") and "R005" != evicted["id"] \
        and "R010" != evicted["id"]
    store = _read_rules(proj)
    assert evicted in store["archived"]                  # 归档不删除
    assert evicted not in store["rules"]
    listed = wr.list_rules(proj, include_archived=True)
    assert evicted["content"] in [r["content"] for r in listed["archived"]]
    assert wr.mark_hits(proj, []) == 0                   # 空 id 集合 no-op


# ---------------- 状态卡注入 ----------------

def _seed_book(proj):
    """最小五章书 + 细纲/正则（供状态卡各栏有料；照 test_state_card 布景缩编）"""
    for n in range(1, 6):
        with open(os.path.join(proj, "正文", "第%03d章_过场.md" % n), "w",
                  encoding="utf-8") as f:
            f.write("# 第%d章\n沈孤灯在灯下翻看账册。" % n)
        memory.append_chapter_summary(proj, n, "过场%d" % n, "第%d章发生了一些事。" % n)
    with open(os.path.join(proj, "大纲", "细纲_第006章.md"), "w", encoding="utf-8") as f:
        f.write("#### 情节安排\n- 主线推进：沈孤灯当众验账，揭穿假账册。\n\n"
                "#### 结尾设定和钩子\n- 章尾钩子：门外传来三长两短的叩门声。\n\n"
                "- 字数目标：3000\n")
    with open(os.path.join(proj, "设定", "正则.md"), "w", encoding="utf-8") as f:
        f.write("# 正则\n\n- 规则：禁止出现现代物品与网络用语｜level: must｜scope: 全书\n")
    with open(os.path.join(proj, "追踪", "伏笔.md"), "w", encoding="utf-8") as f:
        f.write("| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                "|------|------|----------|------|----------|------|\n"
                "| 黑袍人的令牌 | 物 | 第1章 | 已埋 | 第3章 | 测试 |\n")


def test_state_card_injection_position_and_hits(tmp_path):
    """注入：第 3 段「写作规约(最高优先级)」（P0 之后、活跃伏笔之前）；hits 回写"""
    proj = _proj(tmp_path)
    _seed_book(proj)
    wr.add_rule(proj, "不要写心理独白，用动作外化", source_ch=5)
    wr.add_rule(proj, "每章结尾必须留一个具体钩子", source_ch=5)
    card, audit = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert audit == []                                   # 常规书远未到 12KB，零裁剪
    head, _, rest = card.partition("## 写作规约(最高优先级)")
    assert rest, "规约段必须在卡上"
    assert "不要写心理独白，用动作外化" in rest and "每章结尾必须留一个具体钩子" in rest
    assert rest.index("不要写心理独白") < rest.index("每章结尾")   # 入库序
    # 位置钉扎：P0 之后、活跃伏笔之前
    assert "## 下一章承诺" in head and head.index("## 下一章承诺") > head.index("## 当前位置")
    assert card.index("## 写作规约(最高优先级)") < card.index("## 活跃伏笔(作者真相)")
    # hits 回写：注入一次计一次
    data = _read_rules(proj)
    assert [r["hits"] for r in data["rules"]] == [1, 1]
    state_card.build_state_card(proj, 6, proj_io=project)
    assert [r["hits"] for r in _read_rules(proj)["rules"]] == [2, 2]


def test_state_card_rules_survive_budget_trim(tmp_path):
    """预算裁剪：规约段 prio=0 永不裁——小预算下按 P5→P1 裁设定不裁规约"""
    proj = _proj(tmp_path)
    _seed_book(proj)
    wr.add_rule(proj, "不要写心理独白，用动作外化")
    wr.add_rule(proj, "每章结尾必须留一个具体钩子")
    card, audit = state_card.build_state_card_detail(proj, 6, budget=500,
                                                     proj_io=project)
    assert len(card.encode("utf-8")) <= 500
    assert audit, "小预算必须触发裁剪"
    assert audit[0].startswith("裁剪 [近三章速记(读者已知)]")   # 裁剪序照旧 P5→P1
    assert "## 写作规约(最高优先级)" in card                    # 规约段永不丢
    assert "不要写心理独白" in card
    assert "## 近三章速记(读者已知)" not in card                # 最低价值段最先整栏让位


def test_state_card_off_switch_byte_identical(tmp_path):
    """off 逐字对照：writing_rules_enabled=False → 卡片与无规约 sidecar 逐字节一致"""
    proj = _proj(tmp_path)
    _seed_book(proj)
    wr.add_rule(proj, "不要写心理独白，用动作外化")
    wr.add_rule(proj, "每章结尾必须留一个具体钩子")
    off_cfg = {"writing": {"writing_rules_enabled": False}}
    card_off, audit_off = state_card.build_state_card_detail(proj, 6, proj_io=project,
                                                             cfg=off_cfg)
    os.remove(_rules_path(proj))                          # 无规约基线
    card_base, audit_base = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert card_off == card_base and audit_off == audit_base   # 逐字节对照
    # off 侧零计数：sidecar 已删不可验，用开关 on/off 同册再验一轮
    wr.add_rule(proj, "不要写心理独白，用动作外化")
    card_on, _ = state_card.build_state_card_detail(proj, 6, proj_io=project)
    card_off2, _ = state_card.build_state_card_detail(proj, 6, proj_io=project,
                                                      cfg=off_cfg)
    assert "## 写作规约(最高优先级)" in card_on
    assert "## 写作规约(最高优先级)" not in card_off2
    assert [r["hits"] for r in _read_rules(proj)["rules"]] == [1]      # off 不回写


def test_state_card_fail_open(tmp_path):
    """fail-open：sidecar 损坏 → 空段不炸卡；坏字段形态逐项丢弃"""
    proj = _proj(tmp_path)
    _seed_book(proj)
    with open(_rules_path(proj), "w", encoding="utf-8") as f:
        f.write("{not json")
    card, audit = state_card.build_state_card_detail(proj, 6, proj_io=project)
    assert audit == [] and "## 写作规约(最高优先级)" not in card
    with open(_rules_path(proj), "w", encoding="utf-8") as f:
        json.dump({"rules": [{"content": "好规约", "hits": "坏", "enabled": "x"},
                             {"content": ""}, "垃圾", None],
                   "archived": "坏", "next_id": "坏"}, f, ensure_ascii=False)
    assert wr.card_items(proj) == ["好规约"]              # 坏形态容忍，好条目存活
    wr.add_rule(proj, "另一条")                           # 坏 next_id 自愈补号
    data = _read_rules(proj)
    assert [r["id"] for r in data["rules"]] == ["R001", "R002"]


# ---------------- bridge 侧槽（addWritingRule） ----------------

class _Sig:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


_REPORT = ("- 结论：需调整（第3章心理独白过多）\n\n"
           "【改写指令】：删除大段心理独白，改用动作与对话外化情绪\n"
           "- 后续句请一并收敛")


def _slot_self(tmp_path, num=3):
    from app.ui import bridge as bmod
    fs = type("S", (), {})()
    fs.proj = str(tmp_path / "书")
    fs._cur_num = num
    fs.toast = _Sig()
    return fs, bmod


def test_bridge_slot_extracts_directive(tmp_path):
    """报告文本优先沉淀【改写指令】；来源章=当前章"""
    fs, bmod = _slot_self(tmp_path)
    bmod.Bridge.addWritingRule(fs, _REPORT)
    data = _read_rules(fs.proj)
    assert len(data["rules"]) == 1
    assert data["rules"][0]["content"] == "删除大段心理独白，改用动作与对话外化情绪"
    assert data["rules"][0]["source_ch"] == 3
    assert any(c[0] == "ok" for c in fs.toast.calls)


def test_bridge_slot_plain_text_and_empty(tmp_path):
    """无指令结构的普通反馈原文沉淀；空文本拒收零落盘"""
    fs, bmod = _slot_self(tmp_path)
    bmod.Bridge.addWritingRule(fs, "  战斗场面别写得太血腥  ")
    assert [r["content"] for r in _read_rules(fs.proj)["rules"]] == ["战斗场面别写得太血腥"]
    fs2, bmod2 = _slot_self(tmp_path / "空", num=0)
    bmod2.Bridge.addWritingRule(fs2, "   ")
    assert not os.path.exists(_rules_path(fs2.proj))
    assert any(c[0] == "warn" for c in fs2.toast.calls)


def test_bridge_slot_dedup_and_eviction_toast(tmp_path):
    """同义反馈二次沉淀=去重合并（ok 文案区分）；淘汰发生时补 info toast"""
    fs, bmod = _slot_self(tmp_path)
    bmod.Bridge.addWritingRule(fs, "【改写指令】：别用心理独白")
    bmod.Bridge.addWritingRule(fs, "【改写指令】：别  用  心理独白")   # 归一化相似
    data = _read_rules(fs.proj)
    assert len(data["rules"]) == 1
    assert data["rules"][0]["content"] == "别  用  心理独白"
    ok_texts = [c[1] for c in fs.toast.calls if c[0] == "ok"]
    assert any("去重合并" in t for t in ok_texts)
    for i in range(wr.MAX_RULES - 1):                    # 顶满上限触发淘汰
        wr.add_rule(fs.proj, "满员条目%03d号：%s" % (i, "独" * i))
    fs.toast.calls.clear()
    bmod.Bridge.addWritingRule(fs, "【改写指令】：触发淘汰的新反馈")
    info = [c for c in fs.toast.calls if c[0] == "info"]
    assert info and "归档" in info[0][1]
    assert len(_read_rules(fs.proj)["rules"]) == wr.MAX_RULES


def test_bridge_slot_qml_pinning():
    """QML 钉扎：CwDialogueDock 报告区「沉淀为规约」小按钮接线在场"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(root, "app", "ui", "qml", "components",
                           "CwDialogueDock.qml"), encoding="utf-8") as f:
        src = f.read()
    assert "沉淀为规约" in src
    assert "bridge.addWritingRule(bridge.cwReportText)" in src
    # 只许动反馈区局部：按钮必须落在主 Agent 报告区内（报告区注释之后、消息流之前）
    report_area = src[src.index("主 Agent 报告区"):src.index("消息流（转写）")]
    assert "沉淀为规约" in report_area
    # bridge 槽定义唯一且带 @Slot(str)
    import inspect
    from app.ui import bridge as bmod
    bsrc = inspect.getsource(bmod.Bridge)
    assert bsrc.count("def addWritingRule") == 1
    slot_src = inspect.getsource(bmod.Bridge.addWritingRule)
    assert "writing_rules.add_rule" in slot_src and "parse_supervisor_report" in slot_src
