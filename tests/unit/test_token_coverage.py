# -*- coding: utf-8 -*-
"""§7.3 护栏：令牌覆盖率计数门禁（U-02/03/04）。

四类字面量计数**只准降不准升**——新代码必须走 Theme 令牌（动效五档/圆角四档/
语义 soft 色/字重）。需要新增例外时先收窄基线并写明理由，不许悄悄抬。
基线 = U-02 收敛 sweep 后（2026-09-14）。
"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 基线（只准降）：rgba_theme=收敛后剩余 3 处（ReaderView 阅读器高亮族，
# 刻意与写作主题解耦）……以实际 sweep 后计数冻结
BASELINE = {
    "rgba_theme": 3,    # Qt.rgba(Theme.x.r, …) 手调淡底
    "duration_lit": 24, # duration: <数字字面量>
    "radius_lit": 85,   # radius: <数字字面量>
    "bold": 80,         # font.bold: true（U-05 迁 font.weight 后只降）
}

PATS = {
    "rgba_theme": re.compile(r"Qt\.rgba\(Theme\.\w+\.r"),
    "duration_lit": re.compile(r"duration:\s*\d+"),
    "radius_lit": re.compile(r"radius:\s*\d+"),
    "bold": re.compile(r"font\.bold:\s*true"),
}


def test_token_counts_never_rise():
    counts = {k: 0 for k in PATS}
    for f in glob.glob(os.path.join(ROOT, "app", "ui", "qml", "**", "*.qml"), recursive=True):
        s = open(f, encoding="utf-8").read()
        for k, p in PATS.items():
            counts[k] += len(p.findall(s))
    over = {k: (counts[k], BASELINE[k]) for k in PATS if counts[k] > BASELINE[k]}
    assert not over, ("令牌字面量计数回升（只准降不准升）：%s。"
                      "新代码请走 Theme 令牌；确需例外请同步下调 BASELINE 并注记理由" % over)
