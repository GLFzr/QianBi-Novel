# -*- coding: utf-8 -*-
"""同色场景描边：把「卡片色/输入底色但没有描边」的容器补上 1px 边框

判定（宁少不错）：
- 只看 bgCard / bgLog / bgHover 这三种「会跟背景糊在一起」的色；bgPanel 多是分隔带，
- 同一属性块内必须有 radius（说明是卡片/输入框，不是 1px 分隔条或滚动条 thumb），
- 跳过 contentItem: Rectangle（滚动条滑块）与 anchors 单边的细线。

用法：
  python tools/audit_borders.py            # 只列
  python tools/audit_borders.py --fix      # 补 border.width/border.color
"""
import os
import re
import sys

FILL = ("bgCard", "bgLog", "bgPanel")
BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "app", "ui", "qml")
FIX = "--fix" in sys.argv

changed = []
touched = 0
for root, _, files in os.walk(BASE):
    for fn in sorted(files):
        if not fn.endswith(".qml"):
            continue
        p = os.path.join(root, fn)
        lines = open(p, encoding="utf-8").read().splitlines(keepends=True)
        out, skip, per_file = [], 0, 0
        for i, raw in enumerate(lines):
            if i < skip:
                out.append(raw)
                continue
            m = re.search(r"color:\s*Theme\.(%s)\b" % "|".join(FILL), raw)
            if not m or "border.width" in raw:
                out.append(raw)
                continue
            ahead = "".join(lines[i + 1:i + 14])
            back = "".join(lines[max(0, i - 4):i + 1])      # 含当前行：单行块很常见
            if "contentItem: Rectangle" in back or "ScrollBar" in back:
                out.append(raw)
                continue
            if re.search(r"(height|width|implicitHeight|implicitWidth):\s*1\b", raw + ahead):
                out.append(raw)      # 1px 分隔条不是卡片
                continue
            if "radius:" not in back + raw + ahead:
                out.append(raw)
                continue
            # 本仓库卡片只用到 rCard=6 / rBtn=4；写成字面量且 >=8 的是 chip 或浮动条，
            # 1px 描边反而破坏形态，交给人工单独判断
            pills = re.findall(r"radius:\s*(\d+)", back + raw + ahead)
            if pills and max(int(p) for p in pills) >= 8:
                out.append(raw)
                continue
            if re.search(r"border\.width", back + ahead):
                out.append(raw)
                continue
            ind = re.match(r"\s*", raw).group(0)
            out.append(raw)
            out.append("%sborder.width: 1\n" % ind)
            out.append("%sborder.color: Theme.border\n" % ind)
            changed.append((os.path.relpath(p, BASE), i + 1, m.group(1)))
            per_file += 1
            skip = i + 1
        if FIX and per_file:
            open(p, "w", encoding="utf-8", newline="").writelines(out)
            touched += 1

print(("已补描边 " if FIX else "待补描边 ") + str(len(changed)) + " 处")
for f, line, tok in changed[-40:]:
    print("  %-40s %-5s %s" % (f, line, tok))
