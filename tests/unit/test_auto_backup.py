# -*- coding: utf-8 -*-
"""C29 自动备份单测：zip 产物 / 保留 N 份裁剪 / 损坏项目不阻断 / 开关零动作 /
shutdown·关书路径接线（bridge 用轻量桩 self 直调未绑定方法，不起 Qt）。"""
import os
import zipfile

import pytest

from app.core import auto_backup
from app.ui import bridge as bmod


# ---------- 夹具 ----------

def _make_project(root, name="我的书"):
    """标准小项目：设定/正文 + .git 与 __pycache__ 垃圾（应被排除）"""
    proj = os.path.join(str(root), name)
    os.makedirs(os.path.join(proj, "正文"), exist_ok=True)
    os.makedirs(os.path.join(proj, "设定"), exist_ok=True)
    with open(os.path.join(proj, "正文", "001.md"), "w", encoding="utf-8") as f:
        f.write("第一章 正文")
    with open(os.path.join(proj, "设定", "world.md"), "w", encoding="utf-8") as f:
        f.write("世界观设定")
    os.makedirs(os.path.join(proj, ".git"), exist_ok=True)
    with open(os.path.join(proj, ".git", "HEAD"), "w", encoding="utf-8") as f:
        f.write("ref: refs/heads/main")
    os.makedirs(os.path.join(proj, "__pycache__"), exist_ok=True)
    with open(os.path.join(proj, "__pycache__", "junk.pyc"), "wb") as f:
        f.write(b"junk")
    return proj


class _LogModel:
    def __init__(self, owner):
        self._owner = owner

    def append(self, *a):
        self._owner.logs.append(a)


class _FakeBridge:
    """shutdown/_auto_backup 族用轻量桩：只供所需属性与方法；
    _auto_backup_tick 走 Bridge 真方法（验证开关/去重/登记全链），打包靠
    monkeypatch auto_backup.create_backup 拦截记录。"""

    def __init__(self, tmp_path, cfg=None, projects=()):
        self.cfg = cfg if cfg is not None else {}
        self.proj = projects[0] if projects else None
        self._session_projects = [os.path.normpath(p) for p in projects]
        self.orch = None
        self._running = False
        self._cw_worker = None
        self._cw_sum_worker = None
        self._backflow_worker = None
        self.logs = []
        self.zips = []            # create_backup 被调记录
        self.logModel = _LogModel(self)
        self._backup_root = os.path.join(str(tmp_path), "cfgdir", "backups")

    def _auto_backup_dir(self, proj):
        return os.path.join(self._backup_root,
                            os.path.basename(os.path.normpath(proj)))

    def _auto_backup_tick(self, proj):
        """桩不是 Bridge 子类，属性查找够不到真方法——显式委托（走真实逻辑）"""
        return bmod.Bridge._auto_backup_tick(self, proj)

    def _auto_backup_on_shutdown(self):
        bmod.Bridge._auto_backup_on_shutdown(self)


@pytest.fixture
def backup_spy(monkeypatch):
    """把 core 打包替换为记录器：返回 (记录列表, 返回值工厂)"""
    calls = []

    def _record(project_path, backup_dir, keep=5, book_name=""):
        calls.append({"proj": os.path.normpath(str(project_path)),
                      "dir": str(backup_dir), "keep": keep})
        return os.path.join(str(backup_dir), "fake.zip")

    monkeypatch.setattr(auto_backup, "create_backup", _record)
    return calls


