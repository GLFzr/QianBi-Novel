# -*- coding: utf-8 -*-
"""外部文档导入（#9）：只拆实有 + 确认前零副作用 + 落点写法不破坏既有产物

两条作者定的硬约束，各自都有机器兜底，测试就是打这两条：
1. 「只拆真实存在的部分」——未验真的条目默认不勾选，且原因可读；
2. 「导入前预览映射」——不勾选即一个字节都不写；已有章节绝不覆盖。
"""
import os

import pytest

from app import importdoc, project, wb


SRC = """《当铺》设定集

当铺收的不是东西，是时间。当票上写的期限一过，物归原主，人归回。
掌柜陈更今年二十三岁，左手少一指，从不亲自收当。

主角不得凭空变强，每次改命必须索回等价代价。
每月只能点灯三次，第四次灯灭即人灭。

第12章 赎票
陈更把当票按在柜台上，声音很轻：「过期了。」
门外的人没有动，灯笼里的火苗忽然矮了半寸。
"""

PRODUCT = """===核心设定===
当铺收的不是东西，是时间。当票上写的期限一过，物归原主，人归回。

===世界书===
- 陈更（人物）：当铺掌柜，左手少一指，从不亲自收当
- 当铺（地点）：收时间的当铺
引证：掌柜陈更今年二十三岁，左手少一指，从不亲自收当

===正则===
- 每月只能点灯三次，第四次灯灭即人灭｜level：must｜scope：全书
引证：每月只能点灯三次，第四次灯灭即人灭

===大纲===
（无）

===细纲 第3章===
（无）

===正文 第12章===
第12章 赎票
陈更把当票按在柜台上，声音很轻：「过期了。」
门外的人没有动，灯笼里的火苗忽然矮了半寸。

===伏笔===
（无）

===角色状态===
- 陈更：当铺掌柜，左手少一指
引证：掌柜陈更今年二十三岁，左手少一指
"""


@pytest.fixture
def proj(tmp_path):
    p = str(tmp_path)
    project.create_project(p, "书")
    return os.path.join(p, "书")


def _read(proj, rel):
    return project.read_file(os.path.join(proj, rel))


def _plans(proj, product=PRODUCT, source=SRC):
    return importdoc.annotate(importdoc.parse_product(product), source, proj)


# ---------------------------------------------------------------- 读文档

def test_read_document_handles_gb18030(tmp_path):
    f = tmp_path / "稿.txt"
    f.write_bytes("当铺收的不是东西，是时间。".encode("gb18030"))
    text, err = importdoc.read_document(str(f))
    assert err == "" and "当铺收的不是东西" in text


def test_read_document_reports_unreadable(tmp_path):
    f = tmp_path / "坏.txt"
    f.write_bytes(b"\xff\xfe\x00\x00\x00garbage")
    text, err = importdoc.read_document(str(f))
    assert text == "" and err


def test_normalize_path_from_file_url():
    got = importdoc.normalize_path("file:///G:/ai/%E9%85%92%E9%A6%86/%E7%A8%BF.txt")
    assert got.endswith(os.path.join("酒馆", "稿.txt"))


# ---------------------------------------------------------------- 切段

def test_split_chunks_prefers_paragraph_break():
    doc = "甲" * 500 + "\n\n" + "乙" * 4000
    chunks, covered = importdoc.split_chunks(doc, 1000, 8)
    assert covered == len(doc)
    assert all(c in doc for c in chunks)
    assert len(chunks) > 1 and chunks[0].endswith("甲" * 500)


def test_split_chunks_caps_and_reports_coverage():
    doc = "字" * 70000
    chunks, covered = importdoc.split_chunks(doc, 30000, 2)
    assert len(chunks) == 2 and covered == 60000      # 少解析的 1 万字必须报出来


# ---------------------------------------------------------------- 拆解与验真

def test_parse_product_strips_quotes_and_skips_none():
    items = importdoc.parse_product(PRODUCT)
    keys = {(i["key"], i["num"]) for i in items}
    assert ("outline", None) not in keys              # （无）不落成条目
    assert ("outline_ch", None) not in keys
    assert ("prose", 12) in keys
    core = next(i for i in items if i["key"] == "core")
    assert "引证" not in core["content"]


def test_parse_product_fills_rule_fields():
    it = next(i for i in importdoc.parse_product(
        "===正则===\n- 不得出现三连感叹\n引证：不得出现三连感叹") if i["key"] == "regex")
    assert "level：must" in it["content"] and "scope：全书" in it["content"]


