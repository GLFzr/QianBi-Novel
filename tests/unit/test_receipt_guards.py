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

扫描面注记（WP-07/N-05/N-36）：本护栏只解析 app/ui/bridge.py；app/core/stages.py
的 4 处同类「except: pass 后紧邻成功 log」站点在扫描面之外——扩面需先给 core 侧
定义「生效证据」名单（ctx.log 无落盘语义），已登记台账 N-36，不许算已覆盖。
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
    "requestInterruption": "worker 中断标志置位（运行态真实变更，pause/resume/stop 同族，WP-13）",
    "_drain_backflow_queue": "反哺队列起跑（后台 worker 串行执行并落盘，WP-13）",
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
    # —— WP-13 万能名判定后补收的真实效果名（回执实际有真效果，原先证据不在射程）——
    "attempt_unlock": "终稿锁解锁写项目状态盘（unlockChapter 的真实效果，WP-13）",
    "mark_chapter_need_human": "human 标记写状态盘（resolveReviewIssue ignore 支，WP-13）",
    "append_review_chain": "上游重做登记写状态盘（resolveReviewIssue upstream 支，WP-13）",
    "save_review_findings": "审校结论 v2 写状态盘（_on_cw_review_done，WP-13）",
    "_keep_aside": "坏批注库留证 .corrupt 落盘（_read_store 损坏隔离，WP-13）",
    "create_bundle": "报障包 zip 落盘（report_bundle.create_bundle 写完才发回执，WP-28）",
    "_make_bug_report": "报障包 zip 落盘（体内经 report_bundle.create_bundle，含正文/仅日志两档，A-9）",
    # —— 内存生效类（界面/模型态，无盘语义但状态真实切换） ——
    "cwProsePolished": "共写去味信号驱动编辑器（内存生效）",
}
# WP-13 万能名判定留档（③：纯读/纯刷新剔除，死名删除）：
# - "save"（通用保存）：bridge.py 全文无 `.save(` 调用点——死名，任何回执都不可能
#   靠它生效，留着只会让假证据永真 ⇒ 删。
# - "record"：bridge.py 无 `.record(` 调用点（遥测 record 在 app/telemetry，不经
#   回执函数）⇒ 死名，删。
# - "reset"：bridge.py 无 `.reset(` 调用点 ⇒ 死名，删。
# - "set_items"/"refreshQueue"：模型重建=纯刷新，不产生任何持久效果；"set_enabled"：
#   控件启停纯界面态——「已保存」类回执靠它们过关就是说谎 ⇒ 全部剔除（原依赖它们的
#   回执函数已逐一核对：要么另有真实证据，要么进 EXEMPT 并写明理由）。
# - "write"：保留——bridge.py 内 f.write 是遥测 JSONL 真落盘；文件句柄写入语义
#   见条目注记。
EXEMPT = {
    # 豁免只能在「语义确实成立」时开并写明理由；不许用豁免绕过自己写错的代码。
    # WP-05 撤销 copyText 豁免：其理由建立在缺逗号导致 setText 不在证据集上，
    # 逗号修复后 setText 是真证据，无需豁免。
    ("bridge.py", "_on_cw_deslop_done"): "去味效果在工作副本（cwProsePolished 信号驱动编辑器），内存生效类",
    # WP-13 扩面后新增（每条写明为什么免证据仍然不算说谎）：
    ("bridge.py", "_on_sel_done"): "局部改写结果存 _sel_result 内存工作副本，用户点「应用」才经 saveChapterText 落盘；回执只说「可应用或放弃」未宣称已落盘",
    ("bridge.py", "_on_finished"): "停止/完本回执发出前，orchestrator.run 的每条终态路径都已 save_state 真实落盘（WP-25：else 停止与 PipelineStopped 两路径新增 load→save 往返；跨层钉死=test_stop_receipts_backed_by_persisted_stop，删任一终态落盘即红）；本函数是 UI 态收尾+转述",
    ("bridge.py", "confirmChapterLocked"): "「该章已终稿锁定」是早退分支的状态转述（锁由 _do_lock_chapter→set_chapter_locked 落盘）",
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


# 成功语义词/免责否定词（WP-13①：级别只影响颜色，不影响检核）。
# 否定词 = 消息语义不是「宣称成功」的（失败/拒绝/状态告示/进行中），不进检核射程。
SUCCESS_WORDS = ("已", "完成", "成功")
FAILURE_WORDS = ("失败", "无法", "未能", "拒绝", "不能", "没有", "还没", "尚未",
                 "无需", "找不到", "不存在", "已经不在", "过期", "正在", "请先",
                 "先停止", "先完成", "不是", "没通过", "不够", "没听懂")


def _is_success_claim(msg_src: str) -> bool:
    has_ok = any(w in msg_src for w in SUCCESS_WORDS)
    has_fail = any(w in msg_src for w in FAILURE_WORDS)
    return has_ok and not has_fail


def _toast_emit_sites(tree, src):
    """全部 toast.emit(level, msg) 站点（含成功语义的，不论级别）"""
    funcs = _enclosing_functions(tree)
    sites = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit" and node.args):
            continue
        lvl = node.args[0]
        if not (isinstance(lvl, ast.Constant) and lvl.value in ("ok", "info", "warn", "error")):
            continue
        msg = node.args[1] if len(node.args) > 1 else None
        msg_src = ast.get_source_segment(src, msg) if msg else ""
        if not msg_src or not _is_success_claim(msg_src):
            continue
        fn = next((f for f in funcs
                   if f.lineno <= node.lineno <= getattr(f, "end_lineno", f.lineno)), None)
        if fn is None:
            continue
        sites.append((node, msg_src, fn))
    return sites


def test_success_toasts_have_effect_evidence():
    """WP-13①：任何带成功语义（已…/完成/成功）的 toast，**不论级别**（ok/info/
    warn/error），其所在函数必须有生效证据调用。级别只影响颜色，不影响检核——
    否则把「ok」挪成「info」就能让说谎回执过关（L2-18 实证路径）。"""
    tree, src = _bridge_tree_and_src()
    violations = []
    for node, msg_src, fn in _toast_emit_sites(tree, src):
        if (os.path.basename("app/ui/bridge.py"), fn.name) in EXEMPT:
            continue
        callees = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                   for c in ast.walk(fn) if isinstance(c, ast.Call)}
        if not (callees & set(EVIDENCE_CALLEES)):
            violations.append(
                f"bridge.py:{node.lineno} [{msg_src[:50]}…] 所在函数 {fn.name} 无落盘/生效证据调用")
    assert not violations, "回执三态违规（宣称「已X」但无生效证据，不论级别）：" + " | ".join(violations)


