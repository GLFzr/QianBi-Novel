# -*- coding: utf-8 -*-
"""C19/U-A 静默安装编排单测（journal + /SILENT 三旗标 + 启动对账两态）

盯的都是「升级那天才会暴露」的事（w5_update.md §2）：
- installUpdateNow 编排序：flush 草稿 → journal **先于** startDetached 落盘
  （记录待更新状态与包路径，启动对账靠它）→ shutdown() 被调（U-6：os._exit
  不走事件循环，aboutToQuit 不会再触发，流水线/共写线程必须在这里优雅停）→
  三旗标 /SILENT /NORESTART /LOG= → os._exit(0)；
- journal 写/读/清与 marker 读取（路径全走隔离后的 CONFIG_DIR，零真机残留）；
- reconcile_update 两态：journal+marker → clear（清 journal 正常启动）；
  journal 而 marker 缺 → notify（安装器被截杀/断电——journal 保留供排障、
  指向安装包引导手动装）；无 journal → none。
全部零真进程：QProcess.startDetached 与 os._exit 都是假件。
"""
import hashlib
import os

import pytest

import app
from app import config as cfg_mod
from app import update_check as uc
from app import update_install as upd

SHA = hashlib.sha256(b"silent-pkg-bytes").hexdigest()
MANIFEST = {"version": "99.0.0", "url": "https://example.invalid/release/99",
            "sha256": SHA,
            "assets": {"setup": {"name": "QianBi-Novel-v99-setup.exe",
                                 "url": "https://example.invalid/dl/setup.exe",
                                 "sha256": SHA, "size": 16}}}


@pytest.fixture
def isolate_updates_dir(tmp_path, monkeypatch):
    """journal/LOG 落盘必须隔离：单测不许写线上 ~/.qianbi_novel/updates/"""
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def _make_pkg(base):
    """落一个哈希与 MANIFEST 匹配的假安装包，返回路径"""
    d = os.path.join(str(base), "updates_pkg")
    os.makedirs(d, exist_ok=True)
    pkg = os.path.join(d, "QianBi-Novel-v99-setup.exe")
    with open(pkg, "wb") as f:
        f.write(b"silent-pkg-bytes")
    return pkg


def _armed_bridge(isolate_updates_dir, tmp_path):
    """过三道门的桥：验签通过 + 安装版（install_mode 由各测试自己 patch）+ 包已验"""
    from app.ui.bridge import Bridge
    pkg = _make_pkg(isolate_updates_dir)
    b = Bridge()
    b._update_result = uc.CheckResult(state=uc.STATE_NEW,
                                      manifest=dict(MANIFEST), verified=True)
    b._update_pkg = {"ok": True, "path": pkg, "actual": SHA, "expected": SHA}
    return b, pkg


# ---------- journal / marker 基元 ----------

def test_journal_roundtrip_records_from_to_pkg(isolate_updates_dir):
    assert upd.read_journal() == {}, "没有待更新时 journal 必须是空"
    entry = upd.write_journal(to_version="99.0.0", pkg_path=r"C:\u\setup.exe")
    assert entry["to"] == "99.0.0" and entry["pkg"] == r"C:\u\setup.exe"
    assert entry["from"] == app.__version__ and entry["phase"] == "launching"
    assert entry["ts"] > 0
    j = upd.read_journal()
    assert j["to"] == "99.0.0" and j["pkg"] == r"C:\u\setup.exe"
    upd.clear_journal()
    assert upd.read_journal() == {}


def test_marker_read_and_missing(isolate_updates_dir, tmp_path):
    assert upd.read_marker_text(str(tmp_path / "nope" / ".update_done")) == "", \
        "marker 缺席必须读成空串（这正是「安装器没跑完」的判定依据）"
    mp = upd.marker_path(str(tmp_path))
    with open(mp, "w", encoding="utf-8") as f:
        f.write("v99.0.0 2026-09-29 10:00:00\n")
    assert upd.read_marker_text(mp).startswith("v99.0.0")


# ---------- reconcile_update 两态（对账纯判定） ----------

def test_reconcile_clear_when_marker_present(isolate_updates_dir, tmp_path):
    """journal + marker → clear：安装器跑完了，清 journal 正常启动（版本随行返回）"""
    j = {"from": app.__version__, "to": "99.0.0",
         "pkg": str(tmp_path / "s.exe"), "ts": 1.0, "phase": "launching"}
    st = upd.reconcile_update(j, "v99.0.0 2026-09-29 10:00:00")
    assert st["state"] == "clear" and st["to"] == "99.0.0", st


def test_reconcile_notify_and_keep_journal_when_marker_missing(isolate_updates_dir, tmp_path):
    """journal 而 marker 缺 → notify：包还在就指向它（引导手动安装）；journal 由调用方保留"""
    pkg = _make_pkg(tmp_path)
    j = {"from": app.__version__, "to": "99.0.0", "pkg": pkg, "ts": 1.0}
    st = upd.reconcile_update(j, "")
    assert st["state"] == "notify" and st["pkg"] == pkg, st


def test_reconcile_notify_falls_back_to_updates_dir_when_pkg_gone(isolate_updates_dir, tmp_path):
    """安装包已被清掉：指向退路 updates/ 目录（旧包保留策略归 U-C），不指空路径"""
    j = {"to": "99.0.0", "pkg": str(tmp_path / "gone.exe")}
    st = upd.reconcile_update(j, "")
    assert st["state"] == "notify" and st["pkg"] == "", st
    assert st["updates_dir"] == uc.updates_dir(), st


