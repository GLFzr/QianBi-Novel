# -*- coding: utf-8 -*-
"""wb：世界书条目化解析与按章激活（W1 装配内核）"""
import os

from app import project, wb

DOC = """## 世界书

### 1. 实体登记

| 实体名称 | 类型 | 描述 |
|---------|------|------|
| **陈更** | 人物 | 当铺学徒，能改写当票 |
| **柳三更** | 人物 | 灰袍灯客，夜里只点一盏 |

### 2. 规则与数值基准

- **点灯上限**：每日三次，超限反噬。
- **当票铁律**：改写过的当票不得再次改写。

### 3. 地理

- 北城：灯盟据点所在，夜里只开一扇门。
- 南城：黑市，当票流通的灰色地带。

## 追加登记

> 本分区由千笔自动维护（剧情反哺登记）。

- **灯盟**（势力）：守夜人组织，规矩大于人情 ｜ 首见第4章
"""


def _proj(tmp_path, doc=DOC, name="测试书"):
    proj = project.create_project(str(tmp_path), name)
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), doc)
    return proj


def _by_name(entries):
    return {e.name: e for e in entries if e.name}


def _append_section(doc, extra):
    """把附加小节插在「## 追加登记」之前（拼在文末会被当成反哺区的子节）"""
    head, tail = doc.split("## 追加登记")
    return head + extra + "## 追加登记" + tail


# ---------- parse：四种现存语法 + 跨语法合并 ----------

def test_parse_covers_four_real_worldbook_syntaxes():
    by = _by_name(wb.parse(DOC))
    assert set(["陈更", "柳三更", "点灯上限", "当票铁律", "北城", "南城", "灯盟"]) <= set(by)
    assert by["陈更"].section == "实体登记" and by["陈更"].kind == "entity"
    assert by["点灯上限"].section == "规则与数值基准" and by["点灯上限"].kind == "rule"
    assert by["灯盟"].section == "追加登记" and by["灯盟"].is_backflow
    assert by["灯盟"].meta["first_seen"] == 4
    # 表格容器仍是「节」：表头与分隔行留在节骨架，不被当成条目
    prose = [e for e in wb.parse(DOC) if e.kind == "prose"]
    heads = {e.section for e in prose}
    assert "实体登记" in heads and "追加登记" in heads
    reg = next(e for e in prose if e.section == "实体登记")
    assert "| 实体名称 | 类型 | 描述 |" in reg.body and "|---" in reg.body
    assert "陈更" not in reg.body                               # 数据行是条目，不是骨架


def test_parse_heading_entry_keeps_attribute_lines_together():
    doc = "## 世界书\n\n### 柳三更\n\n- 身份：灰袍灯客\n- 弱点：见不得空灯\n"
    entries = wb.parse(doc)
    by = _by_name(entries)
    assert "柳三更" in by and by["柳三更"].kind == "entity"
    assert "见不得空灯" in by["柳三更"].body      # 属性行属于条目本身，不散回节里


def test_parse_heading_entry_folds_recurring_attribute_fields():
    """字段名（约束）跨标题复现 → 属性行属于条目，不许切成只剩标题的空骨架"""
    doc = ("# 世界书\n\n## 实体登记\n\n### 陈更\n- 身份：当铺学徒，逆命者\n"
           "- 约束：不能说出改写过的日期\n- 声口：短句，从不解释\n\n"
           "### 柳三更\n- 身份：掌柜之女\n- 约束：只信账本不信人\n")
    by = _by_name(wb.parse(doc))
    assert "约束" not in by and "声口" not in by
    assert "不能说出改写过的日期" in by["陈更"].body and "只信账本不信人" in by["柳三更"].body
    assert by["陈更"].kind == "entity" and by["陈更"].section == "实体登记"


def test_parse_bold_registration_with_label_suffix_is_an_entry():
    """"清账规则"这类以标签后缀结尾的登记名必须是独立条目（否则保底预算管不到它）"""
    doc = "## 世界书\n\n## 追加登记\n\n- **清账规则**（规则）：子时不能说谎 ｜ 首见第2章\n"
    by = _by_name(wb.parse(doc))
    assert "清账规则" in by and by["清账规则"].is_backflow
    assert wb.trigger(by["清账规则"], 3)[0] == wb.P_RECENT


def test_parse_merges_same_name_across_syntaxes():
    doc = ("## 世界书\n\n### 实体登记\n\n"
           "| 实体名称 | 类型 |\n|---|---|\n| **顾拾遗** | 执灯 |\n\n"
           "- **顾拾遗**：保守派，守规矩三十年\n")
    entries = [e for e in wb.parse(doc) if e.name == "顾拾遗"]
    assert len(entries) == 1                      # 归一化名 + 同节 → 合并成一条
    assert "守规矩三十年" in entries[0].body and "| **顾拾遗** | 执灯 |" in entries[0].body


