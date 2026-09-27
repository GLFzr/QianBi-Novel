# -*- coding: utf-8 -*-
"""0.20.1 书架删书：bridge.deleteBook 双模式行为矩阵。

纪律钉死：① 永不永久删除（disk 只走 trash.send_to_recycle 回收站通道）；
② 当前打开的书拒绝；③ 非 project 目录拒绝；④ 回收站失败不改编组（书还在书架上）；
⑤ 组列表变更必须落盘（写共享 self.cfg 再 save_config，config_write_guard 同族）。
"""
import io
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys_path = ROOT
if sys_path not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from app import config as cfg_mod  # noqa: E402
from app import project  # noqa: E402


@pytest.fixture(scope="module")
def bridge():
    from app.ui.bridge import Bridge
    return Bridge()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离配置文件 + 一个真书项目 + 两个杂目录"""
    books_root = tmp_path / "books"
    books_root.mkdir()
    proj = str(books_root / "我的书")
    project.create_project(books_root, "我的书")
    project.write_idea_info(proj, "都市脑洞", "番茄", "测试", 10)
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path))
    return {
        "proj": proj,
        "cfg_file": cfg_file,
        "empty_dir": str(tmp_path / "not_a_book"),
        "missing": str(tmp_path / "ghost"),
    }


def _arm(bridge, env, extra=None):
    recents = [env["proj"]] + (extra or [])
    bridge.cfg = {"recent_projects": list(recents)}
    return recents


def _toasts(bridge):
    got = []
    bridge.toast.connect(lambda level, msg: got.append((level, msg)))
    return got


def test_shelf_mode_removes_entry_and_persists(bridge, env):
    other = env["empty_dir"]
    _arm(bridge, env, extra=[other])
    got = _toasts(bridge)
    bridge.deleteBook(env["proj"], "shelf")
    assert bridge.cfg["recent_projects"] == [other]
    disk = json.loads(io.open(env["cfg_file"], encoding="utf-8").read())
    assert disk["recent_projects"] == [other]
    assert any(lv == "ok" for lv, _ in got)


def test_disk_mode_sends_to_recycle_then_removes(bridge, env, monkeypatch):
    from app import trash
    calls = []
    monkeypatch.setattr(trash, "send_to_recycle", lambda p: calls.append(os.path.abspath(p)))
    _arm(bridge, env)
    bridge.deleteBook(env["proj"], "disk")
    assert calls == [os.path.abspath(env["proj"])]
    assert bridge.cfg["recent_projects"] == []
    disk = json.loads(io.open(env["cfg_file"], encoding="utf-8").read())
    assert disk["recent_projects"] == []


def test_disk_failure_keeps_book_on_shelf(bridge, env, monkeypatch):
    from app import trash
    def boom(p):
        raise OSError("回收站不可用")
    monkeypatch.setattr(trash, "send_to_recycle", boom)
    _arm(bridge, env)
    got = _toasts(bridge)
    bridge.deleteBook(env["proj"], "disk")
    assert bridge.cfg["recent_projects"] == [env["proj"]]  # 书还在书架上
    assert any(lv == "warn" and "未被删除" in m for lv, m in got)


def test_open_project_refused(bridge, env):
    _arm(bridge, env)
    got = _toasts(bridge)
    bridge.proj = env["proj"]          # 模拟正开着这本书
    try:
        bridge.deleteBook(env["proj"], "shelf")
        assert bridge.cfg["recent_projects"] == [env["proj"]]
        assert any("先关闭" in m for _, m in got)
    finally:
        bridge.proj = ""


def test_non_project_dir_refused(bridge, env):
    os.makedirs(env["empty_dir"], exist_ok=True)
    _arm(bridge, env, extra=[env["empty_dir"]])
    _toasts(bridge)
    bridge.deleteBook(env["empty_dir"], "disk")
    assert env["empty_dir"] in bridge.cfg["recent_projects"]  # 未动


def test_missing_path_refused(bridge, env):
    _arm(bridge, env, extra=[env["missing"]])
    _toasts(bridge)
    bridge.deleteBook(env["missing"], "shelf")
    assert env["missing"] in bridge.cfg["recent_projects"]


def test_invalid_mode_refused(bridge, env):
    _arm(bridge, env)
    got = _toasts(bridge)
    bridge.deleteBook(env["proj"], "shift-delete")   # 永久删除这类语义根本不存在
    assert bridge.cfg["recent_projects"] == [env["proj"]]
    assert any("未知" in m for _, m in got)
