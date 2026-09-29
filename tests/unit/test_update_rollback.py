# -*- coding: utf-8 -*-
"""C21/R3 引导回滚单测（first_run 相位 × 崩溃 dump × 恢复动作参数）

盯的都是「升级那天才会暴露」的事（w5_update.md §3，裁决：只引导不自动回滚）：
- 伪造 journal/相位 + 新 dump → 崩溃判定真：相位停在 first_run（正常关闭标记
  stable 还没打上）∧ crash dump mtime 晚于更新时刻 → 判崩溃，恢复数据一次给齐；
- 正常关闭 → 假：首启整轮无新现场 → mark_stable 打正常关闭标记 → 判 none，
  相位文件收口归零——横幅只认崩溃现场，不拿「可能被硬杀」吓人；
- 恢复动作参数断言：verdict 的 from/to/pkg/dump/installer 逐项对；
  previous_installer 只认「比当前版旧的最近一份」；runPreviousInstaller 交互式
  拉起 startDetached(inst, [])（无 /SILENT——回滚让用户全程看得见）。
全部零真机残留：updates/ 相位文件与崩溃目录都走 tmp，CRASH_DIR 不碰。
"""
import os
import time

import pytest

import app
from app import config as cfg_mod
from app import update_install as upd
from app import update_rollback as ur

FROM_VER = "0.21.0"
TO_VER = "99.0.0"


@pytest.fixture
def isolate_updates_dir(tmp_path, monkeypatch):
    """相位文件落盘必须隔离：单测不许写线上 ~/.qianbi_novel/updates/"""
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def _journal(ts=1000.0, **over):
    j = {"from": FROM_VER, "to": TO_VER,
         "pkg": r"C:\u\QianBi-Novel-v99-setup.exe", "ts": ts, "phase": "launching"}
    j.update(over)
    return j


