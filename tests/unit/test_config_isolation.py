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

LIVE = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")


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