def test_chapter_section_without_number_is_dropped():
    """章号定不出来就没法落点——宁可不导，也不乱建一个文件"""
    items = importdoc.parse_product("===正文===\n陈更把当票按在柜台上\n引证：陈更把当票按在柜台上")
    assert items == []


def test_annotate_marks_fabricated_prose_untrusted(proj):
    fake = PRODUCT.replace("陈更把当票按在柜台上，声音很轻：「过期了。」",
                           "陈更掏出火箭筒，一炮轰开了南天门，从此纵横天下无人能敌。")
    plans = _plans(proj, fake)
    prose = next(p for p in plans if p["key"] == "prose")
    assert prose["trust"] is False and prose["checked"] is False
    assert "逐字" in prose["reason"]


def test_annotate_marks_fake_quote_untrusted(proj):
    fake = PRODUCT.replace("引证：每月只能点灯三次，第四次灯灭即人灭",
                           "引证：每月只能喝三次奶茶，第四次胖十斤")
    plans = _plans(proj, fake)
    rg = next(p for p in plans if p["key"] == "regex")
    assert rg["trust"] is False and rg["quotesOk"] == 0 and rg["quotesTotal"] == 1


def test_annotate_trusts_real_excerpts(proj):
    plans = _plans(proj)
    assert all(p["trust"] for p in plans), [p["reason"] for p in plans if not p["trust"]]
    assert all(p["checked"] for p in plans)


def test_missing_slots_are_listed(proj):
    missing = {m["key"] for m in importdoc.missing_slots(_plans(proj))}
    assert {"outline", "outline_ch", "foreshadow"} <= missing
    assert "prose" not in missing


def test_existing_chapter_maps_to_its_own_file(proj):
    project.write_file(os.path.join(proj, "正文", "第012章_旧名.md"), "已有正文\n")
    plans = _plans(proj)
    prose = next(p for p in plans if p["key"] == "prose")
    assert prose["target"].endswith("第012章_旧名.md")
    assert prose["exists"] is True


def test_merge_items_across_chunks():
    a = importdoc.parse_product("===正文 第1章===\n前半段原文照抄\n引证：前半段原文照抄")
    b = importdoc.parse_product("===正文 第1章===\n后半段原文照抄\n引证：后半段原文照抄")
    merged = importdoc.merge_items([a, b])
    assert len(merged) == 1 and len(merged[0]["quotes"]) == 2
    assert "前半段" in merged[0]["content"] and "后半段" in merged[0]["content"]


# ---------------------------------------------------------------- 落盘

def test_unchecked_plans_touch_nothing(proj):
    before = {f: _read(proj, f) for f in
              ["设定/题材定位.md", "设定/正则.md", "设定/世界书.md", "追踪/角色状态.md"]}
    plans = _plans(proj)
    for p in plans:
        p["checked"] = False
    r = importdoc.apply_import(proj, plans, "设定集.txt")
    assert r["written"] == []
    assert {f: _read(proj, f) for f in before} == before


def test_section_import_appends_under_import_heading(proj):
    r = importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    doc = _read(proj, "设定/题材定位.md")
    assert "## 导入·设定集.txt" in doc
    assert "当铺收的不是东西，是时间" in doc
    assert r["written"] and not r["skipped"]


def test_chapter_import_creates_file_and_never_overwrites(proj):
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    assert os.path.isfile(os.path.join(proj, "正文", "第012章_赎票.md"))

    again = importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    assert any("未覆盖" in s[1] for s in again["skipped"])
    assert not again["written"]
    assert os.listdir(os.path.join(proj, "正文")) == ["第012章_赎票.md"]


def test_regex_import_is_parseable_and_idempotent(proj):
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    rules = project.regex_rules(proj)
    assert any("点灯" in r["rule"] for r in rules)
    n = len(rules)
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    assert len(project.regex_rules(proj)) == n       # 重复导入不累加


def test_worldbook_entries_dedupe_against_existing(proj):
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH),
                       "## 1. 实体登记\n\n- **当铺**（地点）：早已登记的当铺\n")
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    doc = _read(proj, project.WORLDBOOK_PATH)
    assert "陈更" in doc
    assert doc.count("- **当铺**") == 1               # 同名不重复登记


