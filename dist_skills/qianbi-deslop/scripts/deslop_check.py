# -*- coding: utf-8 -*-
"""网文去 AI 味 lint CLI（qianbi-deslop 导出包）——由上游导出管线生成

引擎为 qianbi-novel app/deslop.py + app/core/deslop_metrics.py 的逐字副本
（scripts/_vendor/qianbi_vendor/，MIT License, Copyright (c) 2026 GLFzr）。
上游随真机语料持续校准规则；本包随上游版本同步，请勿手改本文件。

用法：
    python deslop_check.py 章节文件.txt            # 人读报告
    python deslop_check.py 章节文件.txt --json     # 机器可读 JSON（金标同口径）
    python deslop_check.py - < 章节文件.txt        # stdin
    python deslop_check.py --rules                 # 列出本版全部规则 ID

退出码：0 = 无 blocking；1 = 存在 blocking（可作门禁）；2 = 用法/IO 错误。
仅报告，不改写。目标只是读感，不承诺任何 AIGC 检测器分数。
"""
import argparse
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_vendor"))

from qbn_exported.qianbi_vendor import deslop as engine  # noqa: E402


def _extract_rule_ids(src: str) -> list:
    ids = []
    for m in re.finditer(
            r'(?:add|add_span)\("([a-z0-9-]+)"|rule="([a-z0-9-]+)"', src):
        rid = m.group(1) or m.group(2)
        if rid not in ids:
            ids.append(rid)
    return ids


def _report_json(text: str) -> str:
    findings = [{
        "rule": f.rule, "level": f.level, "message": f.message,
        "text": f.text, "start": f.start, "end": f.end,
        "fix_hint": f.fix_hint,
    } for f in engine.scan_text(text)]
    payload = {
        "chars": len(text),
        "blocking": sum(1 for x in findings if x["level"] == "blocking"),
        "advisory": sum(1 for x in findings if x["level"] == "advisory"),
        "findings": findings,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _report_human(text: str) -> str:
    findings = engine.scan_text(text)
    lines = ["扫描完成：%d 字，blocking %d 处，advisory %d 处"
             % (len(text),
                sum(1 for f in findings if f.level == "blocking"),
                sum(1 for f in findings if f.level == "advisory"))]
    for f in findings:
        lines.append("L%d [%s] %s：%s「%s」修法：%s"
                     % (_line_of(text, f.start), f.level, f.rule, f.message,
                        f.text[:40], f.fix_hint or "见 SKILL.md 改写方向"))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deslop_check.py")
    ap.add_argument("file", nargs="?", help="章节文本文件；- 表示 stdin")
    ap.add_argument("--json", action="store_true", help="机器可读 JSON")
    ap.add_argument("--rules", action="store_true",
                    help="列出本版全部规则 ID（来自引擎源码）")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    if args.rules:
        src_path = os.path.join(_HERE, "_vendor", "qbn_exported",
                                "qianbi_vendor", "deslop.py")
        with io.open(src_path, encoding="utf-8") as f:
            ids = _extract_rule_ids(f.read())
        print("本版规则 %d 条：" % len(ids))
        for rid in ids:
            print("  " + rid)
        return 0

    if not args.file:
        ap.error("需要 章节文件.txt（或 --rules）")
        return 2

    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            with io.open(args.file, encoding="utf-8") as f:
                text = f.read()
    except OSError as exc:
        print("读取失败：%s" % exc, file=sys.stderr)
        return 2

    if args.json:
        sys.stdout.write(_report_json(text) + "\n")
    else:
        print(_report_human(text))
    blocking = sum(1 for f in engine.scan_text(text) if f.level == "blocking")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
