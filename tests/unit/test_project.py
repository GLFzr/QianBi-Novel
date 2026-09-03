# -*- coding: utf-8 -*-
"""project：目录结构、章节列表、终稿锁定、字数统计、正则规则解析"""
import os

from app import project


def _make_proj(tmp_path, name="测试书"):
    return project.create_project(str(tmp_path), name)


def test_create_project_structure(tmp_path):
    proj = _make_proj(tmp_path)
    assert project.is_project(proj)
    for d in project.PROJECT_DIRS:
        assert os.path.isdir(os.path.join(proj, d))
    for rel in project.TRACKING_TEMPLATES:
        assert os.path.exists(os.path.join(proj, rel.replace("/", os.sep)))
    assert not project.is_project(str(tmp_path))  # 根目录不是项目


def test_chapter_filename_sanitizes_title():
    assert project.chapter_filename(7) == "第007章.md"
    # 清洗 ASCII 非法文件名字符 \ / : * ? " < > |（全角标点保留）
    assert project.chapter_filename(7, '风起/云涌:决战*终局') == "第007章_风起云涌决战终局.md"
    assert project.chapter_filename(8, "风起？云涌") == "第008章_风起？云涌.md"
    assert project.outline_filename(12) == "细纲_第012章.md"


def test_list_chapters_and_next(tmp_path):
    proj = _make_proj(tmp_path)
    project.write_file(project.get_chapter_path(proj, 1, "开局"), "正文一")
    project.write_file(project.get_chapter_path(proj, 2), "正文二")
    project.write_file(os.path.join(proj, "正文", "草稿.md"), "不应被识别")
    chapters = project.list_chapters(proj)
    assert [c[0] for c in chapters] == [1, 2]
    assert project.next_chapter_num(proj) == 3


def test_chapter_lock_lifecycle(tmp_path):
    proj = _make_proj(tmp_path)
    assert project.is_chapter_locked(proj, 1) is False
    project.set_chapter_locked(proj, 1, True)
    assert project.is_chapter_locked(proj, 1) is True
    assert project.attempt_unlock(proj, 1) is True
    assert project.is_chapter_locked(proj, 1) is False
    assert project.attempt_unlock(proj, 1) is False  # 未锁再解锁返回 False
    assert project.is_chapter_locked(proj, 0) is False  # 0 章号容错


def test_count_chars_ignores_whitespace_and_markup():
    assert project.count_chars("你 好**世界**\n# 标题") == 6


def test_regex_rules_parse_logic_semantics(tmp_path):
    proj = _make_proj(tmp_path)
    project.write_file(os.path.join(proj, "设定", "正则.md"),
                       "# 规则集\n- 不许出现现代词｜level：must｜scope：全书\n"
                       "- 对话占比宜在三成以上｜level：should｜scope：本章\n")
    rules = project.regex_rules(proj)
    assert len(rules) == 2
    assert rules[0]["level"] == "must" and rules[0]["scope"] == "全书"
    assert rules[1]["level"] == "should" and rules[1]["scope"] == "本章"
    # 字面正则语义：无行内反引号时取整行为 rule
    regex_mode = project.regex_rules(proj, semantics="regex")
    assert len(regex_mode) == 2 and regex_mode[0]["scope"] == "样本"


def test_regex_rules_multiline_block(tmp_path):
    """多行规则块：列表项起条目，续行并入；level/scope 整块查找，缺省 must"""
    proj = _make_proj(tmp_path)
    project.write_file(os.path.join(proj, "设定", "正则.md"),
                       "# 规则集\n"
                       "- 规则：主角每日点灯不得超过三次\n"
                       "  level：must\n"
                       "  scope：全书\n"
                       "  说明：超限必须写透支代价\n"
                       "\n"
                       "- 规则：对话占比宜在三成以上｜level：should｜scope：本章\n")
    rules = project.regex_rules(proj)
    assert len(rules) == 2
    assert rules[0]["level"] == "must" and rules[0]["scope"] == "全书"
    assert "透支代价" in rules[0]["rule"] and "level" not in rules[0]["rule"]
    assert rules[1]["level"] == "should" and rules[1]["scope"] == "本章"
    # 无 level 标注的块 → 缺省 must
    project.write_file(os.path.join(proj, "设定", "正则.md"), "- 金手指当日三次为限")
    assert project.regex_rules(proj)[0]["level"] == "must"


def test_regex_rules_disabled_entry_is_skipped(tmp_path):
    """｜disabled 是整条开关（A5 多行块改写曾把它连同旧行循环一起删掉）"""
    proj = _make_proj(tmp_path)
    project.write_file(os.path.join(proj, "设定", "正则.md"),
                       "# 规则集\n"
                       "- 不许出现现代词｜level：must\n"
                       "- 旧的叙述腔规则｜disabled\n"
                       "- 规则：多行块也要认停用标记\n"
                       "  ｜disabled\n"
                       "  说明：标记在中间行也算整条停用\n"
                       "- 规则：仍未停用的条目照常注入\n  level：should\n")
    rules = project.regex_rules(proj)
    assert [r["rule"] for r in rules] == ["不许出现现代词", "规则：仍未停用的条目照常注入"]
    assert rules[1]["level"] == "should"
    # 字面正则语义同样跳过（与旧实现一致）
    assert len(project.regex_rules(proj, semantics="regex")) == 2