def test_worldbook_second_import_reuses_one_section(proj):
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    plans = _plans(proj)
    for p in plans:
        if p["key"] == "core":
            p["checked"] = False
    importdoc.apply_import(proj, plans, "第二份.txt")
    assert _read(proj, project.WORLDBOOK_PATH).count("## 导入·") == 1


def test_foreshadow_rows_align_to_actual_header(proj):
    """伏笔表有两种真实表头（4/6 列），行必须按这本书的列数写，不能硬编"""
    project.write_file(project.get_tracking_path(proj, "伏笔"),
                       "# 伏笔追踪\n\n| 伏笔 | 类别 | 埋设章节 | 状态 | 计划回收 | 备注 |\n"
                       "|------|------|----------|------|----------|------|\n"
                       "| 已有的伏笔 | 道具谜团 | 第1章 | 未回收 | 第9章 | 旧 |\n")
    plans = importdoc.annotate(importdoc.parse_product(
        "===伏笔===\n第四次的灯是谁点的｜道具谜团｜第12章｜第20章前\n"
        "引证：灯笼里的火苗忽然矮了半寸\n- 已有的伏笔｜道具谜团｜第1章｜第9章"), SRC, proj)
    importdoc.apply_import(proj, plans, "设定集.txt")
    doc = _read(proj, "追踪/伏笔.md")
    rows = [l for l in doc.splitlines() if l.startswith("|") and "已有" not in l
            and "---" not in l and not l.startswith("| 伏笔")]
    assert len(rows) == 1
    assert len(rows[0].strip("|").split("|")) == 6
    assert "未回收" in rows[0]
    assert doc.count("第四次的灯") == 1               # 表里已有的不再加


def test_build_prompt_has_no_leftover_placeholders(proj):
    got = importdoc.build_prompt("文档正文", 1, 3, proj)
    assert "{" not in got.replace("{3,}", "") and got.count("第 1／3 段") == 1
    for marker in ("===核心设定===", "===正文 第N章===", "引证：", "===分歧点===",
                   "===原作进程===", "十一个落点"):
        assert marker in got


# ---------------------------------------------------------------- 同人文路径

CANON_SRC = """《守夜人》设定集（原作：爱潜水的乌贼）

灯序共九境，晋升必须服食主材料，失控者化为烛妖。
主角周夜是第七境守灯人，右手戴一枚会数数的骨戒。

本书分歧点：第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒。
原作进程：原作第一卷，周夜在灯塔之下杀死了前任守灯人。
"""

CANON_PRODUCT = """===原作===
书名：《守夜人》｜作者：爱潜水的乌贼
灯序共九境，晋升必须服食主材料，失控者化为烛妖。
引证：灯序共九境，晋升必须服食主材料，失控者化为烛妖

===世界书===
- 周夜（人物）：第七境守灯人，右手戴一枚会数数的骨戒
引证：主角周夜是第七境守灯人，右手戴一枚会数数的骨戒

===分歧点===
- 第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒
引证：第1章起，主角带着原作全文记忆穿成周夜，骨戒提前觉醒

===原作进程===
原作第一卷｜原作第1章｜周夜在灯塔之下杀死了前任守灯人
引证：原作第一卷，周夜在灯塔之下杀死了前任守灯人

===正文 第3章===
（无）
"""


def _canon_plans(proj):
    return importdoc.annotate(importdoc.parse_product(CANON_PRODUCT), CANON_SRC, proj)


def test_canon_name_drives_section_heading_not_filename(proj):
    plans = _canon_plans(proj)
    assert next(p for p in plans if p["key"] == "canon")["canon"] == "守夜人"
    importdoc.apply_import(proj, plans, "设定集.txt")
    doc = _read(proj, project.WORLDBOOK_PATH)
    assert "## 原作·守夜人" in doc
    assert "## 导入·设定集.txt" not in doc          # 借来的世界观必须标原作名


def test_divergence_becomes_must_contract(proj):
    importdoc.apply_import(proj, _canon_plans(proj), "设定集.txt")
    rules = project.regex_rules(proj)
    d = next(r for r in rules if "骨戒提前觉醒" in r["rule"])
    assert d["level"] == "must" and d["scope"].startswith("第1章")


def test_canon_guard_rule_is_suggested_and_untickable(proj):
    plans = _canon_plans(proj)
    guard = [p for p in plans if p.get("suggested")]
    assert len(guard) == 1 and "守夜人" in guard[0]["content"]
    assert guard[0]["checked"] is True              # 预勾选
    guard[0]["checked"] = False                     # 作者可以取消
    importdoc.apply_import(proj, plans, "设定集.txt")
    assert "既成事实不得改写" not in _read(proj, project.REGEX_PATH)


