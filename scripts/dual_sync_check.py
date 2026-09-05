# -*- coding: utf-8 -*-
"""双端共享层同步检查（GUI ↔ TUI）

对比 qianbi-novel（GUI）与 qianbi-Novel-TUI（TUI）的共享层目录
（app/core、app/llm、app/prompts、app/presets 及 app 根目录共享文件），
输出漂移清单。

约定：**共享层改动必须双端同步**。任何一侧改了共享文件，都要手动同步到
另一侧，然后跑本脚本确认结果。

状态语义：
- IDENTICAL / DRIFT_EOL：内容一致（或仅换行差异）
- ACCEPTED：命中 EXPECTED_DIFFS 的**有意保留平台差异**（逐文件记录原因，
  属受控差异，不算漂移；原因变更需同步修订本表）
- DRIFT / ONLY_*：意外漂移，必须处理（同步或裁决进 EXPECTED_DIFFS）

文件级豁免会整份放行，于是**同一文件内本该同源的函数**各改各的也看不见。
故另有符号级门禁（SHARED_SYMBOLS）：对双端指定模块/函数做 AST 摘要
（注释、空行、换行符、行号都不计，只有代码结构计），不同源即失败；
GUI 先行的符号必须在 DEFERRED_SYMBOLS 里登记原因 + TUI 当时的摘要水印，
水印不一致＝登记之后 TUI 侧也动过这个符号，同样失败（防止两侧同时漂移）。

用法：
  python scripts/dual_sync_check.py                 # 自动探测双端目录（同级兄弟）
  python scripts/dual_sync_check.py --gui X --tui Y # 手动指定
  python scripts/dual_sync_check.py --symbols-only  # 只跑符号级门禁
  python scripts/dual_sync_check.py --json out.json # 结果落盘

退出码：0 = 无意外漂移且符号门禁通过；1 = 存在意外漂移或符号级不同源；2 = 目录缺失/配置错误
"""
import argparse
import ast
import hashlib
import json
import os
import sys

