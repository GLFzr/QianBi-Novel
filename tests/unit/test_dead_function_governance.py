# -*- coding: utf-8 -*-
"""死函数治理守卫（B1/0.20.2）：app/ 模块级公共函数零文本引用 = 判红，除非在
conftest.DEAD_FUNC_EVIDENCE 登记复活理由。

口径与 scripts/static_scan.py 第 4 节一致：对全仓 .py + QML/JS + spec 文本做
裸名正则匹配（信号槽/字符串派发靠 QML 文本兜住）；引用数 <= def 行自身（<=1）
视为零调用。私有名（_ 开头）与魔术名不在此守卫射程。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from tests.unit.conftest import DEAD_FUNC_EVIDENCE  # noqa: E402

# SKIP_FILES：co_dialogue 的遗留条目已随 S2c 落地移除（clear_transcript 已删、
# 槽位常量已改引 slots），当前无豁免文件；机制保留给后续死函数批次使用。
SKIP_FILES = set()


def _collect_texts():
    """全仓文本（py + qml/js + spec）：裸名引用的判定语料。
    治理装置自身（本文件 + conftest 登记表）不入语料——豁免登记里出现的函数名
    不是调用方，计入会让豁免条目永远「过期」。"""
    chunks = []
    for base in ("app", "scripts", "tools", "tests"):
        for root, dirs, files in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "node_modules")]
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, ROOT).replace("\\", "/")
                if rel in SKIP_FILES:
                    continue
                if rel in ("tests/unit/conftest.py",
                           "tests/unit/test_dead_function_governance.py"):
                    continue
                if f.endswith((".py", ".qml", ".js")):
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        chunks.append(fh.read())
    spec = os.path.join(ROOT, "QianBi-Novel.spec")
    if os.path.isfile(spec):
        with open(spec, encoding="utf-8", errors="replace") as fh:
            chunks.append(fh.read())
    return chunks


def _public_module_funcs():
    """app/ 下全部模块级公共 def（不含 _ 私有/魔术/类方法），返回 [(name, loc)]"""
    out = []
    for root, dirs, files in os.walk(os.path.join(ROOT, "app")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, ROOT).replace("\\", "/")
            if rel.replace("\\", "/") in SKIP_FILES:
                continue
            with open(fp, encoding="utf-8", errors="replace") as fh:
                try:
                    tree = ast.parse(fh.read(), filename=fp)
                except SyntaxError:
                    continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        out.append((node.name, f"{rel}:{node.lineno}"))
    return out


def test_public_functions_have_callers_or_evidence(dead_func_evidence):
    texts = _collect_texts()
    bulk = "\n".join(texts)
    zero_ref = []
    for name, loc in _public_module_funcs():
        refs = len(re.findall(r"\b" + re.escape(name) + r"\b", bulk)) - 1  # 扣 def 行自身
        if refs <= 0:
            zero_ref.append((name, loc))
    unregistered = [(n, l) for n, l in zero_ref if n not in dead_func_evidence]
    stale = [n for n in dead_func_evidence if n not in {z[0] for z in zero_ref}]
    assert not unregistered, (
        "公共函数零调用且未在 conftest.DEAD_FUNC_EVIDENCE 登记（删掉或登记理由，见 CONTRIBUTING）："
        + "；".join(f"{n} @ {l}" for n, l in sorted(unregistered)))
    assert not stale, f"豁免登记已过期（函数已有调用方，请删除登记条目）：{sorted(stale)}"


def test_exempt_evidence_has_reasons(dead_func_evidence):
    """登记不许开空条目：每条豁免必须写明复活理由（哪张卡接上）"""
    for name, reason in dead_func_evidence.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 8, \
            f"豁免登记 {name} 的理由太薄：{reason!r}"
