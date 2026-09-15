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


def test_all_relative_imports_resolve():
    bad = []
    for dirpath, _dirs, files in os.walk(APP):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.level:
                    continue
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
                pkg_names = _pkg_top_level_names(base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not (_is_module(base, alias.name) or alias.name in pkg_names):
                        bad.append(f"{path}:{node.lineno} "
                                   f"from {'.' * node.level} import {alias.name}")
    assert not bad, "相对导入目标不存在（运行期必 ImportError）：" + " | ".join(bad)