def _dump(crashes_dir, name="crash_20260929_120000.md", mtime=2000.0):
    """落一个假崩溃现场，mtime 显式设置（dump 新旧是判定的全部事实）"""
    os.makedirs(crashes_dir, exist_ok=True)
    p = os.path.join(crashes_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 崩溃现场（测试假件）\n")
    os.utime(p, (mtime, mtime))
    return p


# ---------- 纯判定：evaluate ----------

def test_evaluate_first_run_with_new_dump_is_crash(isolate_updates_dir, tmp_path):
    """伪造 first_run 相位 + 新 dump → 崩溃判定真，恢复数据一次给齐"""
    state = ur.begin_first_run(_journal(), "v99.0.0 marker", str(tmp_path / "upd"))
    dump = _dump(str(tmp_path / "crashes"), mtime=2000.0)
    v = ur.evaluate(state, [{"path": dump, "mtime": 2000.0}])
    assert v["state"] == "crash" and v["active"] is True, v
    assert v["from"] == FROM_VER and v["to"] == TO_VER, v
    assert v["pkg"] == _journal()["pkg"], v
    assert v["dump"] == dump and v["dump_ts"] == 2000.0, v


def test_evaluate_old_dump_is_not_crash(isolate_updates_dir, tmp_path):
    """更新时刻之前的旧 dump（上一版的陈年现场）不作数：mtime 晚于 update_ts 才算"""
    state = ur.begin_first_run(_journal(ts=1000.0), "", str(tmp_path / "upd"))
    old = _dump(str(tmp_path / "crashes"), mtime=500.0)
    assert ur.evaluate(state, [{"path": old, "mtime": 500.0}])["state"] == "watch"


def test_evaluate_stable_phase_is_none(isolate_updates_dir, tmp_path):
    """正常关闭 → 假：相位推进 stable（正常关闭标记在）后，新 dump 也不再喊回滚"""
    state = ur.begin_first_run(_journal(), "", str(tmp_path / "upd"))
    stable = ur.mark_stable(state, str(tmp_path / "upd"))
    assert stable["phase"] == ur.PHASE_STABLE
    assert ur.evaluate(stable, [{"path": "x", "mtime": 99999.0}])["state"] == "none"
    assert ur.evaluate({}, [])["state"] == "none", "无相位文件（已消费）恒 none"


# ---------- 相位机：startup_check ----------

def test_startup_first_launch_begins_phase_quietly(isolate_updates_dir):
    """装完首次启动：立相位但不打标（首启还没跑，不能自己给自己开正常证明）"""
    v = ur.startup_check(_journal(), "v99.0.0 marker", TO_VER,
                         crashes_dir=str(isolate_updates_dir / "nope"))
    assert v == {}, "刚装完的这次启动必须安静，无 dump 不许喊回滚"
    st = ur.read_state()
    assert st["phase"] == ur.PHASE_FIRST_RUN and st["to"] == TO_VER
    assert st["update_ts"] == 1000.0 and st["from"] == FROM_VER


def test_startup_crash_after_first_run_is_detected(isolate_updates_dir, tmp_path):
    """标准剧本：首启崩溃 → 第二次启动判崩溃，相位保留（横幅要一直亮到用户表态）"""
    ur.startup_check(_journal(), "v99.0.0 marker", TO_VER)          # 启动1：立相位
    dump = _dump(str(tmp_path / "crashes"))                          # 首启崩了
    v = ur.startup_check({}, "", TO_VER,                             # 启动2：判崩溃
                         crashes_dir=str(tmp_path / "crashes"))
    assert v["state"] == "crash" and v["dump"] == dump, v
    assert v["to"] == TO_VER and v["from"] == FROM_VER, v
    st = ur.read_state()
    assert st["phase"] == ur.PHASE_FIRST_RUN, "崩溃判定的相位必须保留，横幅下次启动还在"


def test_startup_clean_first_run_marks_stable(isolate_updates_dir, tmp_path):
    """正常关闭 → 假：首启整轮无新现场 → 第二次启动打 stable 标记，第三次归零"""
    crashes = str(tmp_path / "empty_crashes")
    ur.startup_check(_journal(), "v99.0.0 marker", TO_VER, crashes_dir=crashes)
    v = ur.startup_check({}, "", TO_VER, crashes_dir=crashes)       # 首启正常走完
    assert v == {}
    assert ur.read_state().get("phase") == ur.PHASE_STABLE, "正常关闭标记要落在盘上"
    v2 = ur.startup_check({}, "", TO_VER, crashes_dir=crashes)
    assert v2 == {} and ur.read_state() == {}, "stable 相位收口归零，观察期永久关闭"


def test_startup_crash_before_phase_write_still_detected(isolate_updates_dir, tmp_path):
    """装完自动重开就崩（相位还没来得及立）：journal(launching)+marker+新 dump → 判崩溃"""
    dump = _dump(str(tmp_path / "crashes"))
    v = ur.startup_check(_journal(), "v99.0.0 marker", TO_VER,
                         crashes_dir=str(tmp_path / "crashes"))
    assert v["state"] == "crash" and v["dump"] == dump, v


def test_startup_version_mismatch_consumes_phase(isolate_updates_dir, tmp_path):
    """现在跑的已不是当时装的版（用户自己动过）：观察失效，相位清掉"""
    ur.startup_check(_journal(), "v99.0.0 marker", TO_VER)
    _dump(str(tmp_path / "crashes"))
    v = ur.startup_check({}, "", "0.98.0",                          # 另一个版本来跑
                         crashes_dir=str(tmp_path / "crashes"))
    assert v == {} and ur.read_state() == {}, "版本对不上就别再拿旧观察期吓人"


def test_startup_no_update_no_phase(isolate_updates_dir):
    """没更新过（无 journal 无相位）→ 恒 none，且不许凭空写相位文件"""
    assert ur.startup_check({}, "", app.__version__) == {}
    assert ur.read_state() == {}


# ---------- 恢复动作参数 ----------

def test_previous_installer_picks_closest_older(isolate_updates_dir, tmp_path):
    """updates/ 里多份安装包：只认比当前版旧的最近一份（U-C prune 保证有货）"""
    d = str(tmp_path / "updates")
    os.makedirs(d, exist_ok=True)
    for name in ("QianBi-Novel-v0.20.0-setup.exe",
                 "QianBi-Novel-v0.21.0-setup.exe",
                 "QianBi-Novel-v99.0.0-setup.exe",      # 比当前新版：不是回滚路子
                 "not-an-installer.exe",                # 解析不出版本：跳过
                 "readme.txt"):                          # 非 exe：跳过
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"x")
    got = ur.previous_installer(d, TO_VER)
    assert got == os.path.join(d, "QianBi-Novel-v0.21.0-setup.exe"), got
    assert ur.previous_installer(d, "0.19.0") == "", "没有更旧的包就返回空串，不编路径"


