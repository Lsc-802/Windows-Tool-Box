# -*- coding: utf-8 -*-
"""生成 Windows Tool Box 应用图标 icon.ico（蓝色圆角方块 + 白色 WT）。"""
import os
from PIL import Image, ImageDraw, ImageFont

SIZE = 256
FONT_PATH = r"C:\Windows\Fonts\msyhbd.ttc"  # 微软雅黑粗体


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 蓝色圆角方块（渐变效果用两段色带近似）
    radius = 52
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=radius,
                        fill=(22, 119, 255, 255))
    # 底部轻微高光
    d.rounded_rectangle([8, SIZE - 90, SIZE - 8, SIZE - 8], radius=radius,
                        fill=(64, 150, 255, 120))
    d.rounded_rectangle([8, SIZE - 70, SIZE - 8, SIZE - 8], radius=radius,
                        fill=(110, 180, 255, 90))

    # 白色 "WT" 文字
    if os.path.exists(FONT_PATH):
        font = ImageFont.truetype(FONT_PATH, 118)
    else:
        font = ImageFont.load_default()
    text = "WT"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1]),
           text, font=font, fill=(255, 255, 255, 255))

    img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                 (64, 64), (128, 128), (256, 256)])
    print("icon.ico 已生成")


if __name__ == "__main__":
    main()