def test_pipeline_receipts_backed_by_real_state_change():
    """WP-13②：pause/resume/stop 三条回执的「生效证据」必须落在真实状态变更上。

    证据集里 pause/resume/stop 三个名字本身不构成保障——名字匹配是纯字面的：
    orchestrator 的方法被删掉/改名/改成空体，bridge 里的调用字面量仍在，
    回执门禁照样绿。本断言把链路两头钉死：
    ① orchestrator.pause/resume/stop 各自必须真实变更状态（事件 set/clear
       或 _stop 标志赋值）；
    ② bridge 三条回执函数必须真的调用 self.orch.<pause|resume|stop>()。
    """
    orch_src = open(os.path.join(ROOT, "app", "core", "orchestrator.py"), encoding="utf-8").read()
    orch_tree = ast.parse(orch_src)
    methods = {f.name: f for f in ast.walk(orch_tree)
               if isinstance(f, ast.FunctionDef) and f.name in ("pause", "resume", "stop")}
    assert set(methods) == {"pause", "resume", "stop"}, (
        f"orchestrator 的 pause/resume/stop 缺失：{set(('pause','resume','stop')) - set(methods)}")
    for name, fn in methods.items():
        has_evt = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                      and isinstance(c.func.value, ast.Attribute)
                      and c.func.value.value.id == "self"  # type: ignore[attr-defined]
                      and c.func.attr in ("set", "clear")
                      for c in ast.walk(fn))
        has_flag = any(isinstance(st_, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(t, ast.Attribute) and t.value.id == "self"
                               and t.attr == "_stop"  # type: ignore[attr-defined]
                               for t in (st_.targets if isinstance(st_, ast.Assign) else [st_.target]))
                       for st_ in ast.walk(fn) if isinstance(st_, (ast.Assign, ast.AnnAssign)))
        assert has_evt or has_flag, (
            f"orchestrator.{name}() 体内没有任何状态变更（事件 set/clear 或 _stop 赋值）"
            "——回执宣称的暂停/继续/停止是空头支票（WP-13②）")

    tree, _src = _bridge_tree_and_src()
    bridges = {"pausePipeline": "pause", "resumePipeline": "resume", "stopPipeline": "stop"}
    funcs = {f.name: f for f in ast.walk(tree)
             if isinstance(f, ast.FunctionDef) and f.name in bridges}
    assert set(funcs) == set(bridges), f"bridge 缺回执函数：{set(bridges) - set(funcs)}"
    for fname, orch_name in bridges.items():
        calls = [c for c in ast.walk(funcs[fname]) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Attribute) and c.func.attr == orch_name]
        assert calls, (
            f"bridge.{fname} 没有调用 orch.{orch_name}()——回执宣称与真实状态变更脱钩（WP-13②）")