SHARED_DIRS = ["app/core", "app/llm", "app/prompts", "app/presets"]
# app 根目录的双端共享文件（T3.x 补充：deslop.py 曾在覆盖范围外漂移不可见；
# usage.py 为 Token 用量统计共享模块，2026-08-31 纳入；
# wb.py 世界书装配内核（W0b/W1）——放 app 根而非 app/core，是因为 app/project.py
# 被 CLI/脚本直接 import，不能被 app/core/__init__.py 的 PySide6 链拖住）
SHARED_ROOT_FILES = ["app/deslop.py", "app/usage.py", "app/wb.py"]
SKIP_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# 有意保留的平台差异登记表（file → 原因）。裁决记录见 docs/plan_optimization_v1.md 执行日志。
EXPECTED_DIFFS = {
    # ---- 共写阶段序家族：GUI=v1（世界书先于细纲，bridge/QML 流程按此接线）；
    #      TUI=v2（细纲先于世界书，seq_v2 迁移）。数据契约（stage 键名）双端兼容，
    #      行为序差异待 GUI 升级 v2 时收口（届时整族同步并删除本组豁免）。
    "app/core/state.py": "共写阶段序 v1/v2 + GUI 独有 review_* 默认键（T3.2 已双端同构键校验）",
    "app/core/co_writing.py": "TUI v2 seq_v2 阶段重推迁移（依赖 TUI 阶段序）",
    "app/core/co_dialogue.py": "TUI v2 世界书对话流 + roster/ledger 等上下文块组装（GUI 尚未升级 v2）",
    "app/prompts/co_writing.py": "TUI v2 共写 prompt 需 5 个新上下文块（golden_finger/ledger/master_outline/roster/volume_schedule），GUI 调用方未组装，强同步会 KeyError",
    # P0b（2026-09-02，GUI 先行）：正文 prompt 新增 {craft_block}/{author_note} 占位 +
    # 空的「20. 动静配比」并入 21。TUI 调用点不传新 kwargs，同步过去即 KeyError。
    "app/prompts/writing.py": "P0b 正文工艺卡/作者按占位符 GUI 先行，TUI 待同步（同步时须补 stages 传参）",
    "app/prompts/__init__.py": "双端按需 re-export（GUI 导出 v2 审校族，TUI 导出 CO_WORLDBOOK_*）",
    # ---- 体验轮 A1（2026-09-05，GUI 先行）：共享前缀构建器=缓存命中主力，
    #      依赖 GUI prompts/co_writing 的 STYLE_DISCIPLINE 与 wb.constant_entries（已双端）；TUI 待同步
    "app/core/shared_prefix.py": "共享前缀构建器（项目头逐字节稳定）GUI 先行：依赖 GUI co_writing.STYLE_DISCIPLINE；TUI 待排期同步",
    # ---- 方案 D1（2026-09-05，GUI 先行）：设定清算=共写/自动档定稿后的产物对账，
    #      依赖 GUI 的 pipeline_state.chapter_step 与审校槽路由；TUI 无微循环定稿流，待同步
    "app/core/canon_audit.py": "设定清算（正文 vs 拆解底册三分类对账）GUI 先行：依赖 GUI 微循环定稿流与审校槽路由，TUI 无此特性待排期",
    # ---- 平台管道：GUI 走 Qt Signal，TUI 走 bus._pub；stages 差异含 TUI resume 集成
    "app/core/orchestrator.py": "GUI sig_* 信号 vs TUI bus._pub 发布管道（T3.3 去轮询已双端同构）",
    "app/core/stages.py": "TUI resume 续写集成 + 平台管道；共享 prompt 组装逻辑改动仍须人工比对同步",
    # ---- TUI 截断续写特性（LLMTruncated + finish=length 抛错）；GUI 仅移植 parts 重置修复
    # P0a（2026-09-02）双端已同步：_build_payload 唯一构造点 + phase 形参签名同源。
    # P1（2026-09-02，GUI 先行，符号门禁已登记水印）：GUI 在此之上多出一层分相位档
    # （_overrides/stage_params）、OPTIONAL_PARAM_KEYS 循环、能力备忘录与 last_sampling 留痕；
    # TUI 已有 payload_defaults 三级优先级，缺 stage_params 那一层。
    "app/llm/client.py": "TUI 独有 LLMTruncated/resume 钩子（续写特性）；GUI 独有 P1 分相位档+能力备忘录+采样留痕（P0a 构造点已双端同源）",
    # P1（2026-09-02，GUI 先行）：GUI 路由把预设两层覆盖传给 from_connection；
    # TUI 客户端 from_connection 已有 payload_defaults 形参、无 stage_params 形参
    # → 直接把 GUI router 同步过去即 TypeError（先同步 client.py，再同步本文件并删豁免）。
    "app/llm/router.py": "P1 两层参数透传 GUI 先行：TUI router 不传 stage_params/payload_defaults（TUI client 已支持 payload_defaults，故只需同步本文件）",
    "app/llm/resume.py": "TUI 独有截断续写模块（M 系特性，未排期移植 GUI）",
    # ---- v0.18.1（2026-09-04，GUI 先行）：出厂连接预设从 3 家扩到 12 家。这张表与
    #      app/config.py 的 DEFAULT_CONNECTIONS / 槽位指向是一件事（config.py 不在共享层），
    #      只把 providers.py 拷过去会让 TUI 的连接预设与槽位指到解析不到的 id。
    #      真同步 = TUI 同一个 commit 里改 providers.py + 它自己的连接预设与 slot 默认值。
    "app/llm/providers.py": "v0.18.1 12 家预设表 GUI 先行；TUI 同步须连带其 config.py 的连接预设与槽位默认值（只拷本文件会留悬空 id）",
    # ---- 审校两代共存：GUI 保留 v1 真实 REVIEW_PROMPT/REVIEW_FIX_PROMPT（C6 链依赖），
    #      TUI 已将 v1 别名到 v2；v2 主体（FINAL_REVIEW/ROOT_CAUSE few-shot）已双端一致
    "app/prompts/review.py": "GUI 需真实 v1 审校 prompt（C6）；TUI v1=v2 别名；v2 正文已同步",
    # ---- P4（2026-09-02，GUI 先行）：四环节题材块接线。核心设定/全书大纲/世界书三张模板
    #      新增 {genre_block}（stage_hints 此前只有 unit_outline/prose 两键真正生效），
    #      TUI 调用点不传该 kwarg → 同步过去即 KeyError。
    "app/prompts/planning.py": "P4 核心设定/全书大纲题材块 GUI 先行，TUI 待同步（同步时须补 stages 传参）",
    "app/prompts/memory.py": "P4 世界书首版题材块 GUI 先行，TUI 待同步（同步时须补 stages 传参）",
    #      deslop_extra 改走 stages._tic_blacklist 专属近端槽（扩写/压缩/去味三张模板只有该槽），
    #      genre_block 不再带它；TUI 仍从 genre_block 拿这份限量，字段不丢，只是槽位待统一。
    "app/presets/__init__.py": "P4 题材限量改走写作红线专属槽 GUI 先行；TUI 仍由 genre_block 注入（不丢字段，槽位待同步）",
}

