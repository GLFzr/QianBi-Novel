# -*- coding: utf-8 -*-
"""用户本地网文/现代作品样本导入 → tests/corpus_ref/（只导入，不抓取）

版权口径（重要）：近年网文均在版权保护期内，平台 ToS 禁止抓取，
本项目**不做批量抓取**。本脚本只接收用户已合法获得的样本文本
（正规平台购买/免费阅读，仅限个人学习研究，不得再分发），
做编码探测、质量校验、版权标注与编目。

用法：
  python scripts/import_ref_corpus.py 某书.txt --book 书名 --source "起点(已购)"
  python scripts/import_ref_corpus.py 一个目录 --book 书名    # 导入目录下全部 .txt
  python scripts/import_ref_corpus.py --list                  # 查看已入库书目
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEST = os.path.join(ROOT, "tests", "corpus_ref")

_MIN_CHARS = 2000      # 低于此字数的样本无锚定/注入价值
_MIN_CJK = 0.5         # 汉字占比下限（防拿到纯 HTML/乱码）


def _read_text(path: str) -> str:
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RuntimeError(f"无法识别编码：{path}")


def _clean(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\ufeff", "")
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _cjk_ratio(text: str) -> float:
    sample = text[:20000]
    if not sample:
        return 0.0
    return len(re.findall(r"[\u4e00-\u9fff]", sample)) / len(sample)


def import_one(path: str, book: str, source: str) -> bool:
    raw = _read_text(path)
    text = _clean(raw)
    n = len(text)
    ratio = _cjk_ratio(text)
    if n < _MIN_CHARS:
        print(f"  [跳过] {os.path.basename(path)}：仅 {n} 字（<{_MIN_CHARS}）")
        return False
    if ratio < _MIN_CJK:
        print(f"  [跳过] {os.path.basename(path)}：汉字占比 {ratio:.0%} 过低"
              f"（疑非正文/编码异常）")
        return False
    out_dir = os.path.join(DEST, book)
    os.makedirs(out_dir, exist_ok=True)
    base = re.sub(r'[\\/:*?"<>|]', "", os.path.splitext(os.path.basename(path))[0])
    out_path = os.path.join(out_dir, f"{base[:40]}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  [入库] {out_path}（{n} 字，汉字占比 {ratio:.0%}）")
    return True


def _write_manifest(source: str):
    manifest_path = os.path.join(DEST, "corpus_manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}
    manifest.update({
        "license": "copyrighted —— 非公有领域！仅限个人学习研究，"
                   "禁止再分发/公开/打包进任何产物",
        "note": "由 scripts/import_ref_corpus.py 编目，样本须为用户合法获得",
    })
    books = sorted(d for d in os.listdir(DEST)
                   if os.path.isdir(os.path.join(DEST, d)))
    manifest["books"] = books
    if source:
        manifest.setdefault("sources", {})
        for b in books:
            manifest["sources"].setdefault(b, source)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="导入用户合法获得的现代作品样本 → tests/corpus_ref/")
    ap.add_argument("path", nargs="?", default="", help=".txt 文件或含 .txt 的目录")
    ap.add_argument("--book", default="", help="书目名（落盘子目录）")
    ap.add_argument("--source", default="", help="来源备注（如：起点(已购)）")
    ap.add_argument("--list", action="store_true", help="查看已入库书目")
    args = ap.parse_args(argv)

    if args.list:
        if not os.path.isdir(DEST):
            print("（尚未导入任何样本）")
            return 0
        for book in sorted(os.listdir(DEST)):
            d = os.path.join(DEST, book)
            if os.path.isdir(d):
                files = [f for f in os.listdir(d) if f.endswith(".txt")]
                print(f"{book:<20} {len(files)} 个样本")
        return 0

    if not args.path or not args.book:
        print("用法：import_ref_corpus.py <txt文件|目录> --book 书名 [--source 来源]")
        return 1
    if not os.path.exists(args.path):
        print(f"路径不存在：{args.path}")
        return 1
    files = ([args.path] if os.path.isfile(args.path)
             else [os.path.join(args.path, f) for f in sorted(os.listdir(args.path))
                   if f.lower().endswith(".txt")])
    if not files:
        print(f"{args.path} 下没有 .txt 文件")
        return 1
    ok = 0
    for p in files:
        try:
            ok += 1 if import_one(p, args.book, args.source) else 0
        except Exception as e:
            print(f"  [失败] {p}：{e}")
    if ok:
        _write_manifest(args.source)
    print(f"\n入库 {ok}/{len(files)} 个样本 → {os.path.join(DEST, args.book)}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
