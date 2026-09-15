# -*- coding: utf-8 -*-
"""§7.3 护栏：令牌覆盖率计数门禁（U-02/03/04）。

四类字面量计数**只准降不准升**——新代码必须走 Theme 令牌（动效五档/圆角四档/
语义 soft 色/字重）。需要新增例外时先收窄基线并写明理由，不许悄悄抬。
基线 = U-02 收敛 sweep 后（2026-09-14）。

恒真事故留档（WP-05）：ROOT 曾少上溯一层 ⇒ glob 指到 tests/app/ui/qml/**，
实测命中 0 个文件 ⇒ 四类计数恒 0、永远绿。现：目录缺失或扫描数 ≤40 直接 fail。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QML_DIR = os.path.join(ROOT, "app", "ui", "qml")

# 基线（只准降）。WP-05 实测记准剩余 3 处的真身：AppButton.qml:66/:68 危险/成功
# 悬停 tint（alpha 随 hovered 动态变，无法预合成静态令牌）+ QueueRow.qml:26 stale
# 淡底（0.06）。原先注记的「ReaderView 阅读器高亮族」与事实不符，已按实修正。
BASELINE = {
    "rgba_theme": 3,    # Qt.rgba(Theme.x.r, …) 手调淡底
    "duration_lit": 1, # duration: <数字字面量>
    "radius_lit": 60,   # radius: <数字字面量>
    "bold": 52,         # font.bold: true（U-05 迁 font.weight 后只降）
}

PATS = {
    "rgba_theme": re.compile(r"Qt\.rgba\(Theme\.\w+\.r"),
    "duration_lit": re.compile(r"duration:\s*\d+"),
    "radius_lit": re.compile(r"radius:\s*\d+"),
    "bold": re.compile(r"font\.bold:\s*true"),
}


def test_token_counts_never_rise():
    assert os.path.isdir(QML_DIR), f"QML 目录不存在，扫描面失效：{QML_DIR}"
    files = glob.glob(os.path.join(QML_DIR, "**", "*.qml"), recursive=True)
    assert len(files) > 40, (
        f"只扫到 {len(files)} 个 .qml（应 >40）——扫描面又失效了（恒真护栏事故重演）")
    counts = {k: 0 for k in PATS}
    for f in files:
        s = open(f, encoding="utf-8").read()
        for k, p in PATS.items():
            counts[k] += len(p.findall(s))
    print(f"扫到 {len(files)} 个 .qml：{counts}")
    over = {k: (counts[k], BASELINE[k]) for k in PATS if counts[k] > BASELINE[k]}
    assert not over, ("令牌字面量计数回升（只准降不准升）：%s。"
                      "新代码请走 Theme 令牌；确需例外请同步下调 BASELINE 并注记理由" % over)