def test_reconcile_no_journal_is_none(isolate_updates_dir):
    assert upd.reconcile_update({}, "")["state"] == "none"
    assert upd.reconcile_update(None, "v99.0.0 x")["state"] == "none", \
        "没有 journal 时 marker 在不在都无关"


# ---------- installUpdateNow 编排（QProcess.startDetached 捕获 + os._exit 假件） ----------

def test_install_update_now_silent_orchestration(isolate_updates_dir, tmp_path, monkeypatch):
    import app.ui.bridge as bridge_mod
    b, pkg = _armed_bridge(isolate_updates_dir, tmp_path)
    monkeypatch.setattr(uc, "install_mode", lambda: "installed")

    calls, journal_at_launch, exits, shutdowns = [], [], [], []

    class _QP:
        @staticmethod
        def startDetached(path, args):
            journal_at_launch.append(dict(upd.read_journal()))   # 捕获拉起瞬间的 journal
            calls.append((path, list(args)))
            return True

    monkeypatch.setattr(bridge_mod, "QProcess", _QP)
    monkeypatch.setattr(os, "_exit", lambda code=0: exits.append(code))
    monkeypatch.setattr(b, "shutdown", lambda *a, **k: shutdowns.append(True))

    b.installUpdateNow()

    assert len(calls) == 1, calls
    path, args = calls[0]
    assert path == pkg, "拉起的必须是已验包本体"
    assert args[:2] == ["/SILENT", "/NORESTART"], args
    assert len(args) == 3 and args[2].startswith("/LOG="), args
    assert args[2].endswith("install_v99.0.0.log"), args
    assert os.path.dirname(args[2][len("/LOG="):]) == uc.updates_dir(), \
        "安装日志必须落在 updates/ 目录（固定路径覆盖写，当排障凭据）"
    # journal 先于 startDetached 落盘，且已记录待更新状态与包路径
    assert journal_at_launch[0].get("to") == "99.0.0", journal_at_launch
    assert journal_at_launch[0].get("pkg") == pkg, journal_at_launch
    assert journal_at_launch[0].get("from") == app.__version__, journal_at_launch
    assert len(shutdowns) == 1, "shutdown 必须被调（U-6：os._exit 不走 aboutToQuit）"
    assert exits == [0], "安装器拉起后 os._exit(0)（躲 Qt 静态析构）"
    assert b._quit_for_update is True
    # 假 os._exit 返回后函数走完：journal 留在盘上，等下次启动与 marker 对账
    assert upd.read_journal().get("to") == "99.0.0"


def test_install_update_now_start_failure_rolls_back_journal(isolate_updates_dir, tmp_path,
                                                             monkeypatch):
    """startDetached 失败：journal 必须撤（否则下次启动误报「上次更新未完成」）"""
    import app.ui.bridge as bridge_mod
    b, _pkg = _armed_bridge(isolate_updates_dir, tmp_path)
    monkeypatch.setattr(uc, "install_mode", lambda: "installed")
    toasts = []
    b.toast.connect(lambda lv, msg: toasts.append((lv, str(msg))))

    class _QP:
        @staticmethod
        def startDetached(path, args):
            return False

    monkeypatch.setattr(bridge_mod, "QProcess", _QP)
    exits, shutdowns = [], []
    monkeypatch.setattr(os, "_exit", lambda code=0: exits.append(code))
    monkeypatch.setattr(b, "shutdown", lambda *a, **k: shutdowns.append(True))

    b.installUpdateNow()

    assert toasts and toasts[-1][0] == "error" and "没能启动" in toasts[-1][1], toasts
    assert b._quit_for_update is False
    assert upd.read_journal() == {}, "没拉起安装器就没有 marker，journal 不能留"
    assert exits == [] and shutdowns, "失败不退出，但 shutdown 已在拉起前调过"


def test_install_update_now_gates_stay_shut(isolate_updates_dir, tmp_path, monkeypatch):
    """三道门原样：未验签 / 便携版 / 包被换，一个都不许走到 startDetached"""
    import app.ui.bridge as bridge_mod
    b, pkg = _armed_bridge(isolate_updates_dir, tmp_path)

    calls = []

    class _QP:
        @staticmethod
        def startDetached(path, args):
            calls.append((path, list(args)))
            return True

    monkeypatch.setattr(bridge_mod, "QProcess", _QP)
    exits = []
    monkeypatch.setattr(os, "_exit", lambda code=0: exits.append(code))

    # ① 未验签
    b._update_result.verified = False
    b.installUpdateNow()
    assert calls == [] and upd.read_journal() == {}
    b._update_result.verified = True

    # ② 便携版
    monkeypatch.setattr(uc, "install_mode", lambda: "portable")
    b.installUpdateNow()
    assert calls == [] and upd.read_journal() == {}
    monkeypatch.setattr(uc, "install_mode", lambda: "installed")

    # ③ 包在校验后被换
    with open(pkg, "wb") as f:
        f.write(b"tampered-bytes")
    b.installUpdateNow()
    assert calls == [] and upd.read_journal() == {}
    assert exits == [], "三道门任何一道拦下都不许走到退出"
    assert b._update_pkg.get("ok") is False, "被换的包必须当场标坏"
