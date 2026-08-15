# -*- coding: utf-8 -*-
"""生成应用图标 assets/icon.ico：琥珀圆角底 + 宋体「文」字（深夜编辑部设计系统）"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")
os.makedirs(OUT_DIR, exist_ok=True)

SIZE = 256
RADIUS = 56
BG = (226, 177, 91, 255)      # #E2B15B 琥珀
FG = (29, 27, 23, 255)        # #1D1B17 深墨

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simsun.ttc",      # 宋体（贴合正文气质）
    r"C:\Windows\Fonts\msyhbd.ttc",      # 微软雅黑 Bold（回退）
    r"C:\Windows\Fonts\msyh.ttc",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE, SIZE), radius=RADIUS, fill=255)
    bg = Image.new("RGBA", (SIZE, SIZE), BG)
    img.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    font = load_font(150)
    text = "文"
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - w) / 2 - bbox[0]
    y = (SIZE - h) / 2 - bbox[1] - 4
    draw.text((x, y), text, font=font, fill=FG)
    return img


def main():
    img = render()
    png_path = os.path.join(OUT_DIR, "icon.png")
    ico_path = os.path.join(OUT_DIR, "icon.ico")
    img.save(png_path)
    img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ICON_OK", ico_path)


if __name__ == "__main__":
    main()
