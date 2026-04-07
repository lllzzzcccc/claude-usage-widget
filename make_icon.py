"""
生成 macOS 应用图标 (.icns)。

设计：深色渐变圆角方形背景（Claude 品牌橙棕色系），中央白色 "✦" 星芒。
输出到 ~/Applications/ClaudeUsage.app/Contents/Resources/AppIcon.icns
"""

import os
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFilter

APP_PATH = os.path.expanduser("~/Applications/ClaudeUsage.app")
RESOURCES_DIR = os.path.join(APP_PATH, "Contents", "Resources")
ICONSET_DIR = "/tmp/ClaudeUsage.iconset"
ICNS_PATH = os.path.join(RESOURCES_DIR, "AppIcon.icns")


def draw_icon(size: int) -> Image.Image:
    """在给定尺寸上绘制图标。"""
    # 超采样 4x 再缩小，抗锯齿
    scale = 4
    s = size * scale

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角矩形背景（径向渐变的近似：先画底色，再盖一层径向渐变高光）
    corner = int(s * 0.22)

    # 底色：深棕/暗橙渐变（Claude 品牌色系）
    bg_top = (217, 119, 87)     # #D97757 - Claude orange
    bg_bot = (139, 60, 30)      # 更深的橙棕

    # 自上而下线性渐变
    gradient = Image.new("RGBA", (s, s), bg_top)
    gdraw = ImageDraw.Draw(gradient)
    for y in range(s):
        t = y / s
        r = int(bg_top[0] * (1 - t) + bg_bot[0] * t)
        g = int(bg_top[1] * (1 - t) + bg_bot[1] * t)
        b = int(bg_top[2] * (1 - t) + bg_bot[2] * t)
        gdraw.line([(0, y), (s, y)], fill=(r, g, b, 255))

    # 用圆角矩形 mask 裁剪渐变
    mask = Image.new("L", (s, s), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle([(0, 0), (s - 1, s - 1)], radius=corner, fill=255)
    img.paste(gradient, (0, 0), mask)

    # 绘制中央 Claude 风格的星芒 "✦" （四角星）
    # 四角星由两个菱形叠加：一个横长一个竖长
    cx, cy = s / 2, s / 2
    arm_long = s * 0.36
    arm_short = s * 0.08

    star_color = (255, 255, 255, 255)

    # 竖向菱形
    vertical = [
        (cx, cy - arm_long),
        (cx + arm_short, cy),
        (cx, cy + arm_long),
        (cx - arm_short, cy),
    ]
    draw.polygon(vertical, fill=star_color)

    # 横向菱形
    horizontal = [
        (cx - arm_long, cy),
        (cx, cy - arm_short),
        (cx + arm_long, cy),
        (cx, cy + arm_short),
    ]
    draw.polygon(horizontal, fill=star_color)

    # 中央小圆点强调
    dot_r = s * 0.03
    draw.ellipse(
        [(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)],
        fill=star_color,
    )

    # 缩回目标尺寸（LANCZOS 抗锯齿）
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(RESOURCES_DIR, exist_ok=True)
    if os.path.exists(ICONSET_DIR):
        shutil.rmtree(ICONSET_DIR)
    os.makedirs(ICONSET_DIR)

    # macOS iconset 要求的尺寸
    specs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for size, name in specs:
        img = draw_icon(size)
        img.save(os.path.join(ICONSET_DIR, name))
        print(f"  生成 {name} ({size}x{size})")

    # 合并为 .icns
    subprocess.run(
        ["iconutil", "-c", "icns", ICONSET_DIR, "-o", ICNS_PATH],
        check=True,
    )
    print(f"\n✓ 已输出: {ICNS_PATH}")


if __name__ == "__main__":
    main()
