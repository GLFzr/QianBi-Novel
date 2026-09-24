# -*- coding: utf-8 -*-
"""H-11 护栏：bridge 与 core/stages 的「修复稿健全性守卫」双实现不许漂移。

审查报告：bridge.py 与 core/stages.py 的修复守卫逐字同构（注释自承「同款」），
漂移无人守。双实现合并是 XL 重构；本护栏先把两边钉死——任一侧的
判空/判计划/长度阈值被单方面改动即红，改一侧必须同步另一侧或显式更新本护栏。
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE = os.path.join(ROOT, "app", "ui", "bridge.py")
STAGES = os.path.join(ROOT, "app", "core", "stages.py")


def _guard_signatures(path):
    """抽文件内全部「修复稿健全性守卫」三元组的规范化签名：
    [looks_like_plan 赋值, too_short 赋值, 紧随的 if 判定] 的 ast.dump 列表。"""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    parent = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[child] = p
    sigs = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "looks_like_plan"):
            continue
        holder = parent.get(node)
        body = getattr(holder, "body", None)
        if not body or node not in body:
            continue
        idx = body.index(node)
        if idx + 2 >= len(body):
            continue
        too_short, if_stmt = body[idx + 1], body[idx + 2]
        if not (isinstance(too_short, ast.Assign)
                and isinstance(if_stmt, ast.If)):
            continue
        sigs.append([ast.dump(node), ast.dump(too_short), ast.dump(if_stmt.test)])
    return sigs


def test_fix_sanity_guard_stays_in_sync():
    bridge_sigs = _guard_signatures(BRIDGE)
    stages_sigs = _guard_signatures(STAGES)
    assert len(bridge_sigs) == 1, (
        f"bridge 修复守卫站点数异常：{len(bridge_sigs)}（预期 1）")
    assert stages_sigs, "stages 修复守卫站点消失"
    assert bridge_sigs[0] in stages_sigs, (
        "bridge 与 core/stages 的修复稿健全性守卫已漂移"
        "（判空/判计划/长度阈值单方面改动）——两处是同款双实现（H-11），"
        "改一侧必须同步另一侧或显式更新本护栏")
