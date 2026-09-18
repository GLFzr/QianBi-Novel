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


def qianbi_isolated_dir():
    """给锁测试用：当前单测进程的配置落盘目标。"""
    return _ISO_DIR
