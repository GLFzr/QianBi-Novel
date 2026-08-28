# -*- coding: utf-8 -*-
"""双端共享层同步检查（GUI ↔ TUI）

对比 qianbi-novel（GUI）与 qianbi-Novel-TUI（TUI）的共享层目录
（app/core、app/llm、app/prompts、app/presets），输出漂移清单。

约定：**共享层改动必须双端同步**。任何一侧改了共享文件，都要手动同步到
另一侧，然后跑本脚本确认漂移清零（或仅剩有意保留的差异）。

用法：
  python scripts/dual_sync_check.py                 # 自动探测双端目录（同级兄弟）
  python scripts/dual_sync_check.py --gui X --tui Y # 手动指定
  python scripts/dual_sync_check.py --json out.json # 结果落盘

退出码：0 = 完全同步；1 = 存在漂移；2 = 目录缺失/配置错误
"""
import argparse
import hashlib
import json
import os
import sys

SHARED_DIRS = ["app/core", "app/llm", "app/prompts", "app/presets"]
SKIP_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


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
    for subdir in SHARED_DIRS:
        gui_files = _list_files(gui_root, subdir)
        tui_files = _list_files(tui_root, subdir)
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
    print(f"共享层: {', '.join(SHARED_DIRS)}  共 {len(rows)} 个文件")
    print()

    order = ["DRIFT", "ONLY_GUI", "ONLY_TUI", "DRIFT_EOL", "IDENTICAL"]
    label = {
        "DRIFT": "内容漂移",
        "ONLY_GUI": "仅 GUI 存在",
        "ONLY_TUI": "仅 TUI 存在",
        "DRIFT_EOL": "仅换行差异",
        "IDENTICAL": "一致",
    }
    for st in order:
        group = [r for r in rows if r["status"] == st]
        if not group:
            continue
        print(f"[{label[st]}] {len(group)} 个")
        if st != "IDENTICAL":
            for r in group:
                print(f"  - {r['file']}")
        print()

    print(f"结论: {'存在漂移 ' + str(n_drift) + ' 项——共享层改动须双端同步' if n_drift else '双端共享层完全同步'}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"gui": gui_root, "tui": tui_root,
                       "counts": counts, "rows": rows}, f, ensure_ascii=False, indent=2)
        print(f"→ {args.json}")

    sys.exit(1 if n_drift else 0)


if __name__ == "__main__":
    main()
