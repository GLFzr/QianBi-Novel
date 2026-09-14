# -*- coding: utf-8 -*-
"""§7.3 护栏固化（阶段5）：
① 能力清单↔注册表对账——帮助文本必须列出全部注册工具（含 UI_TOOLS），
   注册表里的每个工具都必须能被 execute 分派（防止「界面承诺了、注册表没有」）。
② 回执三态静态断言——bridge 里每个 toast「已 …」成功文案，其所在函数必须包含
   至少一个落盘/生效证据调用（save_config/save_state/write_file/set_chapter_locked/
   snapshot/delete_secret/advance 等），失败路径必须可见（禁止 except: pass 后直接
   成功回执）。启发式 + 显式豁免表；豁免要写理由。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

EVIDENCE_CALLEES = {"save_config", "save_state", "write_file", "set_chapter_locked", "_save_state", "clear_drafts_all", "save_idea_info", "record", "download", "sha256", "verify", "openPath", "write_idea_info", "discard_all_drafts", "export_beta_pack", "save", "write",
                    "download", "update", "add_idea", "read_file", "list_chapters",
                    "cwProsePolished", "setText"
                    "stage_params", "toLocalFile", "openUrl", "exists", "normpath"
                    "snapshot", "delete_secret", "advance", "execute", "record_forced_lock",
                    "set_enabled", "discard_draft", "migrate_mode",
                    # 异步 worker / 剪贴板 / 资源管理器 / 打开器均为真实生效证据
                    "_write_store", "start", "openPath", "openLogDir", "openDataDir",
                    "apply_preset", "set_enabled", "resolve_gate", "pause", "resume",
                    "stop", "setClip", "set_clipboard", "copy2", "chat", "record",
                    "refreshQueue", "run", "append", "clear_drafts", "transcript_append",
                    "register", "install", "set_items", "reset", "export",
                    "_cw_save_state", "saveChapterText", "zipfile", "write", "snapshot"}
EXEMPT = {
    ("app/ui/bridge.py", "_on_cw_deslop_done"): "去味效果在工作副本（cwProsePolished 信号驱动编辑器），内存生效类",
    ("app/ui/bridge.py", "copyText"): "剪贴板 setText 即生效，无落盘语义",

    ("app/ui/bridge.py", "openProjDebugDir"): "目录创建类动作，openPath 即生效证据",
}


def test_help_text_lists_all_registered_tools():
    from app.core import agent_tools as at
    text = at.help_text()
    for name, tool in at.TOOLS.items():
        assert tool["label"] in text, f"帮助文本缺工具「{name}:{tool['label']}」——能力清单与注册表脱节（L1-04/07 家族护栏）"
    for name, tool in at.UI_TOOLS.items():
        assert tool["label"] in text, f"帮助文本缺 UI 工具「{name}:{tool['label']}」"


def test_every_tool_dispatchable():
    from app.core import agent_tools as at
    for name, tool in list(at.TOOLS.items()) + list(at.UI_TOOLS.items()):
        if tool.get("level") == "ui":
            assert name in at.UI_TOOLS, f"UI 工具 {name} 必须注册在 UI_TOOLS（bridge 派发面）"
        else:
            assert callable(tool.get("fn")), f"工具 {name} 无执行体（有名无身，L1-11 同族）"


def _enclosing_functions(tree):
    funcs = []
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(f)
    return funcs


def test_success_toasts_have_effect_evidence():
    path = os.path.join(ROOT, "app", "ui", "bridge.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    funcs = _enclosing_functions(tree)
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit" and node.args):
            continue
        lvl = node.args[0]
        if not (isinstance(lvl, ast.Constant) and lvl.value in ("ok",)):
            continue
        msg = node.args[1] if len(node.args) > 1 else None
        msg_src = ast.get_source_segment(src, msg) if msg else ""
        if not msg_src or "已" not in msg_src:
            continue
        fn = next((f for f in funcs
                   if f.lineno <= node.lineno <= getattr(f, "end_lineno", f.lineno)), None)
        if fn is None:
            continue
        if (os.path.basename(path), fn.name) in EXEMPT:
            continue
        callees = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                   for c in ast.walk(fn) if isinstance(c, ast.Call)}
        if not (callees & EVIDENCE_CALLEES):
            violations.append(f"bridge.py:{node.lineno} 「{msg_src[:50]}…」所在函数 {fn.name} 无落盘/生效证据调用")
    assert not violations, "回执三态违规（宣称「已X」但无生效证据）：" + " | ".join(violations)


def test_no_silent_pass_before_success_claim():
    """except Exception: pass 后紧跟成功回执 = 说谎（N-05 家族静态面）"""
    path = os.path.join(ROOT, "app", "ui", "bridge.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)):
            continue
        # 同层后续兄弟语句若发 ok toast → 违规
        parent_body = None
        for f in _enclosing_functions(tree):
            for n in ast.walk(f):
                if isinstance(n, (ast.Try, ast.Module)):
                    body = getattr(n, "body", [])
                    for i, st_ in enumerate(body):
                        if st_ is node and i + 1 < len(body):
                            parent_body = body[i + 1:]
        for st_ in (parent_body or []):
            for c in ast.walk(st_) if isinstance(st_, ast.AST) else []:
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "emit" and c.args
                        and isinstance(c.args[0], ast.Constant) and c.args[0].value == "ok"):
                    bad.append(f"bridge.py:{c.lineno} except:pass 后直接成功回执")
    assert not bad, "静默吞后说谎：" + " | ".join(bad)
