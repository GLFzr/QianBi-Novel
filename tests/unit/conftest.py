# -*- coding: utf-8 -*-
"""单测引导：把仓库根目录加入 sys.path，保证 `from app import ...` 可导入"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- 配置隔离（主代理 09-18 复验补）----
# 实测：单跑 tests/unit/test_b1_default_cw.py 会把 tmp_path 写进线上
# ~/.qianbi_novel/config.json 的 recent_projects，并把出厂 run_mode 落回盘上；
# 整跑时又因别的用例在 import 期永久改过模块级路径而看不见（顺序污染掩盖泄漏）。
# 因此在导入任何测试模块之前，把 app.config 的落盘目标整体改到本进程专属临时目录。
import tempfile as _tempfile

_ISO_DIR = _tempfile.mkdtemp(prefix="qbn_unit_cfg_")
os.environ["QIANBI_CONFIG_DIR"] = _ISO_DIR
try:
    from app import config as _cfg
    _cfg.CONFIG_DIR = _ISO_DIR
    _cfg.CONFIG_FILE = os.path.join(_ISO_DIR, "config.json")
    _cfg._LEGACY_DIR = os.path.join(_ISO_DIR, "_no_legacy")
except Exception:  # pragma: no cover - 隔离失败必须响，不许静默
    raise

# ---- Keyring 围栏（W-04）----
# config 落盘已进临时目录，但 save_config→dehydrate→store_secret 仍会按 secrets.SERVICE
# 写 Windows 凭据管理器——那是 QIANBI_CONFIG_DIR 管不到的系统级状态。09-18 实测：单测种子里
# 带真实样式的 Key 会被脱水进用户真 Keyring。把 SERVICE 指到测试专用命名空间，用户三条真 Key 不动。
try:
    from app import secrets as _sec
    _sec.SERVICE = "QianBiNovel/connections.__unittest__"
except Exception:  # pragma: no cover
    raise

# ---- 会话起始的真实 HOME（macOS 钥匙串按 HOME 找 login.keychain-db）----
# 十余个测试模块在 import 期把 HOME/USERPROFILE 改到各自的临时目录（且不还原），
# 于是排在它们之后的用例拿到的是别人的临时 HOME：钥匙串路径随之落空，真凭据写入
# 失败 → dehydrate 回退明文 → 「磁盘泄漏明文 key」假红。需要真凭据库的用例用这两个
# 值在自己作用域里把 HOME 还原（monkeypatch.setenv，退出即复原）。
_REAL_HOME = os.environ.get("HOME") or ""
_REAL_USERPROFILE = os.environ.get("USERPROFILE") or ""


def restore_real_home(monkeypatch):
    """把 HOME/USERPROFILE 拨回会话起始值（钥匙串/凭据类用例用）"""
    if _REAL_HOME:
        monkeypatch.setenv("HOME", _REAL_HOME)
    if _REAL_USERPROFILE:
        monkeypatch.setenv("USERPROFILE", _REAL_USERPROFILE)


def qianbi_isolated_dir():
    """给锁测试用：当前单测进程的配置落盘目标。"""
    return _ISO_DIR
