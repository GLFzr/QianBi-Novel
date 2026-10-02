# -*- coding: utf-8 -*-
"""0.24.0 W1 上下文治理回归：
- Q1-a 接力压缩质量标定（默认开 + 阈值 48k + stages 默认读数）
- Q1-c 记账相位脱离卷会话（_bk_session）
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from app.core import stages
from app.core import history_compaction as hc
from app import config as cfg_mod


class _Ctx:
    def __init__(self, cfg):
        self.cfg = cfg


def test_q1a_threshold_quality_calibrated():
    """阈值默认 48k（≈192k 窗口×25%）——旧 800k 成本口径在劣化区外，见计划 §一。"""
    assert hc.DEFAULT_TOKEN_THRESHOLD == 48_000
    assert hc.token_threshold({}) == 48_000
    assert cfg_mod.DEFAULT_CONFIG["writing"]["compaction"] is True
    assert cfg_mod.DEFAULT_CONFIG["writing"]["compaction_token_threshold"] == 48_000


def test_q1a_enabled_by_default():
    """默认开：{} / DEFAULT_CONFIG 均开；显式 False 仍可整体关（字节纪律由显式关承载）。"""
    assert hc.compaction_enabled({}) is True
    assert hc.compaction_enabled(cfg_mod.DEFAULT_CONFIG) is True
    assert hc.compaction_enabled({"writing": {"compaction": False}}) is False


def test_q1c_bk_session_detaches_by_default():
    """Q1-c：记账相位默认脱离（None）；显式 bookkeeping_off_session=False 回骑会话。"""
    sentinel = object()
    assert stages._bk_session(_Ctx({}), sentinel) is None
    assert stages._bk_session(_Ctx({"writing": {}}), sentinel) is None
    assert stages._bk_session(
        _Ctx({"writing": {"bookkeeping_off_session": False}}), sentinel) is sentinel
    # None 透传（无会话路径本就独立单发）
    assert stages._bk_session(_Ctx({}), None) is None
