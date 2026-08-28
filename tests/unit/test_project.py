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


def test_idea_info_and_planned_chapters(tmp_path):
    proj = _make_proj(tmp_path)
    project.write_idea_info(proj, "都市脑洞", "番茄", "一个能改命的笔记本", 60)
    info = project.read_idea_info(proj)
    assert info["genre"] == "都市脑洞"
    assert info["total_words_wan"] == 60
    assert project.planned_chapters(proj, chapter_word_target=3000) == 200