def test_worldbook_text_section_budget_and_anchors(tmp_path):
    """分节预算：追加登记全留、规则节优先；锚点命中行挤进预算（无锚点则被截掉）"""
    proj = _make_proj(tmp_path)
    doc = (
        "## 世界书总述\n" + "总述填充。" * 60 + "\n"
        "### 1. 实体登记\n"
        "| 实体 | 类别 | 描述 |\n| --- | --- | --- |\n"
        "| **陈更** | 人物 | 执灯人学徒 |\n| **顾拾遗** | 人物 | 保守派执灯 |\n"
        "### 2. 规则与数值基准\n"
        "- 点灯每日以三次为限，超限反噬。\n"
        "### 3. 势力与地理\n" + "地理填充。" * 120 + "\n"
        "- 灯盟据点在北城，夜里只开一扇门。\n"
        "## 追加登记\n- **柳三更**（人物）：灰袍灯客 ｜ 首见第4章\n"
    )
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), doc)
    out = project.worldbook_text(proj, max_chars=700)
    assert "柳三更" in out                       # 反哺登记全留
    assert "点灯每日以三次为限" in out           # 规则节优先
    assert len(out) <= 780
    assert "灯盟据点在北城" not in out           # 预算不足时低优先节尾部被截
    out2 = project.worldbook_text(proj, max_chars=700, anchors=["灯盟据点"])
    assert "灯盟据点在北城" in out2              # 锚点命中行挤进预算


def test_worldbook_anchors_from_roster_and_outline(tmp_path):
    """锚点取材（真实结构）：角色表表格行 + 细纲「出场顺序」+ 已知名在情节点命中"""
    proj = _make_proj(tmp_path)
    project.write_file(os.path.join(proj, "设定", "题材定位.md"),
                       "# 题材定位\n\n## 主要角色表\n\n"
                       "| 角色 | 定位 | 一句话动机 |\n| --- | --- | --- |\n"
                       "| 陈更 | 主角 | 查清父亲死因 |\n| 顾拾遗 | 灯盟 | 守住规矩 |\n"
                       "## 世界观\n\n无关内容。\n")
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH),
                       "## 世界书\n\n### 1. 实体登记\n\n"
                       "- **柳三更**（人物）：灰袍灯客 ｜ 首见第4章\n\n"
                       "### 北城当铺\n\n- 类型：据点\n")
    project.write_file(project.get_outline_path(proj, 4),
                       "## 细纲第4章 · 当票\n\n#### 人物关系和出场顺序\n\n"
                       "- 出场顺序：陈更、柳三更\n\n"
                       "#### 情节点序列\n\n1. 顾拾遗在北城当铺烧毁当票\n")
    names = project.worldbook_anchors(proj, 4)
    assert "陈更" in names and "顾拾遗" in names and "柳三更" in names
    assert "北城当铺" in names          # 真实细纲没有「角色：」字段，靠已知名命中
    for label in ("主要角色表", "实体登记", "出场顺序", "类型", "情节点", "人物",
                  "世界观", "角色", "定位"):
        assert label not in names, f"栏目标签污染锚点：{label}"
    assert project.worldbook_anchors(proj, 0) == ["陈更", "顾拾遗"]   # 无章号只回角色表


def test_idea_info_and_planned_chapters(tmp_path):
    proj = _make_proj(tmp_path)
    project.write_idea_info(proj, "都市脑洞", "番茄", "一个能改命的笔记本", 60)
    info = project.read_idea_info(proj)
    assert info["genre"] == "都市脑洞"
    assert info["total_words_wan"] == 60
    assert project.planned_chapters(proj, chapter_word_target=3000) == 200


def test_split_worldbook_product_regex_heading_levels():
    """回归：模型把正则写成「# 正则（逻辑约束规则集）」时旧实现整段不认 → 规则集恒空"""
    wb, rg = project.split_worldbook_product(
        "# 世界书\n力量体系…\n\n# 正则（逻辑约束规则集）\n- 规则：A｜level：must｜scope：全书")
    assert rg.startswith("# 正则") and "正则" not in wb and "力量体系" in wb
    wb2, rg2 = project.split_worldbook_product("## 世界书\n只有世界书")
    assert rg2 == "" and wb2 == "## 世界书\n只有世界书"


def test_split_worldbook_product_keeps_subsections_and_tail():
    """正则段内的 ### 属本段；正则段之后的小节拼回世界书（两半分文件落盘，否则整节消失）"""
    wb, rg = project.split_worldbook_product(
        "## 世界书\n力量体系…\n\n## 正则\n- 规则：A｜level：must\n\n### 文风约束\n"
        "- 规则：B｜level：should\n\n## 地理\n北城。\n")
    assert [l for l in rg.splitlines() if l.startswith("#")] == ["## 正则", "### 文风约束"]
    assert "规则：B" in rg and "北城" not in rg
    assert "## 地理\n北城。" in wb and "正则" not in wb
