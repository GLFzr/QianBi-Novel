# -*- coding: utf-8 -*-
"""续写状态卡校验 CLI（qianbi-state-card 导出包）——由上游导出管线生成

schema 由 qianbi-novel app/core/state_card.py 源码抽取生成（七栏栏题/优先级/
字节预算）。用于：外部 agent 手写/改造状态卡后的结构自检（引擎同款渲染契约）。

用法：
    python state_card_validate.py 状态卡.md            # 人读报告
    python state_card_validate.py 状态卡.md --json     # 机器可读（金标同口径）
    python state_card_validate.py 状态卡.md --budget 12288

退出码：0 = 合格；1 = 有违例；2 = 用法/IO 错误。
"""
import argparse
import io
import json
import re
import sys

# 由导出管线注入：七栏栏题（按渲染顺序）与默认字节预算（state_card.BYTE_BUDGET）
CANONICAL_TITLES = ['当前位置', '下一章承诺', '活跃伏笔(作者真相)', '连贯性风险', '核心角色状态', '长期约束(正则must)', '近三章速记(读者已知)']
DEFAULT_BUDGET = 12288

TITLE_RE = re.compile(r"^# 续写状态卡（第(\d+)章）\s*$")
HEADER_RE = re.compile(r"^##\s*(.+?)\s*$")


def validate(text: str, budget: int) -> dict:
    problems = []
    lines = text.splitlines()
    if not lines or not TITLE_RE.match(lines[0].strip()):
        problems.append({
            "check": "title",
            "message": "首行须为「# 续写状态卡（第N章）」，实际：%r"
                       % (lines[0][:40] if lines else "<空文件>"),
        })
    headers = [(i, m.group(1)) for i, m in
               ((i, HEADER_RE.match(ln.strip())) for i, ln in enumerate(lines))
               if m]
    seen = []
    for lineno, title in headers:
        if title not in CANONICAL_TITLES:
            problems.append({
                "check": "column",
                "line": lineno + 1,
                "message": "未知栏「%s」（七栏之一：%s）"
                           % (title, "、".join(CANONICAL_TITLES)),
            })
        elif title in seen:
            problems.append({
                "check": "column", "line": lineno + 1,
                "message": "栏「%s」重复出现" % title,
            })
        else:
            if seen and CANONICAL_TITLES.index(title) < max(
                    CANONICAL_TITLES.index(s) for s in seen):
                problems.append({
                    "check": "column-order", "line": lineno + 1,
                    "message": "栏「%s」不在规范顺序（%s）"
                               % (title, " → ".join(CANONICAL_TITLES)),
                })
            seen.append(title)
    # 栏内条目必须是「- 」整项（渲染契约：整项取舍不截半句）
    cur_col = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        m = HEADER_RE.match(stripped)
        if m:
            cur_col = m.group(1)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if cur_col and not stripped.startswith("- "):
            problems.append({
                "check": "item-format", "line": i + 1,
                "message": "栏「%s」条目须以「- 」起头：%r" % (cur_col,
                                                             stripped[:30]),
            })
    size = len(text.encode("utf-8"))
    if size > budget:
        problems.append({
            "check": "budget",
            "message": "状态卡 %d 字节超出预算 %d（超 %d 字节；上游按 P5→P1 "
                       "优先级整项裁剪）" % (size, budget, size - budget),
        })
    return {
        "bytes": size, "budget": budget,
        "columns_present": [t for t in CANONICAL_TITLES if t in seen],
        "problems": problems, "ok": not problems,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="state_card_validate.py")
    ap.add_argument("file")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    try:
        with io.open(args.file, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print("读取失败：%s" % exc, file=sys.stderr)
        return 2

    report = validate(text, args.budget)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1))
    elif report["ok"]:
        print("状态卡合格：%d 字节（预算 %d），栏目 %s"
              % (report["bytes"], report["budget"],
                 "、".join(report["columns_present"]) or "（无内容栏）"))
    else:
        for p in report["problems"]:
            print("违例 [%s]%s：%s" % (p["check"],
                                      (" L%d" % p["line"]) if p.get("line")
                                      else "", p["message"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
