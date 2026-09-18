# -*- coding: utf-8 -*-
"""单测不得写用户线上配置（主代理 09-18 实测泄漏后加的锁）。

实测：加隔离前单跑 tests/unit/test_b1_default_cw.py，会把 pytest 的 tmp_path 写进
~/.qianbi_novel/config.json 的 last_project / recent_projects，并把出厂 run_mode 落盘；
整跑时因别的用例改过模块级路径而看不出来（顺序污染把泄漏藏住了）。
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as cfg_mod  # noqa: E402
from app import secrets as sec_mod  # noqa: E402

LIVE = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
PROD_SERVICE = "QianBiNovel/connections"   # secrets.py 里的真实生产命名空间字面量


def _live_sha():
    if not os.path.exists(LIVE):
        return "absent"
    with open(LIVE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_unit_process_config_dir_is_temp_not_home():
    real = os.path.normpath(os.path.join(os.path.expanduser("~"), ".qianbi_novel"))
    cur = os.path.normpath(cfg_mod.CONFIG_DIR)
    assert os.path.normpath(cur) != real, (
        "单测进程的落盘目标仍是用户线上目录（隔离没生效）：", cur)
    assert os.path.normpath(cfg_mod.CONFIG_FILE).startswith(os.path.normpath(cur)), (
        "CONFIG_FILE 没跟着 CONFIG_DIR 走")


def test_save_config_never_touches_live_file(tmp_path, monkeypatch):
    """最像事故现场的写盘：load → 塞最近项目 → save_config。线上文件必须零字节变化。"""
    before = _live_sha()
    cfg = cfg_mod.load_config()
    cfg["recent_projects"] = [str(tmp_path)]
    cfg["last_project"] = str(tmp_path)
    (cfg.setdefault("writing") or {})["run_mode"] = "probe-mutant"
    cfg_mod.save_config(cfg)
    assert _live_sha() == before, (
        "单测 save_config 改到了用户线上 config.json（sha 变了）")
    with open(cfg_mod.CONFIG_FILE, encoding="utf-8") as f:
        import json as _j
        wrote = _j.load(f)
    assert wrote.get("last_project") == str(tmp_path), "写盘应落在隔离目录里（写对了地方）"


# ---------- W-04：Keyring 命名空间围栏 + 进程隔离可抗 kill ----------

def test_secrets_service_is_fenced_in_unit_process():
    """单测进程的 secrets.SERVICE 必须不是生产命名空间（否则 dehydrate 写进用户真 Keyring）。"""
    assert sec_mod.SERVICE != PROD_SERVICE, \
        "secrets.SERVICE 仍指向生产命名空间——09-18 事故会复现"
    assert sec_mod.SERVICE.endswith("__unittest__"), \
        "SERVICE 未指到测试专用命名空间：" + sec_mod.SERVICE


def test_dehydrate_store_secret_targets_fenced_namespace(monkeypatch):
    """走真 store_secret 路径：即便 _AVAILABLE 为真，set_password 也必须打到围栏命名空间。"""
    seen = {}

    def fake_set(service, cid, key):
        seen["service"] = service

    monkeypatch.setattr(sec_mod, "_AVAILABLE", True)
    monkeypatch.setattr(sec_mod._keyring, "set_password", fake_set, raising=True)
    assert sec_mod.store_secret("probe-conn", "sk-abcdef1234567890") is True
    assert seen.get("service") == sec_mod.SERVICE
    assert seen.get("service") != PROD_SERVICE, "Key 被脱水进用户真实凭据命名空间"


_CHILD = r'''
import sys, os, time, json
mode = sys.argv[1]; fake_home = sys.argv[2]
sys.path.insert(0, os.environ["QBN_ROOT"])
os.environ["HOME"] = fake_home
os.environ["USERPROFILE"] = fake_home
if mode == "snapshot":
    live = os.path.join(fake_home, ".qianbi_novel", "config.json")
    os.makedirs(os.path.dirname(live), exist_ok=True)
    orig = None
    if os.path.exists(live):
        orig = open(live, "rb").read()
    import atexit
    def _restore():
        try:
            if orig is not None:
                open(live, "wb").write(orig)
        except OSError:
            pass
    atexit.register(_restore)
    from app import config as c
    c.save_config({"recent_projects": [fake_home], "marker": "dirty"})
else:  # redirect：父进程已设 QIANBI_CONFIG_DIR，导入即落临时目录
    from app import config as c
    c.save_config({"recent_projects": [fake_home], "marker": "dirty"})
sys.stdout.write("WROTE\n"); sys.stdout.flush()
time.sleep(30)
'''


def _run_child_killed(tmp_path, mode):
    """起子进程写配置、等它就绪后强杀（模拟探针超时被 kill），返回 fake-live 的 sha。"""
    import subprocess
    fake_home = str(tmp_path / "home")
    os.makedirs(os.path.join(fake_home, ".qianbi_novel"), exist_ok=True)
    live = os.path.join(fake_home, ".qianbi_novel", "config.json")
    open(live, "w", encoding="utf-8").write('{"pristine": true}')   # 已知原值
    with open(live, "rb") as f:
        before = hashlib.sha256(f.read()).hexdigest()
    env = dict(os.environ)
    env["QBN_ROOT"] = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env.pop("QIANBI_CONFIG_DIR", None)
    if mode == "redirect":
        env["QIANBI_CONFIG_DIR"] = str(tmp_path / "probe_cfg")
    child = os.path.join(str(tmp_path), "_child.py")
    open(child, "w", encoding="utf-8").write(_CHILD)
    p = subprocess.Popen([sys.executable, child, mode, fake_home],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = ""
        import time as _t
        deadline = _t.time() + 30
        while "WROTE" not in line and _t.time() < deadline:
            r = p.stdout.readline()
            if not r:
                break
            line += r
        _t.sleep(0.3)   # 确保写盘已落，再杀（此时 atexit 还原永远轮不到跑）
    finally:
        p.kill(); p.wait(timeout=10)
    with open(live, "rb") as f:
        after = hashlib.sha256(f.read()).hexdigest()
    return before, after


def test_redirect_isolation_survives_kill(tmp_path):
    """新机制：配置落盘目标改到临时目录 ⇒ 探针中途被 kill，用户 config 也从未成为写入目标。"""
    before, after = _run_child_killed(tmp_path, "redirect")
    assert before == after, "重定向到临时目录后仍被 kill 脏到——进程隔离没生效"


def test_snapshot_restore_does_not_survive_kill(tmp_path):
    """对照组（钉住为什么要有 W-04）：只靠 atexit 还原、直写真实路径的旧机制，
    进程被 kill ⇒ 还原轮不到跑 ⇒ 线上被脏。此例若红，说明「抗 kill 靠快照」这个前提本身错了。"""
    before, after = _run_child_killed(tmp_path, "snapshot")
    assert before != after, (
        "快照还原机制下被 kill 竟没脏——说明本对照组没还原旧风险，"
        "或子进程根本没直写 fake-live（测试自身失效）")


_CHILD_GUARD = r'''
import sys, os, time
fake_home = sys.argv[1]
sys.path.insert(0, os.environ["QBN_ROOT"])
sys.path.insert(0, os.path.join(os.environ["QBN_ROOT"], "tests"))
os.environ["HOME"] = fake_home
os.environ["USERPROFILE"] = fake_home
os.environ.pop("QIANBI_CONFIG_DIR", None)
import probe_guard
probe_guard.arm_config_guard()          # W-04：进程内重定向 config 到临时目录 + 围栏 secrets
from app import config as c
from app import secrets as sec
c.save_config({"recent_projects": [fake_home], "marker": "dirty"})
sys.stdout.write("CFG_DIR_OUTSIDE_HOME=%s SERVICE_FENCED=%s WROTE\n" % (
    not os.path.normpath(c.CONFIG_DIR).startswith(os.path.normpath(fake_home)),
    sec.SERVICE != "QianBiNovel/connections"))
sys.stdout.flush()
time.sleep(30)
'''


def test_probe_guard_redirect_survives_kill(tmp_path):
    """真探针护栏跑到一半被 kill：arm_config_guard 已把落盘重定向到临时目录 ⇒
    线上（这里用 fake-live 模拟）config.json 逐字节不变；且 secrets.SERVICE 已离生产命名空间。"""
    import subprocess
    fake_home = str(tmp_path / "home")
    os.makedirs(os.path.join(fake_home, ".qianbi_novel"), exist_ok=True)
    live = os.path.join(fake_home, ".qianbi_novel", "config.json")
    open(live, "w", encoding="utf-8").write('{"pristine": true}')
    before = hashlib.sha256(open(live, "rb").read()).hexdigest()
    env = dict(os.environ)
    env["QBN_ROOT"] = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env.pop("QIANBI_CONFIG_DIR", None)
    child = os.path.join(str(tmp_path), "_guard_child.py")
    open(child, "w", encoding="utf-8").write(_CHILD_GUARD)
    p = subprocess.Popen([sys.executable, child, fake_home],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        out = ""
        import time as _t
        deadline = _t.time() + 30
        while "WROTE" not in out and _t.time() < deadline:
            r = p.stdout.readline()
            if not r:
                break
            out += r
        _t.sleep(0.3)
    finally:
        p.kill(); p.wait(timeout=10)
    after = hashlib.sha256(open(live, "rb").read()).hexdigest()
    assert "CFG_DIR_OUTSIDE_HOME=True" in out, "arm_config_guard 没把 config 落盘重定向出家目录"
    assert "SERVICE_FENCED=True" in out, "arm_config_guard 没把 secrets.SERVICE 移出生产命名空间"
    assert before == after, "探针被 kill 后线上 config 仍被脏——进程隔离没生效"
