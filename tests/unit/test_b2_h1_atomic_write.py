# -*- coding: utf-8 -*-
"""H-1 护栏：project.write_file 原子写盘。

审查报告：write_file 纯 open("w") 直写，崩在半截会留下被
first_missing_chapter（只看文件名存在）判为「已写」的残稿——该章永久跳过，
下一章从残尾续写。修复 = 同目录临时文件 → flush → os.replace 原子替换
（Windows 瞬时文件锁重试 3 次退避，失败不碰原文件、临时文件清理后原样上抛）。
"""
import os

import pytest

from app import project


def _make_proj(tmp_path):
    return project.create_project(str(tmp_path), "原子写盘")


def test_write_file_roundtrip_and_no_tmp_leftover(tmp_path):
    proj = _make_proj(tmp_path)
    path = project.get_chapter_path(proj, 1, "开局")
    project.write_file(path, "# 第1章 开局\n\n正文内容")
    assert project.read_file(path) == "# 第1章 开局\n\n正文内容"
    # 覆盖写也一致（原子替换不是追加/截断拼接）
    project.write_file(path, "改后的正文")
    assert project.read_file(path) == "改后的正文"
    leftovers = [f for f in os.listdir(os.path.join(proj, "正文")) if f.endswith(".tmp")]
    assert not leftovers, f"临时文件残留：{leftovers}"


def test_write_file_replace_failure_keeps_original(tmp_path, monkeypatch):
    """os.replace 全程被占用（模拟杀软瞬时锁不释放）⇒ 异常上抛、原稿完好、tmp 清理"""
    proj = _make_proj(tmp_path)
    path = project.get_chapter_path(proj, 1)
    project.write_file(path, "原稿内容")
    calls = {"n": 0}

    def _always_locked(src, dst):
        calls["n"] += 1
        raise PermissionError(5, "拒绝访问（模拟占用不释放）")

    monkeypatch.setattr(os, "replace", _always_locked)
    monkeypatch.setattr(project.time, "sleep", lambda s: None)   # 不真等退避
    with pytest.raises(PermissionError):
        project.write_file(path, "新内容")
    assert calls["n"] == 3, "应重试 3 次后再放弃"
    # 原文件完好无损（截断丢稿禁则）+ 临时文件已清理
    assert project.read_file(path) == "原稿内容"
    assert not [f for f in os.listdir(os.path.join(proj, "正文")) if f.endswith(".tmp")]


def test_write_file_retry_recovers_from_transient_lock(tmp_path, monkeypatch):
    """Windows 真机路径：os.replace 前两次被瞬时锁拒绝、第三次成功 ⇒ 写入落地"""
    proj = _make_proj(tmp_path)
    path = project.get_chapter_path(proj, 2)
    real_replace = os.replace
    state = {"n": 0}

    def _locked_twice(src, dst):
        state["n"] += 1
        if state["n"] <= 2:
            raise PermissionError(5, "瞬时锁")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _locked_twice)
    monkeypatch.setattr(project.time, "sleep", lambda s: None)
    project.write_file(path, "第二章正文")
    monkeypatch.undo()
    assert state["n"] == 3
    assert project.read_file(path) == "第二章正文"
