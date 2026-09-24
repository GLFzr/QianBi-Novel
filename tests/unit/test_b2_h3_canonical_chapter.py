# -*- coding: utf-8 -*-
"""H-3 护栏：get_chapter_path 同章收敛——同章号复用既有文件名，杜绝同章双文件。

审查报告：定稿按模型现算标题拼路径（stages.py get_chapter_path(proj,num,title)），
标题一变就在盘上留下 第005章.md + 第005章_NEW.md——list_chapters 双 num、
编辑器命中旧稿、导出重复计。修复收敛到源头：同章号复用既有文件名，
标题只影响「该章还不存在时」的新文件名。
"""
import os

from app import project


def _make_proj(tmp_path):
    return project.create_project(str(tmp_path), "同章收敛")


def test_same_num_reuses_existing_file(tmp_path):
    proj = _make_proj(tmp_path)
    p1 = project.get_chapter_path(proj, 5, "旧标题")
    project.write_file(p1, "第五章旧稿")
    # 标题变了：路径必须仍指向既有文件（同章双文件禁则）
    p2 = project.get_chapter_path(proj, 5, "新标题")
    assert p2 == p1, f"同章号拼出新路径 ⇒ 双文件：{p1} vs {p2}"
    project.write_file(p2, "第五章新稿")
    chapters = project.list_chapters(proj)
    assert [c[0] for c in chapters] == [5], f"盘上出现双章：{[c[1] for c in chapters]}"
    assert project.read_file(chapters[0][2]) == "第五章新稿"


def test_new_chapter_keeps_computed_title_name(tmp_path):
    """该章还不存在时：按标题拼名（含非法字符清洗）——旧行为不变"""
    proj = _make_proj(tmp_path)
    path = project.get_chapter_path(proj, 1, "风起/云涌")
    assert os.path.basename(path) == "第001章_风起云涌.md"
    path = project.get_chapter_path(proj, 2)
    assert os.path.basename(path) == "第002章.md"


def test_other_nums_unaffected(tmp_path):
    proj = _make_proj(tmp_path)
    project.write_file(project.get_chapter_path(proj, 3, "甲"), "三章")
    path4 = project.get_chapter_path(proj, 4, "乙")
    assert os.path.basename(path4) == "第004章_乙.md"
    project.write_file(path4, "四章")
    assert [c[0] for c in project.list_chapters(proj)] == [3, 4]
