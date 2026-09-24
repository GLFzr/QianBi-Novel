# -*- coding: utf-8 -*-
"""H-13 护栏：notify 漏发/守卫缺失致绑定脱同步（AST 静态钉死，不启 Qt）。

审查报告：_on_failed 缺 refreshQueue（对照 _on_finished）→ 队列卡「写作中」；
编辑区定稿回读无 _editor_dirty 守卫（对照 _on_repair_chapter 同款守卫）→
静默覆盖用户手改。两处都是「对照函数有、当事函数没有」的脱同步——用 AST
对账钉死，删任一守卫即红。
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE = os.path.join(ROOT, "app", "ui", "bridge.py")


def _bridge_functions():
    tree = ast.parse(open(BRIDGE, encoding="utf-8").read())
    return {f.name: f for f in ast.walk(tree)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_attrs(fn):
    return {getattr(c.func, "attr", getattr(c.func, "id", ""))
            for c in ast.walk(fn) if isinstance(c, ast.Call)}


def test_on_failed_refreshes_queue():
    """失败终态必须刷新队列（对照 _on_finished）——否则队列卡「写作中」"""
    fns = _bridge_functions()
    assert {"_on_failed", "_on_finished"} <= set(fns), "终态回调函数消失"
    for name in ("_on_finished", "_on_failed"):
        assert "refreshQueue" in _called_attrs(fns[name]), (
            f"{name} 不调 refreshQueue——{name} 后队列卡「写作中」（H-13 同族）")


def test_chapter_done_follow_respects_editor_dirty():
    """定稿回读必须以 _editor_dirty 为守卫：用户手改未保存不得静默覆盖"""
    fns = _bridge_functions()
    assert "_on_chapter_done" in fns, "_on_chapter_done 消失"
    guarded_ifs = [
        node for node in ast.walk(fns["_on_chapter_done"])
        if isinstance(node, ast.If)
        and any(isinstance(x, ast.Attribute) and x.attr == "_editor_dirty"
                for x in ast.walk(node.test))
    ]
    assert guarded_ifs, (
        "_on_chapter_done 的定稿回读不再受 _editor_dirty 守卫——"
        "用户手改未保存会被定稿回读静默覆盖（H-13 同族）")


def test_repair_chapter_keeps_same_guard():
    """对照锚不许塌：_on_repair_chapter 的同款守卫是本护栏的语义参照"""
    fns = _bridge_functions()
    assert "_on_repair_chapter" in fns, "_on_repair_chapter 消失（对照锚）"
    guarded_ifs = [
        node for node in ast.walk(fns["_on_repair_chapter"])
        if isinstance(node, ast.If)
        and any(isinstance(x, ast.Attribute) and x.attr == "_editor_dirty"
                for x in ast.walk(node.test))
    ]
    assert guarded_ifs, "_on_repair_chapter 的 _editor_dirty 同款守卫被摘（H-13 对照锚）"