# ---- 符号级门禁：绕开上面的文件级豁免，逐个函数盯同源 ----------------------
# app/project.py 整体不在文件级扫描范围内（双端各有一批专属函数，逐文件比对无意义），
# 但这三个世界书函数是双端共用语义——只有纳入本表才看得见它们在不在漂移。
SHARED_SYMBOLS = {
    "app/wb.py": ["*"],                                    # W1 装配内核：整模块同源
    "app/project.py": ["worldbook_text", "worldbook_anchors", "regex_rules"],
    "app/core/stages.py": ["_stream", "_worldbook_regex_blocks"],
    "app/llm/client.py": ["LLMClient._build_payload", "LLMClient.chat_stream"],
    "app/prompts/scene_cards.py": ["*"],                   # 工艺卡内核：整模块同源
}

# (file, symbol) → {"reason": 为什么允许暂时不同源, "tui": 登记时 TUI 侧 AST 摘要}
# 同步完成后**删除本条**（符号回到 SHARED_SYMBOLS 硬同源）；#64 移植清单逐条对应。
DEFERRED_SYMBOLS = {
    ("app/project.py", "regex_rules"): {
        "reason": "A5 多行块解析（列表项起条目/续行并入/字段整块查找/scope 值截断）GUI 先行，TUI 仍逐行解析",
        "tui": "c70467cbfb69ceca",
    },
    ("app/core/stages.py", "_stream"): {
        "reason": "TUI 独有 resume_base/resume_max_rounds 截断续写形参；GUI 独有 P2 调用记录链"
                  "＋停止实时化（下传 abort 谓词，client 报中断即抛 PipelineStopped）",
        "tui": "55f9565d605f9244",
    },
    ("app/llm/client.py", "LLMClient._build_payload"): {
        "reason": "P1 分相位档 _overrides + 可选参数循环 + 能力备忘录 + last_sampling 留痕 GUI 先行"
                  "（TUI 已有 payload_defaults 三级优先级，缺 stage_params 层）",
        "tui": "d8af506b0f266477",
    },
    ("app/llm/client.py", "LLMClient.chat_stream"): {
        "reason": "P0a/P1 退化标记循环与 phase 透传 GUI 先行；TUI 侧另有 LLMTruncated 截断抛错",
        "tui": "948b6d183b05aa32",
    },
}


# 判过的符号状态：同源、以及**已登记**的延后形态
SYMBOL_PASS = {"OK", "DEFERRED", "DEFERRED_GUI_ONLY", "DEFERRED_RESYNCED"}


def _parse_file(root, rel):
    """返回 (tree, 错误说明)；文件缺失/语法错误都以 None tree 返回，由调用方判失败"""
    path = os.path.join(root, *rel.split("/"))
    if not os.path.isfile(path):
        return None, f"文件缺失: {path}"
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return ast.parse(f.read(), filename=path), ""
    except SyntaxError as e:
        return None, f"语法错误: {rel}:{e.lineno} {e.msg}"


def _find_symbol(tree, dotted):
    """支持 Class.method 两级定位；未命中返回 None"""
    scope, node = tree, None
    for part in dotted.split("."):
        cands = [c for c in getattr(scope, "body", [])
                 if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and c.name == part]
        if not cands:
            return None
        node = scope = cands[0]
    return node


def _symbol_sig(node):
    if node is None:
        return "—"
    if isinstance(node, ast.Module):
        return "整模块"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{kind} {node.name}({ast.unparse(node.args)})"


def _symbol_hash(tree, dotted):
    """AST 结构摘要：注释/空行/换行/行号都不计，只有代码结构计

    所以「格式化」不会误报，而「同名函数换了实现」（哪怕只是把某个字段从注入
    路径里删掉）一定会计出来——正是文件级豁免遮不住的那一类。
    """
    if tree is None:
        return None
    if dotted == "*":
        node = tree
    else:
        node = _find_symbol(tree, dotted)
    if node is None:
        return None
    return hashlib.sha256(ast.dump(node).encode("utf-8")).hexdigest()[:16]


