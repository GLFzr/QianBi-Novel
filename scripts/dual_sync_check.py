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

用法：
  python scripts/dual_sync_check.py                 # 自动探测双端目录（同级兄弟）
  python scripts/dual_sync_check.py --gui X --tui Y # 手动指定
  python scripts/dual_sync_check.py --json out.json # 结果落盘

退出码：0 = 无意外漂移；1 = 存在意外漂移；2 = 目录缺失/配置错误
"""
import argparse
import hashlib
import json
import os
import sys

SHARED_DIRS = ["app/core", "app/llm", "app/prompts", "app/presets"]
# app 根目录的双端共享文件（T3.x 补充：deslop.py 曾在覆盖范围外漂移不可见）
SHARED_ROOT_FILES = ["app/deslop.py"]
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
    "app/prompts/__init__.py": "双端按需 re-export（GUI 导出 v2 审校族，TUI 导出 CO_WORLDBOOK_*）",
    # ---- 平台管道：GUI 走 Qt Signal，TUI 走 bus._pub；stages 差异含 TUI resume 集成
    "app/core/orchestrator.py": "GUI sig_* 信号 vs TUI bus._pub 发布管道（T3.3 去轮询已双端同构）",
    "app/core/stages.py": "TUI resume 续写集成 + 平台管道；共享 prompt 组装逻辑改动仍须人工比对同步",
    # ---- TUI 截断续写特性（LLMTruncated + finish=length 抛错）；GUI 仅移植 parts 重置修复
    "app/llm/client.py": "TUI 独有 LLMTruncated/resume 钩子（续写特性）；GUI 无 resume 消费者",
    "app/llm/resume.py": "TUI 独有截断续写模块（M 系特性，未排期移植 GUI）",
    # ---- 审校两代共存：GUI 保留 v1 真实 REVIEW_PROMPT/REVIEW_FIX_PROMPT（C6 链依赖），
    #      TUI 已将 v1 别名到 v2；v2 主体（FINAL_REVIEW/ROOT_CAUSE few-shot）已双端一致
    "app/prompts/review.py": "GUI 需真实 v1 审校 prompt（C6）；TUI v1=v2 别名；v2 正文已同步",
}


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


def main():
    ap = argparse.ArgumentParser(description="双端共享层同步检查（GUI ↔ TUI）")
    ap.add_argument("--gui", default=None, help="GUI 项目根目录（默认自动探测）")
    ap.add_argument("--tui", default=None, help="TUI 项目根目录（默认自动探测）")
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

    rows = compare(gui_root, tui_root)

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

    if n_drift:
        print(f"结论: 存在意外漂移 {n_drift} 项——共享层改动须双端同步（或裁决后登记进 EXPECTED_DIFFS）")
    else:
        print(f"结论: 无意外漂移（{counts.get('ACCEPTED', 0)} 项登记差异 + {counts.get('IDENTICAL', 0)} 项一致）")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"gui": gui_root, "tui": tui_root,
                       "counts": counts, "rows": rows}, f, ensure_ascii=False, indent=2)
        print(f"→ {args.json}")

    sys.exit(1 if n_drift else 0)


if __name__ == "__main__":
    main()