# 上界面/落日志动作的调用名：handler 体里出现任一即不算「静默吞」
_UI_OR_LOG_CALLEES = {
    "emit", "append",              # toast.emit / logModel.append
    "info", "warning", "warn", "error", "debug", "exception", "critical", "log",
}


def _handler_is_silent(handler: ast.ExceptHandler) -> bool:
    """WP-13④：handler 体不含任何上界面/落日志动作 = 静默吞。
    旧实现只认「体恰好一条 Pass」——`pass` 后补一行无关计算就能绕过。"""
    for c in ast.walk(handler):
        if isinstance(c, ast.Call):
            name = getattr(c.func, "attr", getattr(c.func, "id", ""))
            if name in _UI_OR_LOG_CALLEES:
                return False
    return True


def _silent_swallow_violations(tree, src):
    """except 静默吞后同层紧跟成功回执（不论级别）= 说谎。返回违规描述列表。"""
    parent = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[child] = p
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _handler_is_silent(node):
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
                        and isinstance(c.args[0], ast.Constant)
                        and c.args[0].value in ("ok", "info", "warn", "error")):
                    msg = ast.get_source_segment(src, c.args[1]) if len(c.args) > 1 else ""
                    if msg and _is_success_claim(msg):
                        bad.append(f"行 {c.lineno} except 静默吞后直接成功回执")
    return bad


def test_no_silent_pass_before_success_claim():
    """except 静默吞（体不含任何上界面/落日志动作）后同层紧跟成功回执 = 说谎。

    WP-05 修正：ExceptHandler 挂在 Try.handlers——旧实现去 Try.body 找 ⇒ 恒真。
    WP-13④ 扩面：「体恰好一条 Pass」放宽为「体不含任何上界面/落日志动作」，
    `pass` 后补一行无关计算不再构成绕过；`pass`+`log()` 有日志动作则不算静默。
    """
    tree, src = _bridge_tree_and_src()
    bad = _silent_swallow_violations(tree, src)
    assert not bad, "静默吞后说谎：" + " | ".join(bad)


def test_silent_swallow_guard_synthetic():
    """WP-13④ 合成夹具：纯 pass 吞 + 成功回执必须红；pass+log() 不算静默必须绿。"""
    red_sample = '''
def f(self):
    try:
        do_work()
    except Exception:
        pass
    self.toast.emit("info", "已保存")
'''
    ok_log_sample = '''
def g(self):
    try:
        do_work()
    except Exception:
        pass
        log.warning("save skipped: %s", e)
    self.toast.emit("info", "已保存")
'''
    red_tree = ast.parse(red_sample)
    assert _silent_swallow_violations(red_tree, red_sample), (
        "纯 pass 静默吞 + 成功回执未被判定违规——扩面失效")
    ok_tree = ast.parse(ok_log_sample)
    assert not _silent_swallow_violations(ok_tree, ok_log_sample), (
        "pass+log() 处理器被误判为静默吞——扩面过宽")