def compare_symbols(gui_root, tui_root):
    """逐符号出状态：OK / DEFERRED / DEFERRED_GUI_ONLY / DEFERRED_RESYNCED /
    DEFERRED_TUI_MOVED / DIFF / MISSING_GUI / MISSING_TUI
    """
    rows = []
    for rel, syms in SHARED_SYMBOLS.items():
        g_tree, g_err = _parse_file(gui_root, rel)
        t_tree, t_err = _parse_file(tui_root, rel)
        for sym in syms:
            deferred = DEFERRED_SYMBOLS.get((rel, sym))
            g = _symbol_hash(g_tree, sym)
            t = _symbol_hash(t_tree, sym)
            if g is None:
                status = "MISSING_GUI"
            elif t is None:
                status = "DEFERRED_GUI_ONLY" if deferred else "MISSING_TUI"
            elif g == t:
                status = "DEFERRED_RESYNCED" if deferred else "OK"
            elif not deferred:
                status = "DIFF"
            else:
                status = "DEFERRED" if t == deferred["tui"] else "DEFERRED_TUI_MOVED"
            node = g_tree if sym == "*" else _find_symbol(g_tree, sym)
            rows.append({
                "file": rel, "symbol": sym, "status": status,
                "gui": g, "tui": t,
                "gui_sig": _symbol_sig(node) if g_tree else g_err,
                "note": t_err if (t is None and t_err) else "",
                "reason": deferred["reason"] if deferred else "",
            })
    return rows


def _default_roots():
    """脚本位于 <gui>/scripts/ 下：GUI=上级目录，TUI=同级兄弟 qianbi-Novel-TUI"""
    gui = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tui = os.path.join(os.path.dirname(gui), "qianbi-Novel-TUI")
    return gui, tui


def _list_files(root, subdir):
    """返回 {相对路径: 绝对路径}（跳过 __pycache__/字节码）"""
    base = os.path.join(root, subdir)
    out = {}
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for fn in filenames:
            if os.path.splitext(fn)[1] in SKIP_SUFFIXES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out[rel] = full
    return out


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest_norm(path):
    """换行归一化后的摘要（区分「仅换行差异」与「内容漂移」）"""
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def compare(gui_root, tui_root):
    rows = []
    targets = [(d, None) for d in SHARED_DIRS] + [(os.path.dirname(f), [os.path.basename(f)]) for f in SHARED_ROOT_FILES]
    for subdir, only_names in targets:
        gui_files = _list_files(gui_root, subdir)
        tui_files = _list_files(tui_root, subdir)
        if only_names is not None:
            gui_files = {k: v for k, v in gui_files.items() if os.path.basename(k) in only_names}
            tui_files = {k: v for k, v in tui_files.items() if os.path.basename(k) in only_names}
        all_rels = sorted(set(gui_files) | set(tui_files))
        for rel in all_rels:
            g, t = gui_files.get(rel), tui_files.get(rel)
            if g and not t:
                status = "ONLY_GUI"
            elif t and not g:
                status = "ONLY_TUI"
            elif _digest(g) == _digest(t):
                status = "IDENTICAL"
            elif _digest_norm(g) == _digest_norm(t):
                status = "DRIFT_EOL"  # 仅换行符差异（Windows/Unix）
            else:
                status = "DRIFT"
            if status in ("DRIFT", "DRIFT_EOL", "ONLY_GUI", "ONLY_TUI") and rel in EXPECTED_DIFFS:
                status = "ACCEPTED"
            rows.append({"file": rel, "status": status})
    return rows


def stale_deferrals():
    """DEFERRED_SYMBOLS 里指向清单外符号的条目＝永不生效的空豁免，必须算失败"""
    return [f"{f}::{s}" for f, s in DEFERRED_SYMBOLS if s not in SHARED_SYMBOLS.get(f, [])]


