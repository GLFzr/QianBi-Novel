# -*- coding: utf-8 -*-
"""§5.4 QML 红线静态扫描（WP-05 新增仪器，台账 §7.3 点名此前查无此件）。

扫全部 app/ui/qml/**/*.qml，命中即红：
  ① MultiEffect（禁用：delegate 内成本爆炸；全库手绘柔影）
  ② layer.effect（同 ① 同族，实时特效层）
  ③ Canvas {（禁用）
  ④ delegate/header/footer 祖先域内缓存 property color（Theme 变更不重算、
     每实例常驻，台账 §5.4 明令）
  ⑤ Layout/定位器（Row/Column/Grid/Flow）的直接子项上用 anchors（Qt 未定义行为，
     运行期即告警；ContractPanel.qml:133 曾实锤）

实现：按列序处理 {/} 事件建块栈（行内开合也能正确配对）；行注释先剥。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QML_ROOT = os.path.join(ROOT, "app", "ui", "qml")

OPEN_RE = re.compile(r"([A-Za-z_][\w.]*)\s*$")
# `delegate: Item {` 的块键是 Item（类型名）——delegate 属性名必须单独捕获，
# 否则 ①③④ 的 delegate 域判定永不命中（变异验证抓出过这个洞）
DELEGATE_PROP_RE = re.compile(r"\b(delegate|header|footer)\s*:\s*[A-Za-z_][\w.]*\s*$")
LAYOUT_PARENTS = {"Row", "Column", "Grid", "Flow"}
DELEGATE_KEYS = {"delegate", "header", "footer", "Component"}


def _qml_files():
    out = []
    for dp, _dn, fns in os.walk(QML_ROOT):
        for fn in fns:
            if fn.endswith(".qml"):
                out.append(os.path.join(dp, fn))
    return out


def _parse_blocks(lines):
    """返回 spans=[(key, start, end)]（1 基行号），并保证 start/end 逐块配对。"""
    spans = []
    stack = []  # (key, start_line)
    for i, raw in enumerate(lines, 1):
        code = raw.split("//")[0]
        depth = 0
        buf = ""
        for ch in code:
            if ch == "{":
                buf_s = buf.strip()
                m = OPEN_RE.search(buf_s)
                md = DELEGATE_PROP_RE.search(buf_s)
                key = md.group(1) if md else (m.group(1) if m else "")
                stack.append((key, i))
                buf = ""
            elif ch == "}":
                if stack:
                    spans.append((stack[-1][0], stack[-1][1], i))
                    stack.pop()
                buf = ""
            else:
                buf += ch
    return spans


def _parents_of(spans, start, end):
    return [k for (k, s, e) in spans if s < start and e >= end]


def _nearest_parent_key(spans, start, end):
    """最近祖先块的键（只有直接父级是 Layout/定位器才构成红线⑤，
    祖先链上更外层的 Layout 管不到孙块的布局）。"""
    cand = [(s, k) for (k, s, e) in spans if s < start and e >= end]
    return max(cand)[1] if cand else ""


def test_qml_red_lines():
    files = _qml_files()
    assert len(files) > 40, "QML 扫描面失效（文件数异常）"
    bad = []
    for path in files:
        rel = os.path.relpath(path, ROOT)
        lines = open(path, encoding="utf-8").read().splitlines()
        spans = _parse_blocks(lines)
        for i, raw in enumerate(lines, 1):
            code = raw.split("//")[0]
            cand = [(k, s, e) for k, s, e in spans if s <= i <= e]
            in_delegate = False
            if cand:
                innermost = min(cand, key=lambda t: (t[2] - t[1], -t[1]))
                chain = set(_parents_of(spans, innermost[1], innermost[2]))
                chain.add(innermost[0])
                in_delegate = bool(chain & DELEGATE_KEYS)
            # ①②③④ 是 delegate 域红线（AppIcon/AppCheck 等组件自身合法）
            if in_delegate:
                if "MultiEffect" in code:
                    bad.append(f"{rel}:{i} delegate 内出现 MultiEffect（红线①）")
                if "layer.effect" in code:
                    bad.append(f"{rel}:{i} delegate 内出现 layer.effect（红线①同族）")
                if re.search(r"\bCanvas\s*\{", code):
                    bad.append(f"{rel}:{i} delegate 内出现 Canvas（红线③）")
                if re.search(r"property\s+color\b", code):
                    bad.append(f"{rel}:{i} delegate 域内缓存 property color（红线④）")
            # ⑤ 全局：直接父级是 *Layout 时 anchors = Qt 未定义行为（引擎运行期
            # 即告警 "Detected anchors on an item that is managed by a layout"）。
            # 指南口径是「Layout 子项」——普通定位器 Row/Column 内
            # anchors.verticalCenter 是 Qt 允许的惯用法，不算违规。
            if re.search(r"anchors\.\w+\s*:", code) and cand:
                pk = _nearest_parent_key(spans, innermost[1], innermost[2])
                if pk.endswith("Layout"):
                    bad.append(f"{rel}:{i} Layout 子项上 anchors（红线⑤，Qt 未定义行为）")
    assert not bad, "QML 红线违规：" + " | ".join(bad)