# ---- N-36/N-05：静默吞护栏扩面到 app/core（WP-18） ----
# core 侧没有 toast，log 就是回执；except 静默吞后同层紧跟「成功语义 log」= 说谎。
# 成功语义判定只看 info/debug/log 调用（warning/error 本身是失败声明，不算回执）。

_CORE_LOG_CALLEES = ("log", "info", "debug")
_CORE_SUCCESS_WORDS = ("完成", "成功", "已")


def test_no_silent_pass_before_success_log_in_core():
    core_dir = os.path.join(ROOT, "app", "core")
    bad = []
    for fn in sorted(os.listdir(core_dir)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(core_dir, fn)
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        parent = {}
        for p in ast.walk(tree):
            for child in ast.iter_child_nodes(p):
                parent[child] = p
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _handler_is_silent(node):
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
                    if not isinstance(c, ast.Call):
                        continue
                    name = getattr(c.func, "attr", getattr(c.func, "id", ""))
                    if name not in _CORE_LOG_CALLEES or not c.args:
                        continue
                    # 级别在首参（log("warn", …) 是失败/告警声明，不是成功回执）
                    lvl = ast.unparse(c.args[0]).strip("'\"")
                    if lvl in ("warn", "warning", "error", "critical"):
                        continue
                    # 成功语义在消息参（可能是 f-string），全参扫
                    msg = " ".join(ast.unparse(a) for a in c.args[1:] or c.args)
                    if any(w in msg for w in _CORE_SUCCESS_WORDS):
                        bad.append(f"app/core/{fn}:{c.lineno} except 静默吞后紧跟成功语义 log")
    assert not bad, "core 静默吞后说谎（N-36 扫描面）：" + " | ".join(bad)


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


def test_stop_receipts_backed_by_persisted_stop():
    """WP-25：终态回执（done/stopped）发出前，同分支必须已有真实 save_state。

    背景：_on_finished 豁免理由原写「checkpoint 逐检查点落盘」——checkpoint()
    只做暂停/停止/离峰等待不落盘，被评审驳回。现每条终态路径在 emit 前显式
    落盘（else 停止与 PipelineStopped 两路径为 WP-25 新增 load→save 往返），
    本断言按 AST 钉死「发射终态信号的分支体内、emit 行之前必须有 save_state」：
    删掉任一终态落盘（v3 复验动作：删 orchestrator.py:505 一带的 save_state）
    即红。"""
    orch_path = os.path.join(ROOT, "app", "core", "orchestrator.py")
    src = open(orch_path, encoding="utf-8").read()
    tree = ast.parse(src)
    parent = {}
    for p_ in ast.walk(tree):
        for c in ast.iter_child_nodes(p_):
            parent[c] = p_

    def _stmt_list_of(node):
        """emit 节点所在的可迭代语句体（If/Try/handler/函数体的 body 列表）"""
        cur = node
        while cur in parent:
            holder = parent[cur]
            for _f, v in ast.iter_fields(holder):
                if isinstance(v, list) and cur in v:
                    return holder, v, cur
            cur = holder
        return None, [], node

    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"):
            continue
        if not node.args or not (isinstance(node.args[0], ast.Constant)
                                 and node.args[0].value in ("done", "stopped")):
            continue
        # 只查 emit 直接所属的语句体（不向上爬升）——爬升会用其他分支的落盘
        # 顶替本分支的（v3 复验变异 M1/M2 的第一次实现就是这么漏的）
        _holder, body, _cur = _stmt_list_of(node)
        saves = [st_.lineno for st_ in body
                 if getattr(st_, "lineno", 0) < node.lineno
                 and any(isinstance(c, ast.Call)
                         and getattr(c.func, "attr", getattr(c.func, "id", "")) == "save_state"
                         for c in ast.walk(st_))]
        if not saves:
            bad.append(f"orchestrator.py:{node.lineno} 终态 emit("
                       f"{node.args[0].value}) 所在分支体内无先行的 save_state")
    assert not bad, "终态回执缺真实落盘背书（WP-25）：" + "；".join(bad)