def test_trigger_markers_are_read_and_stripped_from_render():
    doc = ("## 世界书\n\n### 术语\n\n"
           "- **三更灯灭**：撤退暗号 [关键词：灯灭、暗号]\n"
           "- **老约定**：灯盟立盟之本 [常驻]\n"
           "- **拓宽条目**：第6-10章新增设定 [第6-10章]\n")
    by = _by_name(wb.parse(doc))
    assert by["三更灯灭"].meta["keywords"] == ["灯灭", "暗号"]
    assert by["老约定"].meta["constant"] is True
    assert by["拓宽条目"].meta["range"] == (6, 10)
    assert all("[" not in e.body for e in by.values())     # 标记只喂装配层，不进 prompt


# ---------- assemble：快速路径不变式 ----------

def test_fast_path_returns_file_verbatim(tmp_path):
    proj = _proj(tmp_path)
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    out = wb.assemble(proj, num=1, budget=len(doc), doc=doc)
    assert out["text"] == doc
    assert out["dropped"] == [] and len(out["activated"]) == len(wb.parse(doc))
    for a in out["activated"]:
        assert a["why"] == "全文"
    # 装得下就逐字原样（老书零变化的硬保证）；装不下才走装配，且恒不超预算
    big = _append_section(DOC, "### 4. 长史\n\n" + "旧城旧事，无可奉告。" * 60 + "\n")
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), big)
    assert wb.assemble(proj, num=1, budget=len(big))["text"] == big
    assert wb.assemble(proj, num=1, budget=len(big) + 999)["text"] == big
    for budget in range(60, len(big) + 40, 17):
        assert len(wb.assemble(proj, num=1, budget=budget)["text"]) <= budget + 1


def test_empty_worldbook_falls_back_to_placeholder(tmp_path):
    proj = _proj(tmp_path, doc="   \n")
    r = wb.assemble(proj, num=1, budget=500)
    assert r["text"] == wb.EMPTY_PLACEHOLDER and r["activated"] == []


# ---------- assemble：档位与预算 ----------

def test_activation_priority_constant_hit_weight(tmp_path):
    """档位决定入预算顺序：常驻规则 ＞ 实体（节权重 4）＞ 长史（节权重 5）；预算不被撑破"""
    doc = _append_section(DOC, "### 4. 长史\n\n" + "旧城旧事，无可奉告。" * 60 + "\n")
    proj = _proj(tmp_path, doc=doc)
    r = wb.assemble(proj, num=1, budget=300, anchors=[], doc=doc)
    assert len(r["text"]) <= 301
    assert "- **点灯上限**：每日三次，超限反噬。\n" in r["text"]      # 常驻节全文先入
    assert "- **当票铁律**：改写过的当票不得再次改写。\n" in r["text"]
    assert "柳三更" in r["text"]                                   # 实体条目排在兜底档前
    assert "旧城旧事" not in r["text"]                              # 最低档位整节被挤掉
    assert "### 4. 长史" not in r["text"]                            # 条目没进来，节标题也不留空壳
    whys = {a["name"]: a["why"] for a in r["activated"]}
    assert whys["点灯上限"] == "常驻" and "长史" not in whys
    # 预算富余时兜底档只能以节选形式吃剩下的额度
    rich = wb.assemble(proj, num=1, budget=400, anchors=[], doc=doc)
    assert {a["name"]: a["why"] for a in rich["activated"]}["长史"].endswith("·节选")


TWO_TOWN = ("## 世界书\n\n### 地理\n\n"
            "- 北城：灯盟据点，夜里只开一扇门。\n- 南城：黑市，当票流通的灰色地带。\n")


def test_chapter_hit_outranks_plain_section(tmp_path):
    """预算只够一个条目时：命中本章细纲的（文件序在后）挤掉未命中的（文件序在前）"""
    proj = _proj(tmp_path, doc=TWO_TOWN)
    project.write_file(project.get_outline_path(proj, 5),
                       "## 细纲第5章\n\n#### 人物关系和出场顺序\n\n- 出场顺序：南城\n")
    blind = wb.assemble(proj, num=1, budget=45, anchors=[], doc=TWO_TOWN)["text"]
    assert "北城" in blind and "南城" not in blind
    hit = wb.assemble(proj, num=5, budget=45, anchors=[], doc=TWO_TOWN)["text"]
    assert "南城" in hit and "北城" not in hit
    whys = {a["name"]: a["why"] for a in wb.assemble(
        proj, num=5, budget=45, anchors=[], doc=TWO_TOWN)["activated"]}
    assert whys["南城"].startswith("本章命中")


