#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前缀卫生 lint（W0.1 / 测试方案 E0.2）：把「chapter_header 静默丢参」类 bug 变成不可能复发

三层检查：
  A. AST 层——解析 app/core/stages.py（+ app/core/co_writing.py），找所有
     `<prompts模块>.<NAME>.format(...)` 调用：keywords 含 chapter_header= 的，
     断言 app.prompts 对应 NAME 模板字符串含 "{chapter_header}"；
     含 project_header= 的同理。（0.18.4 七处 .format() 静默丢参 bug 的直接防线）
  B. 动态确定性层——tempfile 造最小项目（题材定位.md 含金手指约束条款/全局红线/
     授权自创清单三小节 + 设定/正则.md，最小文件集对齐 app/core/shared_prefix.py
     的 _SOURCES），连续两次 project_header / chapter_header(proj, 1) 逐字节 diff。
  C. 动态值扫描层——读 app/core/shared_prefix.py 源码，正则扫描禁用 tokens
     （datetime / time.time / uuid / random / now(——前缀里不允许任何随跑次漂移的值）。

检查失败 exit 1 并打印违规清单；全过 exit 0 打印全绿。
用法：
  python scripts/prefix_lint.py
  python scripts/prefix_lint.py --no-dynamic    # 只跑 AST + 扫描层（不 import app）
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import sys
import tempfile

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A 层：要扫的调用方文件（app/core 下消费 prompts 模板的两个主文件）
LINT_FILES = (
    "app/core/stages.py",
    "app/core/co_writing.py",
)
HEADER_KEYWORDS = ("chapter_header", "project_header")

# C 层：两层前缀构造函数（shared_prefix.py）里禁止出现的动态值来源
SCAN_FILE = os.path.join("app", "core", "shared_prefix.py")
FORBIDDEN_RE = re.compile(r"datetime|time\.time|uuid|random|now\(")


# ---------- A 层：AST 模板占位符断言 ----------

def _prompts_aliases(tree: ast.AST) -> set:
    """收集本文件内绑定到 app.prompts 包的本地别名。

    stages.py 是 `from .. import project, prompts, ...`（ImportFrom module=None level=2）；
    co_writing.py 在函数内 `from .. import prompts`；也兼容 `from app import prompts`
    与 `import app.prompts as prompts`。
    """
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            tail = mod.split(".")[-1] if mod else ""
            for a in node.names:
                local = a.asname or a.name
                if tail == "prompts" or (node.level and a.name == "prompts") \
                        or ((mod == "app" or mod.startswith("app.")) and a.name == "prompts"):
                    aliases.add(local)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "app.prompts" or a.name.startswith("app.prompts."):
                    aliases.add(a.asname or a.name.split(".")[0] if a.asname else "prompts")
    return aliases


def find_format_calls(tree: ast.AST, aliases: set) -> list:
    """找 `<prompts别名>.<NAME>.format(...)` 调用 → [(lineno, NAME, [keyword...])]"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "format"):
            continue
        v = f.value
        if not (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)):
            continue
        if v.value.id not in aliases:
            continue
        out.append((node.lineno, v.attr, [k.arg for k in node.keywords if k.arg]))
    return out


def check_file(path: str, prompts_mod) -> list:
    """单文件 AST 检查 → 违规列表 [(file, line, NAME, keyword, 说明)]"""
    violations = []
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    aliases = _prompts_aliases(tree)
    for lineno, name, kws in find_format_calls(tree, aliases):
        tmpl = getattr(prompts_mod, name, None)
        if not isinstance(tmpl, str):
            violations.append((path, lineno, name, "",
                               "模板在 app.prompts 取不到（getattr 失败）——人工确认导出"))
            continue
        for kw in HEADER_KEYWORDS:
            if kw in kws and ("{%s}" % kw) not in tmpl:
                violations.append((
                    path, lineno, name, kw,
                    ".format(%s=...) 但模板缺 {%s} 占位符——该参数被 .format() 静默丢弃"
                    "（0.18.4 七处同类 bug 模式）" % (kw, kw)))
    return violations


# ---------- B 层：动态确定性（两次生成逐字节 diff） ----------

def _make_min_project(tmp_root: str) -> str:
    """最小项目：仅 shared_prefix._SOURCES 依赖的两个源文件（世界书缺失走 '-' 指纹）"""
    proj = os.path.join(tmp_root, "lint_proj")
    os.makedirs(os.path.join(proj, "设定"), exist_ok=True)
    with open(os.path.join(proj, "设定", "题材定位.md"), "w", encoding="utf-8") as f:
        f.write("# 题材定位（prefix_lint 最小项目）\n\n"
                "## 核心设定\n主角获得一支能改写命运的笔。\n\n"
                "### 金手指约束条款\n- 每次改写必须付出等价代价。\n"
                "- 不可改写已发生的历史。\n\n"
                "### 全局红线\n- 全书不出现真实政治人物。\n"
                "- 不描写详细自杀过程。\n\n"
                "### 授权自创清单\n- 「笔灵」为授权自创设定。\n")
    with open(os.path.join(proj, "设定", "正则.md"), "w", encoding="utf-8") as f:
        f.write("# 正则契约（must 全文）\n\n- 每章不少于 1800 字。\n")
    return proj


def check_determinism(tmp_root: str = "") -> list:
    """project_header / chapter_header 各生成两次（清缓存强制重算）逐字节 diff"""
    made = False
    if not tmp_root:
        tmp_root = tempfile.mkdtemp(prefix="qbn_prefix_lint_")
        made = True
    violations = []
    try:
        from app.core import shared_prefix as sp
        proj = _make_min_project(tmp_root)
        pairs = (("project_header", sp.project_header, (proj,)),
                 ("chapter_header", sp.chapter_header, (proj, 1)))
        for label, fn, argv in pairs:
            if hasattr(sp, "_header_cached"):
                sp._header_cached.cache_clear()
            a = fn(*argv)
            if hasattr(sp, "_header_cached"):
                sp._header_cached.cache_clear()
            b = fn(*argv)
            if a != b:
                violations.append((
                    "app/core/shared_prefix.py", 0, label, "",
                    "两次生成不一致（len %d vs %d）——前缀存在动态值/顺序化输出，缓存命中率杀手"
                    % (len(a), len(b))))
    finally:
        if made:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return violations


# ---------- C 层：动态值扫描 ----------

def scan_dynamic_values(path: str) -> list:
    """shared_prefix 源码禁用 token 扫描（跳过纯 # 注释行，docstring 照扫）"""
    violations = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.lstrip().startswith("#"):
                continue
            m = FORBIDDEN_RE.search(line)
            if m:
                violations.append((path, i, m.group(0), "",
                                   "前缀构造函数出现禁用动态值 token: %s ｜ %s"
                                   % (m.group(0), line.strip()[:80])))
    return violations


# ---------- 入口 ----------

def run_lint(root: str = ROOT, dynamic: bool = True) -> list:
    """跑全部三层 → 违规列表（空 = 全绿）"""
    violations = []
    for rel in LINT_FILES:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            violations.append((p, 0, "", "", "待扫描文件不存在"))
            continue
        violations += check_file(p, _load_prompts_mod(root))
    violations += scan_dynamic_values(os.path.join(root, SCAN_FILE))
    if dynamic:
        sys.path.insert(0, root)   # 与 check_file 的 app 导入共用
        violations += check_determinism()
    return violations


def _load_prompts_mod(root: str):
    """模板定位：import app.prompts 后 getattr（失败给 None，check_file 逐处报警）"""
    cache = getattr(_load_prompts_mod, "_cache", None)
    if cache is not None:
        return cache
    sys.path.insert(0, root)
    try:
        import app.prompts as prompts_mod
    except Exception as e:  # noqa: BLE001  报违规而不是崩掉（lint 要能跑在任何环境）
        print("[prefix_lint] 警告：app.prompts 导入失败（%s），模板断言按缺失处理" % e)
        prompts_mod = None
    _load_prompts_mod._cache = prompts_mod
    return prompts_mod


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="prefix_lint.py",
        description="前缀卫生 lint（W0.1/E0.2）：模板占位符断言 + 序列化确定性 + 动态值扫描")
    ap.add_argument("--no-dynamic", dest="no_dynamic", action="store_true",
                    help="跳过动态确定性层（不 import app，纯静态环境用）")
    args = ap.parse_args(argv)

    violations = run_lint(ROOT, dynamic=not args.no_dynamic)
    rel = lambda p: os.path.relpath(p, ROOT) if p and os.path.isabs(p) else (p or "")
    if violations:
        print("prefix_lint：%d 处违规" % len(violations))
        for path, line, name, kw, why in violations:
            loc = "%s:%s" % (rel(path), line or "-")
            tag = ("%s(%s)" % (name, kw)) if kw else (name or "-")
            print("  %s  %s\n    %s" % (loc, tag, why))
        return 1
    print("prefix_lint：全绿——模板占位符断言 / 两次生成逐字节一致 / 无禁用动态值")
    return 0


if __name__ == "__main__":
    sys.exit(main())
