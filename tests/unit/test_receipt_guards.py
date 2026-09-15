# -*- coding: utf-8 -*-
"""§7.3 护栏固化（阶段5，WP-05 全面返修）：
① 能力清单↔注册表对账——帮助文本必须列出全部注册工具（含 UI_TOOLS）；
   每个工具必须有执行体；UI 工具必须在 bridge._ui_tool_dispatch 里有真实派发
   字面量（「注册了但无路径可触发」即红，L1-07 家族）。
② 用户可见文案里的 /命令 必须在注册表里（QML 字符串字面量 + README）。
③ 回执三态静态断言——bridge 里每个 toast「已 …」成功文案，其所在函数必须包含
   至少一个落盘/生效证据调用；失败路径必须可见（禁止 except: pass 后直接成功回执）。

恒真事故留档（WP-05 实证）：
- EVIDENCE_CALLEES 曾因缺逗号把 "setText"/"stage_params"、"normpath"/"snapshot"
  粘成两个死名，setText 从未真正在证据集里；
- except:pass 检查曾去 Try.body 找 ExceptHandler（处理器实际挂在 Try.handlers）
  ⇒ parent_body 恒 None ⇒ 该测试不可能失败。
两台都已修成真护栏并做变异验证（见提交信息）。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# 生效证据白名单：键=函数名，值=为什么它算「写/生效」。只认真实语义：
# 纯读（read_file/list_chapters/exists）、纯刷新（append/update/start/run/
# refreshQueue）、纯计算（normpath/toLocalFile）一律不收——把空函数当"生效"
# 会让门禁退化成摆设。WP-05 实证后剔除的正是这批。
EVIDENCE_CALLEES = {
    # —— 配置/状态落盘 ——
    "save_config": "写应用配置盘",
    "save_state": "写项目流水线状态盘",
    "_save_state": "写项目流水线状态盘（别名）",
    "_cw_save_state": "写共写阶段状态盘",
    "migrate_mode": "配置迁移写盘",
    "apply_preset": "预设写入配置",
    "_patch_updates": "写 updates 配置域（save_config 链，WP-05 补）",
    "record_forced_lock": "强锁登记写状态",
    "set_chapter_locked": "终稿锁状态写盘",
    "resolve_gate": "决策门裁决落状态",
    # —— 项目文件写/删（破坏性也算生效） ——
    "write_file": "项目文件写入",
    "save": "通用保存",
    "write": "文件句柄写入",
    "saveChapterText": "正文落盘+读回验证",
    "save_idea_info": "想法信息落盘",
    "write_idea_info": "想法信息落盘（别名）",
    "add_idea": "创作笔记写入",
    "discard_all_drafts": "草稿全清（破坏性落盘）",
    "discard_draft": "草稿删除（破坏性落盘）",
    "clear_drafts": "草稿清理（破坏性落盘）",
    "clear_drafts_all": "草稿全清（破坏性落盘）",
    "delete_secret": "密钥文件删除",
    "_write_store": "批注库落盘",
    "transcript_append": "共写转写追加落盘",
    "record": "事件/遥测记录器（本地落点）",
    "snapshot": "版本快照落盘",
    "copy2": "归档复制落盘",
    "zipfile": "打包写 zip",
    # —— 导出/下载（真实产物落盘） ——
    "export": "导出动作",
    "export_project": "导出器落盘 txt/epub（WP-05 补）",
    "export_preset": "预设导出器落盘（WP-05 补）",
    "export_beta_pack": "公测包落盘",
    "download": "下载器（网络动作+文件落盘）",
    "sha256": "指纹校验",
    "sha256_file": "下载物指纹复核（WP-05 补：安装回执前槽内亲算）",
    "verify": "校验",
    # —— 流程/外部真实效果 ——
    "advance": "门/步骤推进（状态变更）",
    "execute": "agent_tools 派发真实工具",
    "pause": "流水线暂停（流程序真实变更）",
    "resume": "流水线继续（流程序真实变更）",
    "stop": "流水线停止（流程序真实变更）",
    "chat": "LLM 调用（花费真实发生）",
    "register": "更新器注册（外部效果）",
    "install": "更新安装（外部效果）",
    "setClip": "剪贴板写入即生效",
    "set_clipboard": "剪贴板写入即生效",
    "setText": "剪贴板/控件最终写入（QClipboard.setText 即生效；WP-05 修逗号后真正生效）",
    "openPath": "打开目录/文件（外部效果）",
    "openLogDir": "打开日志目录（外部效果）",
    "openDataDir": "打开数据目录（外部效果）",
    "openUrl": "打开外部链接（外部效果）",
    # —— 内存生效类（界面/模型态，无盘语义但状态真实切换） ——
    "set_enabled": "控件/动作启停（界面态生效）",
    "set_items": "模型整体重建（界面态生效）",
    "reset": "模型重置（界面态生效）",
    "refreshQueue": "队列模型重建（界面态生效）",
    "cwProsePolished": "共写去味信号驱动编辑器（内存生效）",
}
EXEMPT = {
    # 豁免只能在「语义确实成立」时开并写明理由；不许用豁免绕过自己写错的代码。
    # WP-05 撤销 copyText 豁免：其理由建立在缺逗号导致 setText 不在证据集上，
    # 逗号修复后 setText 是真证据，无需豁免。
    ("bridge.py", "_on_cw_deslop_done"): "去味效果在工作副本（cwProsePolished 信号驱动编辑器），内存生效类",
}


def test_help_text_lists_all_registered_tools():
    from app.core import agent_tools as at
    text = at.help_text()
    for name, tool in at.TOOLS.items():
        assert tool["label"] in text, f"帮助文本缺工具「{name}:{tool['label']}」——能力清单与注册表脱节（L1-04/07 家族护栏）"
    for name, tool in at.UI_TOOLS.items():
        assert tool["label"] in text, f"帮助文本缺 UI 工具「{name}:{tool['label']}」"


def test_every_tool_dispatchable():
    """有名无身防线：UI 工具必须在 _ui_tool_dispatch 派发面有字面量（L1-07 家族）"""
    from app.core import agent_tools as at
    bridge_src = open(os.path.join(ROOT, "app", "ui", "bridge.py"), encoding="utf-8").read()
    m = re.search(r"def _ui_tool_dispatch\(.*?(?=\n    def |\nclass |\Z)", bridge_src, re.S)
    assert m, "bridge._ui_tool_dispatch 派发面消失"
    dispatch_src = m.group(0)
    for name, tool in list(at.TOOLS.items()) + list(at.UI_TOOLS.items()):
        if tool.get("level") == "ui":
            assert name in at.UI_TOOLS, f"UI 工具 {name} 必须注册在 UI_TOOLS（bridge 派发面）"
        else:
            assert callable(tool.get("fn")), f"工具 {name} 无执行体（有名无身，L1-11 同族）"
        if name in at.UI_TOOLS:
            assert f'"{name}"' in dispatch_src, (
                f"UI 工具 {name} 注册了但派发面无此字面量——无路径可触发（L1-07 同族）")


# ---- 回执三态 ----

def _enclosing_functions(tree):
    funcs = []
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(f)
    return funcs


def _bridge_tree_and_src():
    path = os.path.join(ROOT, "app", "ui", "bridge.py")
    src = open(path, encoding="utf-8").read()
    return ast.parse(src), src


def test_success_toasts_have_effect_evidence():
    tree, src = _bridge_tree_and_src()
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
        if (os.path.basename("app/ui/bridge.py"), fn.name) in EXEMPT:
            continue
        callees = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                   for c in ast.walk(fn) if isinstance(c, ast.Call)}
        if not (callees & set(EVIDENCE_CALLEES)):
            violations.append(f"bridge.py:{node.lineno} 「{msg_src[:50]}…」所在函数 {fn.name} 无落盘/生效证据调用")
    assert not violations, "回执三态违规（宣称「已X」但无生效证据）：" + " | ".join(violations)


def test_no_silent_pass_before_success_claim():
    """except: pass 后同层紧跟成功回执 = 说谎（N-05 家族静态面）。

    WP-05 修正：ExceptHandler 挂在 Try.handlers（不是 Try.body，更不在
    FunctionDef.body 里被 walk 到）——旧实现永不命中 ⇒ 恒真。现用父指针
    定位 except 所在 Try，再取该 Try 所在语句列表的同层后续兄弟。
    """
    tree, _src = _bridge_tree_and_src()
    parent = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[child] = p
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)):
            continue
        try_node = parent.get(node)
        if not isinstance(try_node, ast.Try):
            continue
        holder = parent.get(try_node)
        if holder is None:
            continue
        siblings_after = []
        for _fieldname, value in ast.iter_fields(holder):
            if isinstance(value, list) and try_node in value:
                siblings_after = value[value.index(try_node) + 1:]
                break
        for st_ in siblings_after:
            for c in ast.walk(st_):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "emit" and c.args
                        and isinstance(c.args[0], ast.Constant) and c.args[0].value == "ok"):
                    bad.append(f"bridge.py:{c.lineno} except:pass 后直接成功回执")
    assert not bad, "静默吞后说谎：" + " | ".join(bad)


def test_user_facing_slash_commands_are_registered():
    """用户可见文案里的 /命令 必须在注册表里（QML 双引号字面量 + README）。"""
    from app.core import agent_tools as at
    registry = set(at.TOOLS) | set(at.UI_TOOLS)
    # 已知非命令误报：HTML 闭合标签与资源路径片段
    allowlist = {"span", "models"}
    pat_cmd = re.compile(r"(?<![\w/.:])/([a-z][a-z_]{2,24})(?![\w/])")
    pat_str = re.compile(r'"([^"\n]*)"')
    found = {}
    qml_root = os.path.join(ROOT, "app", "ui", "qml")
    for dp, _dn, fns in os.walk(qml_root):
        for fn in fns:
            if not fn.endswith(".qml"):
                continue
            p = os.path.join(dp, fn)
            for s in pat_str.findall(open(p, encoding="utf-8", errors="replace").read()):
                for m in pat_cmd.findall(s):
                    found.setdefault(m, set()).add(fn)
    for readme in ("README.md", "README.en.md"):
        p = os.path.join(ROOT, readme)
        if os.path.isfile(p):
            for m in pat_cmd.findall(open(p, encoding="utf-8", errors="replace").read()):
                found.setdefault(m, set()).add(readme)
    unknown = {k: v for k, v in found.items() if k not in registry and k not in allowlist}
    assert not unknown, (
        f"界面/README 提到未注册的 /命令：{unknown}——要么注册成工具，要么改文案（L1-04 家族）")