def main():
    ap = argparse.ArgumentParser(description="双端共享层同步检查（GUI ↔ TUI）")
    ap.add_argument("--gui", default=None, help="GUI 项目根目录（默认自动探测）")
    ap.add_argument("--tui", default=None, help="TUI 项目根目录（默认自动探测）")
    ap.add_argument("--symbols-only", action="store_true", help="只跑符号级门禁")
    ap.add_argument("--json", default=None, help="结果输出到 JSON 文件")
    args = ap.parse_args()

    d_gui, d_tui = _default_roots()
    gui_root = args.gui or os.environ.get("QIANBI_GUI_ROOT") or d_gui
    tui_root = args.tui or os.environ.get("QIANBI_TUI_ROOT") or d_tui

    if not os.path.isdir(os.path.join(gui_root, "app")):
        print(f"GUI 目录无效: {gui_root}")
        sys.exit(2)
    if not os.path.isdir(os.path.join(tui_root, "app")):
        print(f"TUI 目录无效: {tui_root}")
        sys.exit(2)

    rows = [] if args.symbols_only else compare(gui_root, tui_root)

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    n_drift = counts.get("DRIFT", 0) + counts.get("DRIFT_EOL", 0) \
        + counts.get("ONLY_GUI", 0) + counts.get("ONLY_TUI", 0)

    print(f"GUI: {gui_root}")
    print(f"TUI: {tui_root}")
    print(f"共享层: {', '.join(SHARED_DIRS)} + 根文件 {SHARED_ROOT_FILES}  共 {len(rows)} 个文件")
    print()

    order = ["DRIFT", "ONLY_GUI", "ONLY_TUI", "DRIFT_EOL", "ACCEPTED", "IDENTICAL"]
    label = {
        "DRIFT": "内容漂移",
        "ONLY_GUI": "仅 GUI 存在",
        "ONLY_TUI": "仅 TUI 存在",
        "DRIFT_EOL": "仅换行差异",
        "ACCEPTED": "有意平台差异（已登记豁免）",
        "IDENTICAL": "一致",
    }
    for st in order:
        group = [r for r in rows if r["status"] == st]
        if not group:
            continue
        print(f"[{label[st]}] {len(group)} 个")
        if st in ("DRIFT", "ONLY_GUI", "ONLY_TUI", "DRIFT_EOL"):
            for r in group:
                print(f"  - {r['file']}")
        elif st == "ACCEPTED":
            for r in group:
                print(f"  - {r['file']}\n      {EXPECTED_DIFFS[r['file']]}")
        print()

    sym_rows = compare_symbols(gui_root, tui_root)
    stale = stale_deferrals()
    n_sym = sum(1 for r in sym_rows if r["status"] not in SYMBOL_PASS) + len(stale)
    sym_label = {
        "DIFF": "符号级不同源（未登记）",
        "MISSING_GUI": "GUI 侧查无此符号（清单笔误或已被删）",
        "MISSING_TUI": "TUI 侧查无此符号",
        "DEFERRED_TUI_MOVED": "登记延后后 TUI 侧又改过（两侧同时漂移）",
        "DEFERRED_RESYNCED": "延后登记已多余（其实同源，删条目）",
        "DEFERRED_GUI_ONLY": "GUI 独有（已登记延后）",
        "DEFERRED": "GUI 先行（已登记延后 + 水印一致）",
        "OK": "符号同源",
    }
    print(f"[符号级门禁] {len(sym_rows)} 项（SHARED_SYMBOLS 绕开文件级豁免）")
    for st in ["DIFF", "MISSING_GUI", "MISSING_TUI", "DEFERRED_TUI_MOVED",
               "DEFERRED_RESYNCED", "DEFERRED_GUI_ONLY", "DEFERRED"]:
        group = [r for r in sym_rows if r["status"] == st]
        if not group:
            continue
        print(f"  {sym_label[st]} {len(group)} 个")
        for r in group:
            print(f"    - {r['file']}::{r['symbol']}   gui={r['gui'] or '—'} tui={r['tui'] or '—'}")
            if st in ("DIFF", "MISSING_GUI", "MISSING_TUI", "DEFERRED_TUI_MOVED"):
                print(f"        登记：DEFERRED_SYMBOLS[('{r['file']}', '{r['symbol']}')]，"
                      f"tui 水印填 {r['tui'] or '—（TUI 侧无此符号）'}")
            if r["gui_sig"]:
                print(f"        GUI 签名: {r['gui_sig'][:160]}")
            if r["note"]:
                print(f"        TUI: {r['note']}")
            if r["reason"]:
                print(f"        {r['reason']}")
    if stale:
        print(f"  失效的延后登记 {len(stale)} 个（符号已不在清单里，永不生效）")
        for s in stale:
            print(f"    - {s}")
    print(f"  符号同源 {sum(1 for r in sym_rows if r['status'] == 'OK')} 个")
    print()

    verdict = []
    if n_drift:
        verdict.append(f"意外漂移 {n_drift} 项（共享层改动须双端同步，或裁决后登记进 EXPECTED_DIFFS）")
    if n_sym:
        verdict.append(f"符号级问题 {n_sym} 项（同步该符号，或登记进 DEFERRED_SYMBOLS 并留 TUI 水印）")
    if verdict:
        print("结论: " + "；".join(verdict))
    else:
        print(f"结论: 无意外漂移（{counts.get('ACCEPTED', 0)} 项登记差异 + "
              f"{counts.get('IDENTICAL', 0)} 项一致）；符号门禁 {len(sym_rows)} 项全过")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"gui": gui_root, "tui": tui_root,
                       "counts": counts, "rows": rows,
                       "symbols": sym_rows, "stale_deferrals": stale},
                      f, ensure_ascii=False, indent=2)
        print(f"→ {args.json}")

    sys.exit(1 if (n_drift or n_sym) else 0)


if __name__ == "__main__":
    main()