@pytest.fixture
def backup_boom(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("备份炸了")
    monkeypatch.setattr(auto_backup, "create_backup", _boom)


# ---------- 1. zip 产物存在且可解 ----------

def test_backup_creates_readable_zip(tmp_path):
    proj = _make_project(tmp_path)
    bdir = os.path.join(str(tmp_path), "backups", "我的书")
    out = auto_backup.create_backup(proj, bdir, keep=5)
    assert out and os.path.isfile(out)
    assert out.endswith(".zip") and "我的书" in os.path.basename(out)
    with zipfile.ZipFile(out) as zf:            # 可解 + 无损坏成员
        assert zf.testzip() is None
        names = [n.replace("\\", "/") for n in zf.namelist()]   # zip 规范用 / 分隔
    assert "正文/001.md" in names
    assert any("world.md" in n for n in names)
    # 排除：.git / __pycache__ 不进包
    assert not any(".git" in n for n in names)
    assert not any("__pycache__" in n for n in names)


# ---------- 2. 保留 N 份裁剪 ----------

def test_keep_trims_to_n(tmp_path, monkeypatch):
    proj = _make_project(tmp_path)
    bdir = os.path.join(str(tmp_path), "backups", "我的书")
    seq = iter("20260101_0000%02d" % i for i in range(7))
    monkeypatch.setattr(auto_backup, "_timestamp", lambda: next(seq))
    for _ in range(7):
        assert auto_backup.create_backup(proj, bdir, keep=5)
    zips = sorted(n for n in os.listdir(bdir) if n.endswith(".zip"))
    assert len(zips) == 5                        # 超删旧：7 份只留最近 5 份
    assert zips[0].endswith("_000002.zip")       # 最旧两份被裁
    assert zips[-1].endswith("_000006.zip")


def test_keep_zero_disables_trim(tmp_path, monkeypatch):
    proj = _make_project(tmp_path)
    bdir = os.path.join(str(tmp_path), "backups", "我的书")
    seq = iter("20260101_0000%02d" % i for i in range(3))
    monkeypatch.setattr(auto_backup, "_timestamp", lambda: next(seq))
    for _ in range(3):
        assert auto_backup.create_backup(proj, bdir, keep=0)
    assert len([n for n in os.listdir(bdir) if n.endswith(".zip")]) == 3


# ---------- 3. 损坏项目不阻断（跳过并记录，绝不抛出）----------

def test_broken_project_returns_empty_without_raise(tmp_path, monkeypatch):
    # 项目目录不存在 / 路径是文件不是目录
    assert auto_backup.create_backup(
        os.path.join(str(tmp_path), "不存在"), str(tmp_path), keep=5) == ""
    pfile = os.path.join(str(tmp_path), "是个文件")
    with open(pfile, "w", encoding="utf-8") as f:
        f.write("x")
    assert auto_backup.create_backup(pfile, str(tmp_path), keep=5) == ""
    # 打包中途 os.walk 炸（权限/损坏）→ 仍不抛出，且不留半截 zip
    proj = _make_project(tmp_path, "烂书")
    bdir = os.path.join(str(tmp_path), "backups", "烂书")

    def _boom(*a, **kw):
        raise OSError("模拟损坏项目")
    monkeypatch.setattr(auto_backup.os, "walk", _boom)
    assert auto_backup.create_backup(proj, bdir, keep=5) == ""
    monkeypatch.undo()                           # 恢复 walk 后验证无残留半截包
    assert not os.path.exists(bdir) or \
        not [n for n in os.listdir(bdir) if n.endswith(".zip")]


# ---------- 4. 开关关闭零动作 ----------

def test_enabled_default_on_and_off():
    assert auto_backup.enabled({}) is True                       # 出厂默认开
    assert auto_backup.enabled({"auto_backup": {"enabled": False}}) is False
    assert auto_backup.keep_n({}) == 5
    assert auto_backup.keep_n({"auto_backup": {"keep": 3}}) == 3


def test_disabled_tick_is_noop(tmp_path, monkeypatch):
    proj = _make_project(tmp_path)
    fb = _FakeBridge(tmp_path, cfg={"auto_backup": {"enabled": False, "keep": 5}})

    def _no_backup(*a, **kw):                    # 零动作：真打包一旦被调即红
        raise AssertionError("开关关闭仍触发了打包")
    monkeypatch.setattr(auto_backup, "create_backup", _no_backup)
    assert bmod.Bridge._auto_backup_tick(fb, proj) == ""


def test_due_mark_done_daily_throttle(tmp_path):
    proj = _make_project(tmp_path)
    cfg = {}
    assert auto_backup.due(cfg, proj, "2026-09-29") is True
    auto_backup.mark_done(cfg, proj, "2026-09-29")
    assert auto_backup.due(cfg, proj, "2026-09-29") is False     # 当日不再备
    assert auto_backup.due(cfg, proj, "2026-09-30") is True      # 次日恢复
    assert cfg["auto_backup"]["done"][os.path.normpath(proj)] == "2026-09-29"


def test_tick_backs_up_marks_done_and_throttles(tmp_path, backup_spy):
    proj = _make_project(tmp_path)
    fb = _FakeBridge(tmp_path, cfg={"auto_backup": {"enabled": True, "keep": 5}})
    out = bmod.Bridge._auto_backup_tick(fb, proj)
    assert out.endswith("fake.zip")
    assert backup_spy and backup_spy[0]["proj"] == os.path.normpath(proj)
    assert backup_spy[0]["keep"] == 5
    assert fb.logs and "自动备份" in fb.logs[0][1]
    assert auto_backup.due(fb.cfg, proj) is False                # 落了当日标记
    assert bmod.Bridge._auto_backup_tick(fb, proj) == ""         # 当日再 tick 零动作
    assert len(backup_spy) == 1


# ---------- 5. shutdown / 关书路径接线（mock 触发）----------

def test_shutdown_backs_up_session_projects(tmp_path, backup_spy):
    p1 = _make_project(tmp_path, "书一")
    p2 = _make_project(tmp_path, "书二")
    fb = _FakeBridge(tmp_path, projects=[p1, p2])
    bmod.Bridge.shutdown(fb, 100)                # 轻量桩直调，不需要 Qt 事件循环
    assert [c["proj"] for c in backup_spy] == [os.path.normpath(p1),
                                               os.path.normpath(p2)]


def test_shutdown_survives_backup_crash(tmp_path, backup_boom):
    fb = _FakeBridge(tmp_path, projects=[str(tmp_path)])
    bmod.Bridge.shutdown(fb, 100)                # 备份炸了不许阻断退出：不抛即过


def test_shutdown_skips_missing_projects(tmp_path, backup_spy):
    ghost = os.path.join(str(tmp_path), "已删除的书")
    live = _make_project(tmp_path, "还在的书")
    fb = _FakeBridge(tmp_path, projects=[ghost, live])
    bmod.Bridge.shutdown(fb, 100)
    assert [c["proj"] for c in backup_spy] == [os.path.normpath(live)]


def test_close_book_backs_up_before_switch(tmp_path, backup_spy):
    old = _make_project(tmp_path, "旧书")
    new = _make_project(tmp_path, "新书")
    fb = _FakeBridge(tmp_path, projects=[old])
    bmod.Bridge._auto_backup_on_close_book(fb, new)   # 换书 → 备旧书
    assert [c["proj"] for c in backup_spy] == [os.path.normpath(old)]
    bmod.Bridge._auto_backup_on_close_book(fb, old)   # 同书重开 → 不触发
    assert len(backup_spy) == 1
    fb.proj = None
    bmod.Bridge._auto_backup_on_close_book(fb, new)   # 无书 → 不触发
    assert len(backup_spy) == 1


def test_close_book_honors_disabled_switch(tmp_path, monkeypatch):
    old = _make_project(tmp_path, "旧书")
    fb = _FakeBridge(tmp_path, cfg={"auto_backup": {"enabled": False}})

    def _no_backup(*a, **kw):
        raise AssertionError("开关关闭仍触发了打包")
    monkeypatch.setattr(auto_backup, "create_backup", _no_backup)
    bmod.Bridge._auto_backup_on_close_book(fb, os.path.join(str(tmp_path), "新书"))
    assert fb.logs == []


def test_remember_session_project_dedup():
    fb = _FakeBridge.__new__(_FakeBridge)        # 只测登记逻辑，跳过 __init__
    fb._session_projects = []
    bmod.Bridge._remember_session_project(fb, "G:/a/我的书/")
    bmod.Bridge._remember_session_project(fb, "G:\\a\\我的书")   # 规范化后去重
    assert fb._session_projects == [os.path.normpath("G:/a/我的书")]


# ---------- 6. 出厂键与迁移契约 ----------

def test_default_config_keys():
    """出厂键：默认开 + 保留 5 份（成熟度短板补齐的契约钉测）"""
    from app import config
    ab = config.DEFAULT_CONFIG["auto_backup"]
    assert ab["enabled"] is True
    assert ab["keep"] == 5
    assert auto_backup.enabled(config.DEFAULT_CONFIG) is True
    assert auto_backup.keep_n(config.DEFAULT_CONFIG) == 5


def test_migrate_respects_explicit_legacy_off():
    """老用户显式关过旧「每日备份」→ 新键保持关；显式开/未表态 → 按新默认开"""
    from app.config import _migrate_auto_backup
    cfg = {"backup": {"auto": False}, "auto_backup": {"enabled": True, "keep": 5}}
    assert _migrate_auto_backup(cfg)["auto_backup"]["enabled"] is True  # 新键已表态→不动
    # 盘上老 config 走 load_config 的补缺键合并后 auto_backup 必已存在（出厂数据）
    cfg2 = {"backup": {"auto": False}, "auto_backup": {}}
    _migrate_auto_backup(cfg2)
    assert cfg2["auto_backup"]["enabled"] is False
    cfg3 = {"backup": {"auto": True}, "auto_backup": {}}
    _migrate_auto_backup(cfg3)
    assert "enabled" not in cfg3["auto_backup"]                  # 未显式关→出厂开兜底
    cfg4 = {}
    _migrate_auto_backup(cfg4)
    assert cfg4.get("auto_backup") is None                       # 无新键（新装路径）→不动
