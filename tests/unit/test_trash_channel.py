# -*- coding: utf-8 -*-
"""系统垃圾桶通道（app/trash.py）：平台分派 + 「失败绝不退化成永久删除」

0.20.1 书架删书的立身之本：Windows 走 SHFileOperationW + FOF_ALLOWUNDO，macOS 走
移入 .Trash。两侧同一条纪律——移不动就抛 OSError，书必须留在原地；本模块里任何
一条 `except` 后继续删的分支都是丢稿事故，所以下面每条断言都盯着「源还在不在」。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from app import trash  # noqa: E402

_NEEDS_POSIX_HOME = pytest.mark.skipif(
    sys.platform == "win32",
    reason="废纸篓按 POSIX HOME 定位；Windows 那侧走 SHFileOperation 通道")


def _book(tmp_path, name="我的书"):
    book = tmp_path / name
    book.mkdir()
    (book / "正文.md").write_text("第一版", encoding="utf-8")
    return book


# ---------- macOS 废纸篓 ----------

@_NEEDS_POSIX_HOME
def test_mac_trash_moves_book_into_home_trash(monkeypatch, tmp_path):
    """移入 ~/.Trash 而不是删掉：正文要一并过去"""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".Trash").mkdir()
    book = _book(tmp_path)
    trash._mac_trash(str(book))
    assert not book.exists(), "源目录必须消失（已被搬走）"
    moved = tmp_path / ".Trash" / "我的书"
    assert (moved / "正文.md").read_text(encoding="utf-8") == "第一版", "正文必须原样在废纸篓里"


@_NEEDS_POSIX_HOME
def test_mac_trash_never_overwrites_same_name(monkeypatch, tmp_path):
    """废纸篓里已有同名的书：后来者不许把它吃掉（Finder 的做法）"""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".Trash").mkdir()
    first = tmp_path / ".Trash" / "我的书"
    first.mkdir()
    (first / "旧的.md").write_text("旧", encoding="utf-8")
    book = _book(tmp_path)
    trash._mac_trash(str(book))
    assert (first / "旧的.md").exists(), "废纸篓里原有的东西不许被覆盖"
    assert (tmp_path / ".Trash" / "我的书 1" / "正文.md").exists(), "新来的另起一个名字"


@_NEEDS_POSIX_HOME
def test_mac_trash_without_trash_dir_keeps_book(monkeypatch, tmp_path):
    """没有废纸篓通道：抛 OSError，书留在原地——绝不退化成永久删除"""
    monkeypatch.setenv("HOME", str(tmp_path))
    book = _book(tmp_path)
    with pytest.raises(OSError, match="永不永久删除"):
        trash._mac_trash(str(book))
    assert book.exists(), "移不进废纸篓时书必须还在原地"
    assert (book / "正文.md").exists(), "一个字节都不许少"


def test_mac_trash_missing_target_raises(tmp_path):
    with pytest.raises(OSError):
        trash._mac_trash(str(tmp_path / "ghost"))


@_NEEDS_POSIX_HOME
def test_trash_dir_for_cross_volume_uses_volume_trash(monkeypatch, tmp_path):
    """书在另一个卷上：进那个卷自己的 .Trash（同卷搬才不用跨卷拷贝）"""
    home = tmp_path / "home"
    vol = tmp_path / "vol"
    (home / ".Trash").mkdir(parents=True)
    (vol / ".Trash").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(trash, "_volume_root",
                        lambda p: str(vol) if str(p).startswith(str(vol)) else str(home))
    assert trash._trash_dir_for(str(vol / "书")) == str(vol / ".Trash")
    assert trash._trash_dir_for(str(home / "书")) == str(home / ".Trash")


def test_unique_dest_never_replaces(tmp_path):
    dest = str(tmp_path / "书")
    assert trash._unique_dest(dest) == dest
    (tmp_path / "书").mkdir()
    assert trash._unique_dest(dest) == dest + " 1"
    (tmp_path / "书 1").mkdir()
    assert trash._unique_dest(dest) == dest + " 2"


def test_volume_root_is_a_mountpoint(tmp_path):
    root = trash._volume_root(str(tmp_path / "nope" / "deeper"))
    assert os.path.ismount(root), "必须走到挂载点，否则跨卷判断无从谈起"


# ---------- 分派与「不支持的平台」 ----------

def test_send_to_recycle_darwin_goes_to_trash(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(trash, "_platform_key", lambda: "darwin")
    monkeypatch.setattr(trash, "_mac_trash", calls.append)
    trash.send_to_recycle(str(tmp_path))
    assert calls == [str(tmp_path)]


def test_send_to_recycle_nt_goes_to_shfileop(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(trash, "_platform_key", lambda: "nt")
    monkeypatch.setattr(trash, "_sh_delete", calls.append)
    trash.send_to_recycle(str(tmp_path))
    assert calls == [str(tmp_path)]


def test_send_to_recycle_unsupported_platform_refuses(monkeypatch, tmp_path):
    """没接垃圾桶通道的平台：拒绝执行而不是偷偷 rm——书必须还在"""
    monkeypatch.setattr(trash, "_platform_key", lambda: "linux")
    book = _book(tmp_path, "别的书")
    with pytest.raises(OSError, match="永不永久删除"):
        trash.send_to_recycle(str(book))
    assert book.exists(), "拒绝执行之后书必须原封不动"


def test_send_to_recycle_requires_existing_dir(tmp_path):
    with pytest.raises(OSError):
        trash.send_to_recycle(str(tmp_path / "ghost"))
