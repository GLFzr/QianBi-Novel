# -*- coding: utf-8 -*-
"""N-06 护栏：审校修复环轮数上限由配置真实生效。

出厂值 1 曾被读取点地板 max(...,3) 永久吃掉（配置 <3 一律无效）。
修复后：出厂 3（默认行为不变）、地板 1（配置 1 ⇒ 上限 1）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import config as cfg_mod
from app.core.stages import _review_round_cap


def test_factory_default_is_3():
    assert cfg_mod.DEFAULT_CONFIG["gates"]["review_max_rounds"] == 3


def test_missing_config_falls_back_to_3():
    assert _review_round_cap({}) == 3
    assert _review_round_cap(None) == 3


def test_config_value_1_is_now_effective():
    assert _review_round_cap({"review_max_rounds": 1}) == 1


def test_config_value_5_passes_through():
    assert _review_round_cap({"review_max_rounds": 5}) == 5


def test_floor_is_1_not_3():
    assert _review_round_cap({"review_max_rounds": 0}) == 1
    assert _review_round_cap({"review_max_rounds": -2}) == 1


def test_string_value_coerced_and_garbage_falls_back():
    assert _review_round_cap({"review_max_rounds": "2"}) == 2
    assert _review_round_cap({"review_max_rounds": "abc"}) == 3
