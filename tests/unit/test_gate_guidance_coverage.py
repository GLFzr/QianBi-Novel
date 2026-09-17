# -*- coding: utf-8 -*-
"""WP-22 / R13：九门停靠详情的覆盖面锁。

v3 复验变异：`g = self.GATE_GUIDANCE.get(key, {})` 改成 `g = {}` ⇒ 986 全绿——
文案表再完整、gate() 不引用它就等于没有。本锁三层：
① GATE_GUIDANCE 键集必须与 config.WIRED_GATES 九门**恰好相等**（多一门少一门红）；
② 每门的「拦哪条 / 继续后果 / 回退后果」三条文案必须非空非占位；
③ gate() 函数体必须真实引用 GATE_GUIDANCE（`g = {}` 式绕过路径在此红）。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.config import WIRED_GATES  # noqa: E402

ORCH = os.path.join(ROOT, "app", "core", "orchestrator.py")
_FIELDS = ("blocked", "continue", "rollback")


def _orch_tree():
    return ast.parse(open(ORCH, encoding="utf-8").read())


def _guidance_dict():
    """从 orchestrator 的 Orchestrator 类体 AST 取 GATE_GUIDANCE 字面量（派生，非手抄）"""
    tree = _orch_tree()
    holders = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    holders += [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    for holder in holders:
        for node in holder.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "GATE_GUIDANCE" for t in node.targets):
                assert isinstance(node.value, ast.Dict), "GATE_GUIDANCE 不是字面量 dict"
                out = {}
                for k, v in zip(node.value.keys, node.value.values):
                    assert isinstance(k, ast.Constant), "GATE_GUIDANCE 键必须是字面量"
                    entry = {}
                    assert isinstance(v, ast.Dict), f"GATE_GUIDANCE[{k.value}] 必须是字面量 dict"
                    for fk, fv in zip(v.keys, v.values):
                        assert isinstance(fk, ast.Constant) and isinstance(fv, ast.Constant), (
                            f"GATE_GUIDANCE[{k.value}] 的字段必须是字面量")
                        entry[fk.value] = fv.value
                    out[k.value] = entry
                return out
    raise AssertionError("orchestrator 找不到 GATE_GUIDANCE 字面量定义（类体/模块层均无）")


def test_guidance_covers_exactly_the_nine_gates():
    g = _guidance_dict()
    assert set(g) == set(WIRED_GATES), (
        f"GATE_GUIDANCE 键集与九门不一致：多 {sorted(set(g) - set(WIRED_GATES))}，"
        f"少 {sorted(set(WIRED_GATES) - set(g))}——多挂空指导的门与漏掉的门同样违规（WP-22①）")


def test_guidance_each_gate_has_three_nonempty_texts():
    g = _guidance_dict()
    thin = []
    for key, entry in sorted(g.items()):
        for f in _FIELDS:
            val = str(entry.get(f, "")).strip()
            if len(val) < 6:   # 「拦哪条/继续/回退」每条至少是一句人话
                thin.append(f"{key}.{f}={val!r}")
    assert not thin, (
        "九门指导文案缺条/过薄（删任意一门的任一条文案即在此红，WP-22②）：" + "；".join(thin))


def test_gate_method_actually_uses_guidance():
    """R13 覆盖面锁：gate() 不引用 GATE_GUIDANCE ⇒ 详情恒空。
    v3 变异 `g = self.GATE_GUIDANCE.get(key, {}) → g = {}` 在这条红。"""
    tree = _orch_tree()
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "gate")
    body_src = ast.get_source_segment(open(ORCH, encoding="utf-8").read(), fn) or ""
    assert "GATE_GUIDANCE" in body_src, (
        "orchestrator.gate() 不再引用 GATE_GUIDANCE——九门停靠详情被整段架空"
        "（`g = {}` 式绕过路径，WP-22③/R13）")
    assert "sigGateDetail.emit" in body_src, (
        "orchestrator.gate() 不再发射 sigGateDetail——九门详情信号被摘除（WP-22③）")
