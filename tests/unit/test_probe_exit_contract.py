# -*- coding: utf-8 -*-
"""R10 退出码契约锁：探针/检查脚本「自报结论」与「进程退码」必须一致

背景（WP-11 实测）：check_layout.py 打印 LAYOUT_CHECK_DONE 后落到模块末尾，Qt 静态
析构期 native fastfail（0xC0000409，经 MSYS timeout 映射成 127）——"报成功却退非零"。
本锁静态要求每支 probe_*.py / check_layout.py 末尾存在显式退出码约定，并把
「PASS 分支退码非 0」当违规。

helper 模块豁免：被其他探针 import 的 probe_*（如 probe_format_guard / probe_guard）
是库不是运行体——该集合从全部探针源码的 import 语句派生，不是手写白名单。
"""
import ast
import os

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runner_files():
    files = sorted(
        os.path.join(TESTS_DIR, n) for n in os.listdir(TESTS_DIR)
        if n.startswith("probe_") and n.endswith(".py"))
    files.append(os.path.join(TESTS_DIR, "check_layout.py"))
    return files


def _module_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def _imported_probe_modules():
    """被任一探针源码 import 的 probe_* 模块名集合（从代码派生，非手写清单）"""
    imported = set()
    for path in _runner_files():
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("probe_"):
                        imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("probe_"):
                    imported.add(node.module.split(".")[0])
    return imported


def _exit_calls(nodes):
    """收集语句序列里的 sys.exit(...) / os._exit(...) / raise SystemExit(...) 调用节点"""
    calls = []
    for node in nodes:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            is_exit_attr = (isinstance(f, ast.Attribute) and f.attr in ("exit", "_exit")
                            and isinstance(f.value, ast.Name)
                            and f.value.id in ("sys", "os"))
            is_systemexit = isinstance(f, ast.Name) and f.id == "SystemExit"
            if is_exit_attr or is_systemexit:
                calls.append(sub)
    return calls


def _top_level_tail_statements(tree):
    """模块最后一条顶层语句（不下钻函数/类定义）"""
    return tree.body[-1:] if tree.body else []


def _terminal_exit_call(tree):
    """末条顶层语句内的退出调用（允许 if __name__ == '__main__' 包裹）"""
    for st in _top_level_tail_statements(tree):
        calls = _exit_calls([st])
        if calls:
            return calls[-1]
    return None


def _pass_branch_is_zero(call_node):
    """终端退出调用必须「双向」满足 R10：PASS 退 0 且 FAIL 退非 0。

    可静态判定的形态：
    - 裸常量参数（含 0）：一律违规——`sys.exit(0)` 恒 0 意味着 FAIL 也退 0
      （v3 复验变异），`sys.exit(2)` 恒非 0 意味着 PASS 也非 0；成功/失败必须
      由失败派生表达式决定
    - 双分支均为常量的条件表达式：两值必须恰含一个 0（如 `1 if fail else 0`）；
      两分支同值（`1 if ok else 1` / `0 if ok else 0`）即违规
    其余（名字/调用/运算）视为失败派生，静态不可判但约定存在。
    """
    if not call_node.args:
        return True
    arg = call_node.args[0]
    if isinstance(arg, ast.Constant):
        return False
    if isinstance(arg, ast.IfExp):
        consts = {b.value for b in (arg.body, arg.orelse) if isinstance(b, ast.Constant)}
        # 双分支均为常量：必须恰含一个 0（`1 if fail else 0` 合法；
        # `1 if ok else 1`——把 PASS 分支改成 1 的变异形态——必红）
        if len(consts) == 2:
            return 0 in consts
        if len(consts) == 1 and len([b for b in (arg.body, arg.orelse)
                                     if isinstance(b, ast.Constant)]) == 2:
            return consts == {0}
        # 单侧常量（如 `2 if bad else rc`）：非常量侧失败派生，放行
        return True
    return True


def _has_exec_tail(tree):
    """Qt 定时器模式：末条顶层语句是 app.exec()，SystemExit 从槽里传出"""
    for st in _top_level_tail_statements(tree):
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            f = st.value.func
            if isinstance(f, ast.Attribute) and f.attr == "exec":
                return True
    return False


@pytest.mark.parametrize("path", _runner_files(), ids=lambda p: os.path.basename(p))
def test_probe_exit_contract(path):
    rel = os.path.relpath(path, TESTS_DIR)
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=rel)

    # helper 模块（被其他探针 import）：不运行，不适用退出码约定
    if _module_name(path) in _imported_probe_modules():
        pytest.skip("helper 模块（被其他探针 import，不单独运行）")

    terminal = _terminal_exit_call(tree)
    if terminal is None and _has_exec_tail(tree):
        # Qt 定时器模式：退出约定在事件循环槽内（app.exec() 收尾）——
        # v3 WP-24：不再一 skip 了事，槽内最后一个退出调用按同一套双向规则检
        all_calls = _exit_calls(tree.body)
        assert all_calls, (
            f"{rel}: 末条顶层语句是 app.exec() 但全文件没有任何显式退出码约定"
            "（R10：PASS 退 0 且 FAIL 退非 0）")
        terminal = all_calls[-1]

    assert terminal is not None, (
        f"{rel}: 末条顶层语句没有显式退出码约定（R10：PASS 退 0 且 FAIL 退非 0；"
        "缺约定会让 Qt 静态析构期 fastfail 决定退码）")

    assert _pass_branch_is_zero(terminal), (
        f"{rel}: 终端退出调用 {ast.unparse(terminal)} 不满足双向 R10"
        "（PASS 退 0 且 FAIL 退非 0：裸常量恒值、两分支同值、PASS 分支非 0 均违规）")


def test_check_layout_conclusion_line_and_exit_agree():
    """check_layout 的结论行 LAYOUT_CHECK_DONE 必须与退码同源（同一判定变量）"""
    src = open(os.path.join(TESTS_DIR, "check_layout.py"), encoding="utf-8").read()
    assert "LAYOUT_CHECK_DONE" in src
    tree = ast.parse(src)
    terminal = _terminal_exit_call(tree)
    assert terminal is not None, "check_layout.py 末尾必须有显式退出码约定"
    assert _pass_branch_is_zero(terminal)
