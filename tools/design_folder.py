r"""迭代"原生文件夹"形状（Pillow 快速出图，定稿后再移植到 wx 图元）。

## 用户提供的参照

Windows Explorer 的文件夹图标（`shell32.dll` 的 folder）：
**主体是圆角矩形，左上有一个"舌片"，舌片右侧斜切到主体顶边。**
用户要求"照着它再画一版，让形状更接近原生的文件夹"。

## 为什么要先在这里迭代

在 wx 窗口里改一次、跑一次、截图一次要几十秒，而且**窗口截图抓不到
原生控件**（见 `_probe_guard` / 项目文档）。Pillow 出图是毫秒级的，
而且几何是**归一化坐标**，和 `_draw_icon` 的图元一一对应。

定稿后把这里的点表抄进 `widgets.icon_path` 即可。
"""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "design")
FONT = r"C:\Windows\Fonts\msyhbd.ttc"

#: 归一化轮廓（以 (cx,cy) 为中心、size 为边长；坐标范围约 ±0.5）
#:
#: 顺序：左下 → 沿左边向上 → 舌片顶 → 斜切 → 主体顶 → 右边向下 → 回左下
#: 每个角用 2 个点切出**微小圆角**（1/16 边长），24px 下看不出是折线。
NATIVE_FOLDER = [
    # ## 第三版：再压扁一点（用户 2026-10-17 第三次反馈）
    #
    # > "只需要把你画的文件夹再压扁一点点，它就非常合适了。"
    #
    # 第一版 1.47（太扁、像托盘）→ 第二版 1.16（用户仍觉得"高"）→
    # **现在 0.88 / 0.68 ≈ 1.29**。
    #
    # 舌片凸起也从 0.10 收到 0.12（主体顶 -0.22 / 舌片顶 -0.34），
    # 并且把舌片的水平段缩短（-0.44..-0.14，占 34%），
    # 主体顶边相应变长（0.00..0.42，占 48%）—— 参考图就是这个比例。
    #
    # 左下角（圆角）
    (-0.44, 0.26), (-0.40, 0.32), (-0.34, 0.34),
    # 下边
    (0.34, 0.34), (0.40, 0.32),
    # 右下角
    (0.44, 0.26),
    # 右边向上
    (0.44, -0.16), (0.42, -0.22),
    # **主体顶边：水平**（从右向左，占 48%）
    (0.00, -0.22),
    # **短斜切**
    (-0.14, -0.34),
    # **舌片顶边：水平**（占 34%）
    (-0.38, -0.34),
    # 左上角（小圆角）
    (-0.43, -0.28), (-0.44, -0.20),
]


def polygon_points(cx, cy, size, norm):
    return [(cx + nx * size, cy + ny * size) for nx, ny in norm]


def draw_folder(d, cx, cy, size, colour, norm=NATIVE_FOLDER):
    d.polygon(polygon_points(cx, cy, size, norm), fill=colour)


def draw_old_folder(d, cx, cy, size, colour):
    """改造前的版本：两个实心矩形叠出来（舌片 + 主体）。"""
    s = size
    d.rectangle([cx - 0.42 * s, cy - 0.30 * s, cx - 0.02 * s, cy - 0.06 * s], fill=colour)
    d.rectangle([cx - 0.42 * s, cy - 0.12 * s, cx + 0.42 * s, cy + 0.32 * s], fill=colour)


def render():
    bg, fg = "#FFFFFF", "#2B2B2B"
    W, H = 720, 420
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT, 17)
    small = ImageFont.truetype(FONT, 13)

    d.text((24, 16), "文件夹图标：改造前 vs 参照 Explorer", font=title, fill=fg)

    # 大图对比
    draw_old_folder(d, 150, 120, 120, fg)
    d.text((95, 190), "改造前（两个矩形）", font=small, fill=fg)

    draw_folder(d, 330, 120, 120, fg)
    d.text((255, 190), "新版（原生轮廓）", font=small, fill=fg)

    # **真实尺寸**：图标按"文字高"排，本机 175% 下约 42 物理像素。
    # 24 逻辑像素的预览**偏悲观**（圆角被吃掉了），实机会更清楚。
    d.text((500, 240), "42px（175% 实机）：", font=small, fill=fg)
    draw_old_folder(d, 520, 300, 42, fg)
    draw_folder(d, 590, 300, 42, fg)

    # 实际大小对比（24px）
    d.text((24, 240), "实际大小（24 / 20 / 16 px）：", font=small, fill=fg)
    x = 24
    for sz in (24, 20, 16):
        draw_old_folder(d, x + sz / 2, 290, sz, fg)
        draw_folder(d, x + sz / 2 + 46, 290, sz, fg)
        d.text((x, 316), "%dpx" % sz, font=small, fill=fg)
        x += 130

    d.text((24, 360), "左 = 改造前，右 = 新版", font=small, fill=fg)

    path = os.path.join(OUT, "folder-compare.png")
    img.save(path)
    print("saved:", path, img.size)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    render()
