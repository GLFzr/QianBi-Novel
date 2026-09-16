# -*- coding: utf-8 -*-
"""L2-23 同类 Bug 护栏：app/ 内相对导入的目标必须真实存在。

事故留档：bridge.py 曾写 `from .core import volume_session`（bridge 在 app/ui/
下 ⇒ app.ui.core 不存在）⇒ 必然 ImportError，被 except 吞掉，卷完成 toast
从未发出过一次。此护栏静态解析全部相对导入，目标模块不存在即红。

注意 `from pkg import X` 的 X 既可以是子模块，也可以是 pkg/__init__.py 里
定义或导入的名字（如 __version__），两者都认，避免误报。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "app")


def _is_module(base, name):
    return (os.path.isfile(os.path.join(base, name + ".py"))
            or os.path.isdir(os.path.join(base, name)))


def _pkg_top_level_names(base):
    """base/__init__.py 顶层定义或导入的名字集合（语法层，不执行）。"""
    names = set()
    init = os.path.join(base, "__init__.py")
    if not os.path.isfile(init):
        return names
    try:
        tree = ast.parse(open(init, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return names
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def _pkg_top_level_names(base):
    """base/__init__.py 顶层定义或导入的名字集合（语法层，不执行）。"""
    names = set()
    init = os.path.join(base, "__init__.py")
    if not os.path.isfile(init):
        return names
    return _file_top_level_names(init)


def _file_top_level_names(path):
    """单个 .py 文件顶层（含模块级 Try/If 分支内，不含函数/类体）定义或导入的名字。
    WP-14：旧实现只读 __init__.py 且不下钻 Try——目标模块条件导入的名字会被误判
    为不存在。"""
    names = set()
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return names

    def collect(body):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                names.add(n.target.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, (ast.Try, ast.If)):
                collect(n.body)
                collect(n.orelse)
                if isinstance(n, ast.Try):
                    for h in n.handlers:
                        collect(h.body)

    collect(tree.body)
    return names


def _importerror_guarded_spans(tree):
    """全部带 ImportError/ModuleNotFoundError 处器的 Try 行跨度。
    WP-14：条件导入（try: from x import y / except ImportError: 回退）本身有守卫，
    目标暂缺不算事故——白名单化而非误报红。"""
    spans = []
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        for h in t.handlers:
            htype = h.type
            names = set()
            if htype is not None:
                for x in ast.walk(htype):
                    if isinstance(x, ast.Name) and x.id in ("ImportError", "ModuleNotFoundError"):
                        names.add(x.id)
                    elif isinstance(x, ast.Tuple):
                        for e in x.elts:
                            if isinstance(e, ast.Name) and e.id in ("ImportError", "ModuleNotFoundError"):
                                names.add(e.id)
            if names:
                spans.append((t.lineno, getattr(t, "end_lineno", t.lineno)))
                break
    return spans


def test_all_relative_imports_resolve():
    bad = []
    for dirpath, _dirs, files in os.walk(APP):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
            guarded = _importerror_guarded_spans(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.level:
                    continue
                if any(s <= node.lineno <= e for s, e in guarded):
                    continue  # 条件导入有 ImportError 守卫，白名单放行
                base = os.path.dirname(path)
                for _ in range(node.level - 1):
                    base = os.path.dirname(base)
                if node.module:
                    parts = node.module.split(".")
                    ok = _is_module(base, parts[0])
                    if ok and len(parts) > 1:
                        sub = os.path.join(base, *parts[:-1])
                        ok = _is_module(sub, parts[-1])
                    if not ok:
                        bad.append(f"{path}:{node.lineno} from {'.' * node.level}{node.module}")
                        continue
                    # WP-14 补牙：校验被导入符号真实存在于目标模块顶层
                    #（事故原型：from ..core import volume_sessionXX——模块在、
                    # 符号不在，len(parts)==1 时旧实现压根不查 names ⇒ 永绿）
                    target_dir = os.path.join(base, *parts[:-1]) if len(parts) > 1 else base
                    target_name = parts[-1]
                    target_path = os.path.join(target_dir, target_name)
                    if os.path.isdir(target_path):
                        avail = _pkg_top_level_names(target_path)
                        pkg_dir = target_path  # 目标是包：名字也可来自其子模块
                    else:
                        avail = _file_top_level_names(target_path + ".py")
                        pkg_dir = target_dir
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        if not (alias.name in avail or _is_module(pkg_dir, alias.name)):
                            bad.append(
                                f"{path}:{node.lineno} from {'.' * node.level}{node.module} "
                                f"import {alias.name} —— 符号不存在于目标模块顶层"
                                "（运行期必 ImportError，try 守卫缺失时被吞成静默故障）")
                    continue
                pkg_names = _pkg_top_level_names(base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not (_is_module(base, alias.name) or alias.name in pkg_names):
                        bad.append(f"{path}:{node.lineno} "
                                   f"from {'.' * node.level} import {alias.name}")
    assert not bad, "相对导入目标不存在（运行期必 ImportError）：" + " | ".join(bad)
