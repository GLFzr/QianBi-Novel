#!/usr/bin/env python3
"""audit_tokens.py — QML 视觉 token 纪律审计（v0.17「成熟化」防线）

拦住四类会悄悄回潮的样式违例：
  T1  font.pixelSize 裸数字 10（历史上 52 处地下字号，现必须走 Theme.fsMicro）
  T2  footer: Row { anchors.* }（Dialog footer 锚点反模式：挤压内容、按钮贴边）
  T3  业务 QML 里的 #hex 裸色（Theme.qml/ReaderView.qml/DialogBg.qml 白名单外）
  T4  卡片色（Theme.bgCard）Rectangle 无 border（同色糊底，audit_borders 的补充）

用法：python tools/audit_tokens.py [--fix]
  默认只报告；--fix 仅对 T1 自动改写为 Theme.fsMicro。
退出码：有违例=1，全绿=0（可编入发布闸门）。
"""
import io
import re
import sys
from pathlib import Path

QML_ROOT = Path(__file__).resolve().parent.parent / "app" / "ui" / "qml"

# T3 白名单：token 定义处、阅读器自有主题体系（刻意与写作主题隔离）、投影黑色
T3_WHITELIST = {"Theme.qml", "ReaderView.qml", "DialogBg.qml"}

RE_PIXEL10 = re.compile(r"font\.pixelSize:\s*10(?![0-9])")
RE_FOOTER_ROW = re.compile(r"footer:\s*Row\s*\{")
RE_HEX = re.compile(r'"#[0-9A-Fa-f]{3,8}"')
RE_BGCARD_RECT = re.compile(r"color:\s*Theme\.bgCard\b")


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def audit_file(path: Path) -> list:
    issues = []
    text = io.open(path, encoding="utf-8").read()
    rel = path.name

    for m in RE_PIXEL10.finditer(text):
        issues.append(("T1", _line_of(text, m.start()),
                       "裸字号 10 → 用 Theme.fsMicro"))

    if RE_FOOTER_ROW.search(text):
        for m in RE_FOOTER_ROW.finditer(text):
            # 只拦带锚点的用法（不带锚点的 Row footer 合法但少见，一并提示改 RowLayout）
            tail = text[m.end():m.end() + 200]
            if re.search(r"anchors\.(right|left|fill)", tail):
                issues.append(("T2", _line_of(text, m.start()),
                               "footer 用锚点定位 → RowLayout + Item { Layout.fillWidth: true }"))

    if rel not in T3_WHITELIST:
        for m in RE_HEX.finditer(text):
            issues.append(("T3", _line_of(text, m.start()),
                           "裸 #hex 颜色 → 加进 Theme 主题表或用语义 token"))

    # T4：含 color: Theme.bgCard 的 Rectangle 块是否带边框手段
    #（自身 border.width，或块内 1px Theme.border 发丝线分隔子元素）
    # 用括号深度找到外层元素的完整块再查，避免被第一个子元素截断
    for m in RE_BGCARD_RECT.finditer(text):
        start = m.start()
        depth_before = text.count("{", 0, start) - text.count("}", 0, start)
        depth, i = depth_before, start
        while i < len(text) and depth >= depth_before:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        seg = text[start:i]
        if "border.width" not in seg and "color: Theme.border" not in seg:
            issues.append(("T4", _line_of(text, start),
                           "bgCard 卡片无 border → 补 border.width:1 / Theme.border"))
    return issues


def main() -> int:
    fix = "--fix" in sys.argv
    total = 0
    for qml in sorted(QML_ROOT.rglob("*.qml")):
        issues = audit_file(qml)
        if not issues:
            continue
        rel = qml.relative_to(QML_ROOT.parent)
        for kind, line, msg in issues:
            print(f"[{kind}] {rel}:{line}  {msg}")
        total += len(issues)
        if fix:
            src = io.open(qml, encoding="utf-8").read()
            src = RE_PIXEL10.sub("font.pixelSize: Theme.fsMicro", src)
            io.open(qml, "w", encoding="utf-8", newline="").write(src)

    print(f"TOTAL = {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