def test_startup_crash_verdict_carries_installer(isolate_updates_dir, tmp_path):
    """崩溃 verdict 必须自带上一版安装包路径与 updates 目录（恢复对话框数据齐）"""
    d = str(tmp_path / "updates")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "QianBi-Novel-v0.21.0-setup.exe"), "wb") as f:
        f.write(b"x")
    # 相位文件与安装包同住 updates/（生产事实）：两次调用必须同一个目录，
    # 否则第二次读的是另一份 updates/，相位为空、崩溃判定根本不会发生
    ur.startup_check(_journal(), "v99.0.0 marker", TO_VER, updates_dir=d)
    _dump(str(tmp_path / "crashes"))
    v = ur.startup_check({}, "", TO_VER, crashes_dir=str(tmp_path / "crashes"),
                         updates_dir=d)
    assert v["installer"] == os.path.join(d, "QianBi-Novel-v0.21.0-setup.exe"), v
    assert v["updatesDir"] == d, v


def test_bridge_run_previous_installer_interactive_params(isolate_updates_dir,
                                                          tmp_path, monkeypatch):
    """桥端到端：updateRollback 横幅数据 + runPreviousInstaller 交互式参数断言

    startDetached(inst, [])——不带 /SILENT：回滚是罕见动作，让用户全程看得见；
    拉起成功即消费相位（横幅功成身退）。相位 to 必须等于当前版：版本对不上时
    观察期会被判失效清掉（那正是版本守卫的职责）。
    """
    import app.ui.bridge as bridge_mod
    from app import update_check as uc
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(uc, "install_dir", lambda: str(tmp_path / "app"))
    upd_dir = uc.updates_dir()
    old_pkg = os.path.join(upd_dir, "QianBi-Novel-v0.21.0-setup.exe")
    with open(old_pkg, "wb") as f:
        f.write(b"old-installer")
    # 相位文件直接立在盘上（模拟「首启崩过后第二次启动」之前的现场）
    ur.begin_first_run(_journal(ts=time.time() - 100, to=app.__version__), "")
    fake_dump = str(tmp_path / "crashes" / "crash_x.md")
    monkeypatch.setattr(ur, "list_dumps",
                        lambda crashes_dir="": [{"path": fake_dump, "mtime": time.time()}])

    from app.ui.bridge import Bridge
    b = Bridge()
    rb = b.updateRollback
    assert rb.get("active") is True and rb.get("to") == app.__version__, rb
    assert rb.get("installer") == old_pkg and rb.get("dump") == fake_dump, rb

    calls = []

    class _QP:
        @staticmethod
        def startDetached(path, args):
            calls.append((path, list(args)))
            return True

    monkeypatch.setattr(bridge_mod, "QProcess", _QP)
    b.runPreviousInstaller()
    assert calls == [(old_pkg, [])], calls    # 交互式：零旗标，用户自己走向导
    assert b.updateRollback == {}, "用户已表态（回滚），横幅必须退场"
    assert ur.read_state() == {}, "相位文件随之消费，观察期收口"


def test_bridge_run_previous_installer_without_package_warns(isolate_updates_dir,
                                                             tmp_path, monkeypatch):
    """上一版安装包不在了（被手动清掉）：给发布页指引，绝不 startDetached 空路径"""
    import app.ui.bridge as bridge_mod
    from app import update_check as uc
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(uc, "install_dir", lambda: str(tmp_path / "app"))
    ur.begin_first_run(_journal(ts=time.time() - 100, to=app.__version__), "")
    monkeypatch.setattr(ur, "list_dumps",
                        lambda crashes_dir="": [{"path": "d.md", "mtime": time.time()}])
    from app.ui.bridge import Bridge
    b = Bridge()
    assert b.updateRollback.get("active") is True
    assert b.updateRollback.get("installer") == "", "没有旧包就不许编路径"

    calls = []

    class _QP:
        @staticmethod
        def startDetached(path, args):
            calls.append((path, list(args)))
            return True

    monkeypatch.setattr(bridge_mod, "QProcess", _QP)
    b.runPreviousInstaller()
    assert calls == [], "空路径绝不能被拉起"


def test_bridge_dismiss_consumes_phase(isolate_updates_dir, tmp_path, monkeypatch):
    """「继续用新版」：相位消费 + 横幅退场（下次启动不再出现）"""
    from app import update_check as uc
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(uc, "install_dir", lambda: str(tmp_path / "app"))
    ur.begin_first_run(_journal(ts=time.time() - 100, to=app.__version__), "")
    monkeypatch.setattr(ur, "list_dumps",
                        lambda crashes_dir="": [{"path": "d.md", "mtime": time.time()}])
    from app.ui.bridge import Bridge
    b = Bridge()
    assert b.updateRollback.get("active") is True
    b.dismissUpdateRollback()
    assert b.updateRollback == {} and ur.read_state() == {}
