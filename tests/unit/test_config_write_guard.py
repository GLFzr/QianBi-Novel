# -*- coding: utf-8 -*-
"""§7.3 护栏：写盘↔写内存一致性（§11.1「写盘不写内存」家族门禁）

背景：#15（setAutoGate）→ L1-01（agent set_setting）→ setOnboarded / setTelemetryEnabled /
_patch_updates——同族七处发作。病根：``cfg_mod.save_config(新字典)`` 落了盘，但共享的
``self.cfg``（orchestrator / main.py / 设置页持有的同一引用）没动 ⇒ 本会话内不生效、
回执说谎。本门禁用 AST 扫 app/**.py 里全部 ``*.save_config(...)`` 调用：

- 实参是 ``…cfg`` 属性链（self.cfg / self.bridge.cfg）→ 合规；
- 实参是名字 ``cfg`` → 仅当 ①所在函数内有 ``self.cfg = cfg`` 的认可重绑
  （applyModelPreset 范式），或 ②``cfg`` 是函数形参且函数内**没有** ``cfg = load_config()``
  的换新字典动作（agent_tools 的共享下发契约）→ 合规；
- 其余一律列出并 fail——第七处、第八处别再长出来。

范围说明：只扫 Attribute 形态（``cfg_mod.save_config``）；app/config.py 自身的模块级
持久化（save_config(DEFAULT_CONFIG) 等）不在本族语义内。
"""
import ast
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/unit → 仓库根


def _arg_repr(a: ast.expr) -> str:
    if isinstance(a, ast.Attribute):
        tail = []
        cur = a
        while isinstance(cur, ast.Attribute):
            tail.append(cur.attr)
            cur = cur.value
        tail.append(getattr(cur, "id", "?"))
        return ".".join(reversed(tail))
    if isinstance(a, ast.Name):
        return a.id
    if isinstance(a, ast.Call):
        f = a.func
        return "CALL(%s)" % getattr(f, "id", getattr(f, "attr", "?"))
    return type(a).__name__


def _check_function(fn, arg_name: str) -> str:
    """返回 'ok' 或违规原因。fn 为包含该调用的最近函数节点（可为 None=模块级）"""
    if fn is None:
        return "模块级 save_config(%s)：无共享语义上下文" % arg_name
    has_params = any(a.arg == arg_name for a in getattr(fn, "args", ast.arguments()).args)
    rebind_self_cfg = False
    fresh_load = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "self" and t.attr == "cfg"
                        and isinstance(node.value, ast.Name) and node.value.id == arg_name):
                    rebind_self_cfg = True
                if isinstance(t, ast.Name) and t.id == arg_name and \
                        isinstance(node.value, ast.Call):
                    fresh_load = True
    if rebind_self_cfg:
        return "ok"          # 认可范式：换新字典后立刻回写共享引用（applyModelPreset）
    if has_params and not fresh_load:
        return "ok"          # 共享下发契约：cfg 形参来自 bridge 按引用传入
    if fresh_load:
        return "%s 在函数内被 load_config() 换新字典后落盘——写盘不写内存（§11.1）" % arg_name
    return "save_config(%s)：非共享引用且无认可范式" % arg_name


def test_save_config_always_writes_shared_cfg():
    violations = []
    for root, dirs, files in os.walk(os.path.join(ROOT, "app")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=rel)

            # 先收集 (函数节点, 其行号区间)
            funcs = [(f, getattr(f, "lineno", 0), getattr(f, "end_lineno", 0))
                     for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]

            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "save_config" and node.args):
                    continue
                arg = node.args[0]
                arg_s = _arg_repr(arg)
                if arg_s.endswith(".cfg"):
                    continue                      # 共享引用：合规
                fn = next((f for f, lo, hi in funcs if lo <= node.lineno <= hi), None)
                verdict = (_check_function(fn, arg_s)
                           if isinstance(arg, ast.Name) else
                           "save_config(实参=%s)：非共享引用" % arg_s)
                if verdict != "ok":
                    violations.append("%s:%d  %s" % (rel, node.lineno, verdict))
    assert not violations, "写盘不写内存家族复发（§11.1 门禁）：\n" + "\n".join(violations)


def test_set_setting_writes_shared_cfg(tmp_path):
    """L1-01 语义钉：execute('set_setting') 必须改调用方传入的共享字典"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from app.core import agent_tools
    from app import project
    proj = project.create_project(str(tmp_path), "护栏书")
    shared = {"gates": {}, "writing": {}}
    res = agent_tools.execute("set_setting", {"key": "审校", "on": True},
                              proj, shared, pipeline_running=False)
    assert res.get("ok") is True
    assert shared["gates"]["review_enabled"] is True, \
        "共享字典未被改——写盘不写内存复发（L1-01）"


def test_clear_chapter_step_scoped_to_chapter(tmp_path):
    """L1-02 语义钉：清 A 章断点不得动 B 章断点"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from app import project
    from app.core import state as st
    proj = project.create_project(str(tmp_path), "断点守卫")
    st.save_chapter_step(proj, 30, "draft", draft_path="x.md")
    st.clear_chapter_step(proj, 12)            # 重写第 12 章：不得动第 30 章断点
    raw = st.load_state(proj).get("chapter_step")
    assert raw and json.loads(raw)["num"] == 30, "跨章误清断点（L1-02 复发）"
    st.clear_chapter_step(proj, 30)            # 清对的章：真清
    assert st.load_state(proj).get("chapter_step") == ""


def test_need_human_read_write_same_function(tmp_path):
    """L1-14 语义钉：mark（写）与 bridge 侧查询（读）必须同一口径"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from app import project
    from app.core import state as st
    proj = project.create_project(str(tmp_path), "口径书")
    state = st.load_state(proj)
    st.mark_chapter_need_human(proj, state, 7)
    assert st.is_chapter_need_human(st.load_state(proj), 7) is True
    assert st.is_chapter_need_human(st.load_state(proj), 8) is False
    # bridge 侧 entries 构建走的是同一函数（原直读 state 键）
    from app.ui import bridge as bridge_mod
    state2 = st.load_state(proj)
    state2["review_findings"] = {"7": {"blocking": ["x"], "verdict": "REJECT"}}
    entries = bridge_mod.NeedsFixModel.collect(state2) if hasattr(
        bridge_mod, "NeedsFixModel") else None
    # 若 collect 不在模型上，直接验证纯函数路径（防 L1-14 退化：直读键绕过函数）
    repo = ROOT
    src = open(os.path.join(repo, "app", "ui", "bridge.py"), encoding="utf-8").read()
    assert 'state.get("chapter_need_human")' not in src, \
        "bridge 绕过 is_chapter_need_human 直读 state 键（L1-14 复发）"
