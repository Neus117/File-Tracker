r"""画排序方式图标的**方案对比图**（给用户挑，不是最终资源）。

## 背景

设置界面的"排序方式"现在是三个文字按钮（`Path` / `Count` / `Time`，
两行排列）。用户希望改成**像主题那三个一样的图标小按钮**：

> "排序方式现在也按照界面主题的分类一样，使用 3 个小按钮，
>   里面用图形来代表路径、频次和时间。具体用什么样的图形来表示呢？
>   你先为我出一些方案并绘制出来，我看一下哪些比较好。"

## 为什么用 Pillow 而不是 wx 画

wx 需要真实窗口与消息循环，产出取决于屏幕 DPI；而"挑方案"要的是
**确定的、可重复的**图。Pillow 直接出像素，和最终用 `wx.DC` 实现时
的几何一一对应（都是 0..N 的浮点坐标）。

## 三套方案

| 方案 | 风格 | 路径 | 频次 | 时间 |
|---|---|---|---|---|
| **A** | 线条（stroke） | 折线 + 起终点 | 三根高低柱 | 圆环 + 指针 |
| **B** | 实心（filled） | 文件夹 | 阶梯方块 | 实心圆 + 镂空指针 |
| **C** | 符号（glyph） | `D:\` | `#` | `12` |

每套同时给**放大版（96px）**和**实际大小（20px）**——
后者才是它在按钮里真实的样子，很多方案放大好看、缩小就糊。
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "design")
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"      # 含中文
FONT_UI = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_MONO_BOLD = r"C:\Windows\Fonts\consolab.ttf"

#: 两套主题的 (背景, 图标色)
THEMES = {
    # (背景, 图标色, 选中底色, 选中图标色)
    "light": ("#FFFFFF", "#2B2B2B", "#0F6CBD", "#FFFFFF"),
    "dark": ("#242424", "#E8E8E8", "#4CC2FF", "#0B1A26"),
}


# ---------------------------------------------------------------- 图标画法
# 所有函数都在 (cx, cy) 为中心、边长 S 的方框里画。
# 用**归一化坐标**（0..1）再乘 S，这样 96px 和 20px 是同一份几何。

def _p(cx, cy, S, nx, ny):
    return (cx - S / 2 + nx * S, cy - S / 2 + ny * S)


def _w(S, k=0.09):
    """线宽：随尺寸线性缩放，但至少 1 像素。"""
    return max(int(round(S * k)), 1)


def icon_path_stroke(d, cx, cy, S, color, bg):
    w = _w(S)
    pts = [_p(cx, cy, S, 0.10, 0.82), _p(cx, cy, S, 0.34, 0.52),
           _p(cx, cy, S, 0.56, 0.66), _p(cx, cy, S, 0.90, 0.16)]
    d.line(pts, fill=color, width=w, joint="curve")
    # 起点实心点、终点空心圈 —— "从这里到哪里"
    r = S * 0.10
    x, y = _p(cx, cy, S, 0.10, 0.82)
    d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    x, y = _p(cx, cy, S, 0.90, 0.16)
    d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=w)


def icon_count_stroke(d, cx, cy, S, color, bg):
    w = _w(S)
    base = _p(cx, cy, S, 0, 0.84)[1]
    for i, h in enumerate((0.34, 0.66, 0.50)):
        x0 = _p(cx, cy, S, 0.12 + i * 0.28, 0)[0]
        x1 = x0 + S * 0.18
        top = base - h * S
        d.rectangle([x0, top, x1, base], outline=color, width=w)


def icon_time_stroke(d, cx, cy, S, color, bg):
    w = _w(S)
    r = S * 0.38
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
    d.line([(cx, cy), (cx, cy - r * 0.62)], fill=color, width=w)          # 时针
    d.line([(cx, cy), (cx + r * 0.52, cy + r * 0.36)], fill=color, width=w)  # 分针


def icon_path_filled(d, cx, cy, S, color, bg):
    # 文件夹：一个矩形 + 左上角的"舌片"
    x0, y0 = _p(cx, cy, S, 0.08, 0.30)
    x1, y1 = _p(cx, cy, S, 0.92, 0.86)
    d.rectangle([x0, y0, x1, y1], fill=color)
    d.rectangle([x0, _p(cx, cy, S, 0, 0.18)[1],
                 x0 + S * 0.42, y0 + S * 0.02], fill=color)


def icon_count_filled(d, cx, cy, S, color, bg):
    base = _p(cx, cy, S, 0, 0.86)[1]
    for i, h in enumerate((0.30, 0.62, 0.46)):
        x0 = _p(cx, cy, S, 0.10 + i * 0.28, 0)[0]
        x1 = x0 + S * 0.20
        d.rectangle([x0, base - h * S, x1, base], fill=color)


def icon_time_filled(d, cx, cy, S, color, bg):
    r = S * 0.40
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    w = max(int(round(S * 0.11)), 1)
    # 指针用背景色"挖"出来 —— 实心圆里才有对比
    d.line([(cx, cy), (cx, cy - r * 0.60)], fill=bg, width=w)
    d.line([(cx, cy), (cx + r * 0.50, cy + r * 0.34)], fill=bg, width=w)


def _glyph(d, text, cx, cy, S, color, font_path, scale=0.62):
    size = max(int(round(S * scale)), 6)
    font = ImageFont.truetype(font_path, size)
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text((cx - tw / 2 - box[0], cy - th / 2 - box[1]), text,
           font=font, fill=color)


def icon_path_glyph(d, cx, cy, S, color, bg):
    _glyph(d, "D:\\", cx, cy, S, color, FONT_MONO_BOLD, 0.66)


def icon_count_glyph(d, cx, cy, S, color, bg):
    _glyph(d, "#", cx, cy, S, color, FONT_MONO_BOLD, 0.82)


def icon_time_glyph(d, cx, cy, S, color, bg):
    _glyph(d, "12", cx, cy, S, color, FONT_MONO_BOLD, 0.72)


PLANS = [
    ("A  线条", (icon_path_stroke, icon_count_stroke, icon_time_stroke)),
    ("B  实心", (icon_path_filled, icon_count_filled, icon_time_filled)),
    ("C  符号", (icon_path_glyph, icon_count_glyph, icon_time_glyph)),
]
COLS = ("路径 Path", "频次 Count", "时间 Time")

BIG, SMALL = 96, 20
CELL = 150
LABEL_W = 130
PAD = 24
TITLE_H = 46


def render(theme_name: str, save_as: str) -> None:
    bg, fg, accent, on_accent = THEMES[theme_name]
    width = LABEL_W + PAD * 2 + CELL * 3
    height = TITLE_H + PAD + (CELL + 34) * len(PLANS) + PAD

    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    label_font = ImageFont.truetype(FONT_BOLD, 15)
    small_font = ImageFont.truetype(FONT_BOLD, 13)

    d.text((PAD, 12), "排序方式图标 · %s主题（大 = 放大预览，小 = 按钮里的实际大小 20px）"
           % ("浅色" if theme_name == "light" else "深色"),
           font=label_font, fill=fg)

    for row, (plan_name, icons) in enumerate(PLANS):
        y_top = TITLE_H + PAD + row * (CELL + 34)
        d.text((PAD, y_top + CELL // 2 - 10), plan_name, font=label_font, fill=fg)
        for col, fn in enumerate(icons):
            cx = LABEL_W + PAD + col * CELL + CELL // 2
            cy = y_top + CELL // 2
            # 放大版
            fn(d, cx, cy, BIG, fg, bg)
            # 实际大小（画在放大版右下角，标注出来）
            sx = cx + CELL // 2 - SMALL - 10
            sy = y_top + CELL - SMALL - 8
            d.rectangle([sx - 4, sy - 4, sx + SMALL + 4, sy + SMALL + 4],
                        outline=fg, width=1)
            fn(d, sx + SMALL // 2, sy + SMALL // 2, SMALL, fg, bg)
        # 列标题（只在第一行）
        if row == 0:
            for col, title in enumerate(COLS):
                cx = LABEL_W + PAD + col * CELL + CELL // 2
                box = d.textbbox((0, 0), title, font=small_font)
                d.text((cx - (box[2] - box[0]) / 2, y_top - 20),
                       title, font=small_font, fill=fg)

    # ---- 按钮中的真实效果（模拟 RoundedButton：圆角 + 图标居中）----
    bar_h = 168
    bar = Image.new("RGB", (width, bar_h), bg)
    bd = ImageDraw.Draw(bar)
    title_font = ImageFont.truetype(FONT_BOLD, 14)
    btn_w, btn_h, gap = 62, 42, 16
    for line, (label, selected) in enumerate((
            ("未选中", False), ("选中（按下后）", True))):
        y0 = 30 + line * 74
        bd.text((PAD, y0 + 12), label, font=title_font, fill=fg)
        bx = LABEL_W + PAD
        for plan_name, icons in PLANS:
            for fn in icons:
                bg_fill = accent if selected else None
                fg_icon = on_accent if selected else fg
                if selected:
                    bd.rounded_rectangle([bx, y0, bx + btn_w, y0 + btn_h],
                                         radius=8, fill=bg_fill)
                else:
                    bd.rounded_rectangle([bx, y0, bx + btn_w, y0 + btn_h],
                                         radius=8, outline=fg, width=1)
                fn(bd, bx + btn_w / 2, y0 + btn_h / 2, 24, fg_icon, bg_fill or bg)
                bx += btn_w + gap
            bx += 24
    out = Image.new("RGB", (width, height + bar_h), bg)
    out.paste(img, (0, 0))
    out.paste(bar, (0, height))
    out.save(save_as)
    print("saved:", save_as, out.size)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    render("light", os.path.join(OUT, "icons-light.png"))
    render("dark", os.path.join(OUT, "icons-dark.png"))
