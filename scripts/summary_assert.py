# -*- coding: utf-8 -*-
"""摘要覆盖度断言（W4.2 / E4.1 外迁实验的质量断言）：给定摘要 + 关键要素清单 → 覆盖度判定

从摘要**反向断言**：摘要必须包含关键要素清单里的每一条（人物/事件/时间线三类），
命中 = 摘要文本含要素关键词或其任一别名（子串匹配）。脚本可判、零 API 成本，
用于摘要系相位（chapter_summary/global_summary/tracking）外迁 qwen/doubao/GLM 前后的质量闸门。

manifest schema（JSON，三类键均可缺省，缺省视为 0 条）：
{
  "characters": [{"key": "陈默", "aliases": ["老陈", "男主"]}, ...],   # 人物要素
  "events":    [{"key": "父亲留下通话录音", "aliases": ["录音", "遗嘱"]}, ...],  # 关键事件
  "timeline":  [{"key": "0317 订单", "aliases": ["编号零三一七", "3月17日"]}, ...]  # 时间线
}

用法：
  python scripts/summary_assert.py --summary <摘要文件> --manifest <要素清单.json>
  python scripts/summary_assert.py --summary <摘要文件> --inline '<manifest json>'
  python scripts/summary_assert.py --summary-text "<摘要全文>" --manifest <要素清单.json>

输出：stdout 明细表（类别/要素/命中词/结果 + 分类统计）；
退出码：0=全部命中；1=存在未命中；2=用法/IO/解析错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CATEGORIES = [("characters", "人物"), ("events", "事件"), ("timeline", "时间线")]


def load_manifest(path=None, inline=None):
    """读要素清单：--manifest 文件 或 --inline 内联 JSON，二者给一。"""
    if inline:
        raw = inline
    elif path:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    else:
        raise ValueError("--manifest 与 --inline 至少给一个")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("manifest 根节点必须是 dict")
    for cat, _ in CATEGORIES:
        items = data.get(cat, [])
        if not isinstance(items, list):
            raise ValueError("manifest.%s 必须是 list" % cat)
        for it in items:
            if not isinstance(it, dict) or not str(it.get("key", "")).strip():
                raise ValueError("manifest.%s 每项须含非空 key：%r" % (cat, it))
            if not isinstance(it.get("aliases", []), list):
                raise ValueError("manifest.%s 的 aliases 必须是 list：%r" % (cat, it))
    return data


def judge(summary_text, manifest):
    """逐要素判定覆盖度。

    返回 (rows, stats)：
    rows = [{"category": "人物", "key": ..., "aliases": [...], "hit_word": 命中词或 None}, ...]
    stats = {类别中文名: (命中数, 总数)}，顺序同 CATEGORIES。
    """
    rows = []
    stats = {}
    for cat, label in CATEGORIES:
        items = manifest.get(cat, [])
        hit_n = 0
        for it in items:
            key = str(it["key"])
            aliases = [str(a) for a in it.get("aliases", [])]
            hit_word = key if key in summary_text else next(
                (a for a in aliases if a in summary_text), None)
            if hit_word:
                hit_n += 1
            rows.append({"category": label, "key": key,
                         "aliases": aliases, "hit_word": hit_word})
        stats[label] = (hit_n, len(items))
    return rows, stats


def _print_table(rows, stats):
    print("%-6s  %-24s  %-28s  %s" % ("类别", "要素", "别名", "结果（命中词）"))
    print("-" * 84)
    for r in rows:
        if r["hit_word"]:
            verdict = "命中  ←「%s」" % r["hit_word"]
        else:
            verdict = "未命中"
        print("%-6s  %-24s  %-28s  %s"
              % (r["category"], r["key"][:24], "|".join(r["aliases"])[:28], verdict))
    print("-" * 84)
    parts = ["%s %d/%d" % (label, stats[label][0], stats[label][1]) for _, label in CATEGORIES]
    total_hit = sum(v[0] for v in stats.values())
    total = sum(v[1] for v in stats.values())
    print("统计：%s ｜ 总计 %d/%d" % ("  ".join(parts), total_hit, total))
    if total_hit == total:
        print("结论：全部命中（覆盖度 100%）")
    else:
        missing = [r["key"] for r in rows if not r["hit_word"]]
        print("结论：存在缺失 %d 项：%s" % (len(missing), "、".join(m[:20] for m in missing)))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="摘要覆盖度断言：关键要素清单（人物/事件/时间线）反向断言，退出码 0=全命中 1=有缺失")
    ap.add_argument("--summary", help="摘要文本文件路径")
    ap.add_argument("--summary-text", help="直接给摘要文本（免落盘，优先级高于 --summary）")
    ap.add_argument("--manifest", help="要素清单 JSON 文件（schema 见脚本 docstring）")
    ap.add_argument("--inline", help="要素清单内联 JSON 字符串（与 --manifest 二选一）")
    args = ap.parse_args(argv)

    try:
        if args.summary_text is not None:
            text = args.summary_text
        elif args.summary:
            with open(args.summary, encoding="utf-8") as f:
                text = f.read()
        else:
            ap.error("需要 --summary <文件> 或 --summary-text <文本>")
            return 2
        manifest = load_manifest(path=args.manifest, inline=args.inline)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("[错误] %s" % e)
        return 2
    rows, stats = judge(text, manifest)
    _print_table(rows, stats)
    return 0 if all(h == t for h, t in stats.values()) and stats else 1


if __name__ == "__main__":
    sys.exit(main())