def test_canon_timeline_lands_in_timeline_table(proj):
    importdoc.apply_import(proj, _canon_plans(proj), "设定集.txt")
    doc = _read(proj, "追踪/时间线.md")
    row = next(l for l in doc.splitlines() if "守灯人" in l)
    assert len(row.strip("|").split("|")) == 3
    assert row.index("原作第一卷") < row.index("周夜在灯塔")


def test_no_canon_means_no_suggested_rule(proj):
    assert not any(p.get("suggested") for p in _plans(proj))


def test_canon_entries_are_pinned_const(proj):
    """借来的世界观必须常驻：世界书超预算按档裁剪时，它是最不能丢的地基"""
    importdoc.apply_import(proj, _canon_plans(proj), "设定集.txt")
    doc = _read(proj, project.WORLDBOOK_PATH)
    assert "[常驻]" in doc and "周夜" in doc
    # 裁剪路径会剥掉标记；「全文不超预算逐字返回」的快速路径不剥——
    # 那条路径下所有条目本来都要进来，标记只是多四个字符，不是丢设定
    trimmed = wb.assemble(proj, 0, 120, doc=doc + "\n" + "\n".join(
        "- **路人%s**（人物）：一次性背景板人物描述文字描述文字" % c for c in "甲乙丙丁戊己庚"))
    assert "[常驻]" not in trimmed["text"] and "周夜" in trimmed["text"]
    assert wb.assemble(proj, 0, 2000, doc=doc)["text"] == doc


def test_const_marker_survives_tight_budget(proj):
    project.write_file(os.path.join(proj, project.WORLDBOOK_PATH),
                       "# 世界书\n\n## 原作·守夜人\n\n"
                       "- **周夜**（人物）：第七境守灯人，右手戴一枚会数数的骨戒 [常驻]\n\n"
                       "## 9. 其它无关\n\n"
                       + "".join("- **路人%s**（人物）：一次性背景板人物描述文字描述文字\n"
                                 % c for c in "甲乙丙丁戊"))
    r = wb.assemble(proj, 0, 150)
    assert "周夜" in r["text"]
    assert "路人丁" not in r["text"]          # 被裁的应是无关路人
    assert any(a["name"] == "周夜" and a["why"] == "常驻" for a in r["activated"])


def test_non_canon_import_has_no_const_marker(proj):
    importdoc.apply_import(proj, _plans(proj), "设定集.txt")
    assert "[常驻]" not in _read(proj, project.WORLDBOOK_PATH)


# ---------------------------------------------------------------- 整批撤销

def test_revert_removes_imported_lines_and_files(proj):
    plans = _plans(proj)
    batch = importdoc.apply_import(proj, plans, "设定集.txt")["batch"]
    assert batch
    assert os.path.isfile(os.path.join(proj, "正文", "第012章_赎票.md"))

    r = importdoc.revert_import(proj, batch)
    assert r["ok"]
    assert "当铺收的不是东西" not in _read(proj, "设定/题材定位.md")
    assert "点灯" not in _read(proj, project.REGEX_PATH)
    assert "陈更" not in _read(proj, project.WORLDBOOK_PATH)
    assert not os.path.exists(os.path.join(proj, "正文", "第012章_赎票.md"))
    assert importdoc.import_batches(proj) == []


def test_revert_keeps_what_the_author_edited(proj):
    batch = importdoc.apply_import(proj, _plans(proj), "设定集.txt")["batch"]
    p = os.path.join(proj, "正文", "第012章_赎票.md")
    project.write_file(p, "第十二章 赎票\n作者自己重写过的一章。\n")
    rule_path = os.path.join(proj, project.REGEX_PATH)
    project.write_file(rule_path, _read(proj, project.REGEX_PATH).replace(
        "每月只能点灯三次", "每月只准点灯三次（作者改过措辞）"))

    r = importdoc.revert_import(proj, batch)
    assert os.path.isfile(p)                        # 改过的文件不删
    assert "被编辑过" in r["report"]
    assert "作者改过措辞" in _read(proj, project.REGEX_PATH)   # 改过的行不删


def test_revert_unknown_batch_is_reported_not_thrown(proj):
    r = importdoc.revert_import(proj, "20200101-000000")
    assert r["ok"] is False and "找不到" in r["report"]
