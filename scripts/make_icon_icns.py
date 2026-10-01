# -*- coding: utf-8 -*-
"""生成 assets/icon.icns（macOS 应用图标）

几何与 make_icon.py 同源（琥珀圆角底 + 宋体「文」），差别只在尺寸：macOS 的
iconset 要 16…1024 全套（1x/2x 各一张），拿 256px 的 .png 硬放到 1024 在 Finder
大图标视图里会糊成一片，所以按尺寸重画，最后交系统 `iconutil` 收成 .icns。

产物进仓库（发版流水线只读不重算，构建机不需要 Pillow）；仅 macOS 可跑。

用法：python scripts/make_icon_icns.py [--out assets/icon.icns]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_icon import BG, FG, RADIUS, load_font   # noqa: E402

BASE = 256                      # make_icon 的出图基准，其他尺寸按比例缩

# iconset 尺寸表：(基准边长, 倍率) → 文件名。@2x 即 2 倍，凑齐全套 16…1024
ICONSET = [
    (16, 1), (16, 2),
    (32, 1), (32, 2),
    (128, 1), (128, 2),
    (256, 1), (256, 2),
    (512, 1), (512, 2),
]


def render(size: int):
    from PIL import Image, ImageDraw
    scale = size / BASE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size),
                                           radius=max(1, round(RADIUS * scale)), fill=255)
    img.paste(Image.new("RGBA", (size, size), BG), (0, 0), mask)
    draw = ImageDraw.Draw(img)
    font = load_font(max(8, round(150 * scale)))
    bbox = draw.textbbox((0, 0), "文", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - 4 * scale),
              "文", font=font, fill=FG)
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.icns"))
    args = ap.parse_args()
    if sys.platform != "darwin":
        print("ICON_SKIP 非 macOS（.icns 由 iconutil 生成）", file=sys.stderr)
        return 1
    iconset = tempfile.mkdtemp(prefix="qbn_", suffix=".iconset")
    try:
        for base, mult in ICONSET:
            px = base * mult
            suffix = "@2x" if mult == 2 else ""
            name = "icon_%dx%d%s.png" % (base, base, suffix)
            render(px).save(os.path.join(iconset, name))
        r = subprocess.run(["iconutil", "-c", "icns", iconset, "--output", args.out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(iconset, ignore_errors=True)
    print("ICON_OK", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
