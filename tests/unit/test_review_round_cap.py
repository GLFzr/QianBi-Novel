# -*- coding: utf-8 -*-
"""N-06 护栏：审校修复环轮数上限由配置真实生效。

出厂值 1 曾被读取点地板 max(...,3) 永久吃掉（配置 <3 一律无效）。
修复后：出厂 3（默认行为不变）、地板 1（配置 1 ⇒ 上限 1）。
WP-12 连带：纯函数六例之外，钉死 stages.py 的调用点必须来自 _review_round_cap
（否则把调用点改回 max(...,3)，六例依旧全绿——护栏存在但没接线上）。
"""
import ast
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


# ---- WP-12：调用点钉死（AST，从代码现实派生，不写死行号） ----

def _stages_source():
    path = os.path.join(ROOT, "app", "core", "stages.py")
    return open(path, encoding="utf-8").read()


def _review_cap_call_sites():
    """stages.py 里 _review_round_cap 的全部调用点（按外层函数名归类）"""
    tree = ast.parse(_stages_source())
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "_review_round_cap":
            sites.append(node)
    return sites


def test_review_round_cap_read_only_via_helper():
    """修复轮上限的读取必须收敛在 _review_round_cap 一处：
    ① helper 自身之外的任何 max(...review_max_rounds...) 调用 = 把地板逻辑
       拷回调用点的回归形态，必红；
    ② 两个修复环站点（stages 主循环 + 定点修复路径）必须真的调用 helper——
       删掉调用（恒 3 恒 1 硬编码）同样必红。"""
    tree = ast.parse(_stages_source())
    stray_max = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Name) and f.id == "max"):
            continue
        # helper 定义体内的 max(1, int(...)) 是地板本体，合法
        src = ast.get_source_segment(_stages_source(), node) or ast.unparse(node)
        if "review_max_rounds" in src:
            stray_max.append(node.lineno)
    assert len(stray_max) == 1, (
        f"stages.py 里除 _review_round_cap 定义体外还有 {len(stray_max)} 处直接对 "
        f"review_max_rounds 做 max 的调用（行号 {stray_max}）——修复轮上限被拷贝/"
        f"改写回内联 max(...,3) 形态（N-06 回归）")

    sites = _review_cap_call_sites()
    assert len(sites) >= 2, (
        f"stages.py 里 _review_round_cap 调用点只剩 {len(sites)} 处（应为两处修复环"
        "站点 2037/2896 一带）——某处上限改成了硬编码，配置不再生效（N-06 回归）")