def test_shell_passes_num_to_kernel(tmp_path):
    """兼容壳必须真的把 num 传下去（A5 教训：参数传了等于没传的断链）"""
    proj = _proj(tmp_path, doc=TWO_TOWN)
    project.write_file(project.get_outline_path(proj, 5),
                       "## 细纲第5章\n\n#### 人物关系和出场顺序\n\n- 出场顺序：南城\n")
    assert "南城" in project.worldbook_text(proj, 45, anchors=[], num=5)
    assert "南城" not in project.worldbook_text(proj, 45, anchors=[], num=1)


GROW = """## 世界书

### 实体登记

- 陈更：当铺学徒，能改写当票，夜里睡不着就对着灯反复练那一笔改字的手法。

### 拓宽·第6-10章

- 旧债：柳三更手里有当铺三年前的凭据。
"""


def test_grow_batch_ranks_as_recent_registration(tmp_path):
    """TUI 的「### 拓宽·第N-M章」是近章登记档，不许按最低节权重垫底（自动档不比 TUI 丢上下文）"""
    by = _by_name(wb.parse(GROW))
    assert wb.trigger(by["旧债"], 40)[0] == wb.P_RECENT
    assert wb.trigger(by["陈更"], 40)[0] > wb.P_RECENT
    proj = _proj(tmp_path, doc=GROW)
    out = wb.assemble(proj, num=40, budget=60, anchors=[], doc=GROW)["text"]
    assert "旧债" in out and "陈更" not in out


def test_trigger_bands(tmp_path):
    """档位口径：常驻 0 ＜ 本章命中 1 ＜ 近章登记 2 ＜ 节权重 3/4/5"""
    by = _by_name(wb.parse(DOC))
    assert wb.trigger(by["点灯上限"], 9) == (wb.P_CONSTANT, "常驻")
    assert wb.trigger(by["北城"], 9) == (wb.P_SECTION + 2, "节权重")     # 地理节权重最低
    assert wb.trigger(by["北城"], 9, "北城夜里戒严") [0] == wb.P_HIT
    assert wb.trigger(by["灯盟"], 5)[0] == wb.P_RECENT                   # 首见第4章在 5 章近窗
    assert wb.trigger(by["灯盟"], 40)[0] == wb.P_RECENT                  # 仍属反哺登记区
    assert wb.trigger(by["柳三更"], 9, "", anchors=["柳三更"])[0] == wb.P_HIT


def test_backflow_registration_is_never_squeezed_out(tmp_path):
    """反哺登记有保底预算：登记描述逐字在场，节选的只能是大块填充"""
    doc = _append_section(DOC, "### 5. 杂记\n\n" + "无关填充。" * 200 + "\n")
    proj = _proj(tmp_path, doc=doc)
    for budget in (150, 300, 450, 600):
        r = wb.assemble(proj, num=9, budget=budget, anchors=[], doc=doc)
        assert len(r["text"]) <= budget + 1
        assert "- **灯盟**（势力）：守夜人组织，规矩大于人情 ｜ 首见第4章" in r["text"]
        assert "追加登记" in {a["name"] for a in r["activated"]}
    # 保底之外仍有额度时，兜底档才允许被节选
    rich = wb.assemble(proj, num=9, budget=600, anchors=[], doc=doc)["text"]
    assert "无关填充" in rich and "截断" in rich


def test_backflow_reserve_covers_the_section_skeleton(tmp_path):
    """整本书只剩反哺区：预算 60（连标题都装不满）时登记仍在场、描述没被节选"""
    doc = "## 追加登记\n\n- **灯盟**（势力）：守夜人组织，规矩大于人情 ｜ 首见第4章\n"
    proj = _proj(tmp_path, doc=doc)
    out = wb.assemble(proj, num=9, budget=60, anchors=[], doc=doc)["text"]
    assert "灯盟" in out and "节选" not in out and "截断" not in out


def test_dropped_lists_what_never_made_the_cut(tmp_path):
    doc = _append_section(DOC, "### 4. 长史\n\n- 旧城：无可奉告。\n\n" + "填充。" * 200 + "\n")
    proj = _proj(tmp_path, doc=doc)
    r = wb.assemble(proj, num=1, budget=400, anchors=[], doc=doc)
    names = {a["name"] for a in r["activated"]}
    assert r["dropped"] and not (names & {d["name"] for d in r["dropped"]})
    assert {"点灯上限", "陈更"} <= names


def test_markdown_table_survives_truncation(tmp_path):
    """截断后表头与首行数据必须仍相邻（空行会把表格截成两段文本）"""
    proj = _proj(tmp_path)
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    out = wb.assemble(proj, num=1, budget=150, anchors=[], doc=doc)["text"]
    assert "| **陈更** |" not in out                          # 预算太小时整节进不来
    out = wb.assemble(proj, num=1, budget=230, anchors=[], doc=doc)["text"]
    lines = [l for l in out.splitlines() if l.strip()]
    i = next(k for k, l in enumerate(lines) if l.startswith("| 实体名称"))
    assert lines[i + 1].startswith("|---")
    assert lines[i + 2].startswith("| **")


def test_no_orphan_heading_or_empty_table_across_budgets(tmp_path):
    """回归：节骨架只在条目进得来时才占额度（曾出现只剩标题 / 只剩表头的空节）"""
    proj = _proj(tmp_path)
    doc = _append_section(DOC, "### 4. 长史\n\n" + "旧城旧事，无可奉告。" * 60 + "\n")
    for budget in range(120, 620, 20):
        out = wb.assemble(proj, num=1, budget=budget, anchors=[], doc=doc)["text"]
        assert len(out) <= budget + 1
        lines = [l for l in out.splitlines() if l.strip()]
        for k, l in enumerate(lines):
            if l.startswith("|") and k + 1 < len(lines) and lines[k + 1].startswith("|--"):
                assert k + 2 < len(lines) and lines[k + 2].startswith("| **"), budget
            if l.startswith("#") and k + 1 < len(lines) and lines[k + 1].startswith("| 实体"):
                assert k + 2 < len(lines) and lines[k + 2].startswith("|--"), budget
        for head in ("### 1. 实体登记", "### 2. 规则与数值基准", "### 3. 地理", "### 4. 长史"):
            if head in out:
                rest = out.split(head, 1)[1].split("\n#", 1)[0]
                assert rest.strip(" \n|—-"), (budget, head)   # 标题下不能是空的


def test_trailing_bare_heading_is_not_a_section(tmp_path):
    """回归（真书取证）：结尾裸「##」残段既不是节，也不许以空壳标题混进激活视图"""
    doc = DOC.rstrip("\n") + "\n\n---\n\n##\n"
    proj = _proj(tmp_path, doc=doc)
    assert not [e for e in wb.parse(doc) if e.body.strip() == "##"]
    for budget in (300, 600):
        out = wb.assemble(proj, num=1, budget=budget, anchors=[], doc=doc)["text"]
        assert not [l for l in out.splitlines() if l.strip() == "#"], budget


NESTED = ("## 世界书\n\n## 1. 实体登记\n\n### 人物\n\n- 陈更：当铺学徒，能改写当票。\n\n"
          "### 地点\n\n- 北城：灯盟据点，夜里只开一扇门。\n")


def test_container_heading_never_enters_alone(tmp_path):
    """容器节（内容全在子节）不许单独吃预算：只剩一个空标题＝空壳"""
    proj = _proj(tmp_path, doc=NESTED)
    for budget in range(40, 200, 10):
        out = wb.assemble(proj, num=1, budget=budget, anchors=[], doc=NESTED)["text"]
        assert len(out) <= budget + 1
        if "## 1. 实体登记" in out:
            assert "陈更" in out or "北城" in out, budget


def test_preset_can_override_worldbook_budget(tmp_path):
    proj = _proj(tmp_path)
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    preset = {"worldbook_budget": {"prose": 120, "*": 400}}
    assert wb._budget_for(preset, "prose", 2000) == 120
    assert wb._budget_for(preset, "review", 2000) == 400
    assert wb._budget_for(None, "prose", 2000) == 2000
    r = wb.assemble(proj, num=1, budget=2000, preset=preset, phase="prose", doc=doc)
    assert r["budget"] == 120 and len(r["text"]) <= 121 and r["phase"] == "prose"


# ---------- 快照要的标识：id 稳定、content_hash 随内容变 ----------

def test_entry_id_stable_and_hash_tracks_content():
    a = _by_name(wb.parse(DOC))["陈更"]
    b = _by_name(wb.parse(DOC.replace("当铺学徒，能改写当票", "当铺学徒，能改当票")))["陈更"]
    assert a.id == b.id and a.content_hash != b.content_hash


def test_worldbook_text_shell_matches_kernel(tmp_path):
    proj = _proj(tmp_path)
    doc = project.read_file(os.path.join(proj, project.WORLDBOOK_PATH))
    for budget in (len(doc), 5000, 300, 1):
        assert project.worldbook_text(proj, budget, anchors=[]) == \
            wb.assemble(proj, budget=budget, anchors=[], doc=doc)["text"]
    assert project.worldbook_text(proj, 300, anchors=[]).startswith("## 世界书")
