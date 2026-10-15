"""诊断：按钮的**描边有没有被裁断**，以及圆角半径是多少。

用户反馈两条：
  1. "所有按钮圆角过大，统一参数、适当缩小圆角"
  2. "按钮边缘线右侧有被裁断痕迹，roboc 里是没有这种情况的"

## ① 描边裁断的判据

`DrawRoundedRectangle(0, 0, w, h, r)` 画的是**路径**，1px 描边以路径为中心
向两侧各扩 0.5 —— 所以右边界线覆盖 `[w-0.5, w+0.5)`，
而客户区只有 `[0, w)`，**外半像素被裁掉**，线的颜色会变淡/断续。

判据：**四条边最外侧那一列/行的像素应当形状一致**。
被裁的那条边会出现"颜色比别的边淡"或"中间有缺口"。

用**位图**（不是窗口）——位图上的 `GetPixel` 在这个环境里是可靠的。

## ② 圆角半径

直接从 `METRICS.button_radius_for()` 读，并按 DPI 换算成物理像素，
和 Win11 原生的 4 物理像素作对比。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import theme as theme_mod
from file_tracker.theme import METRICS
from file_tracker.widgets import RoundedButton, dpi_of

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

print("=== ② 圆角半径 ===")
print(f"  radius_button = {METRICS.radius_button} 逻辑像素（绝对值，与高度无关）")
for logical_h in (24, 32):
    r_logical = METRICS.button_radius_for(logical_h)
    print(f"  高 {logical_h} 逻辑像素 → 半径 {r_logical} 逻辑"
          f"   比例 {r_logical / logical_h:.3f}")

frame = wx.Frame(None, size=(900, 400))
frame.SetBackgroundColour(wx.Colour("#FFFFFF"))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()

dpi = dpi_of(frame)
print(f"  当前 DPI = {dpi}（{dpi / 96 * 100:.0f}%）")
theme = theme_mod.Theme.light("#2959CB")

for label, variant in (("次要（有描边）", "secondary"), ("强调（无描边）", "accent")):
    button = RoundedButton(frame, "删除", theme, variant=variant)
    button.SetSize((150, 42))
    button.Layout()
    button._hovering = False
    button._pressed = False

    width, height = button.GetSize()
    bitmap = wx.Bitmap(width, height)
    dc = wx.MemoryDC(bitmap)
    dc.SetBackground(wx.Brush(wx.Colour("#FFFFFF")))
    dc.Clear()
    button.draw_to(dc, width, height)
    dc.SelectObject(wx.NullBitmap)

    image = bitmap.ConvertToImage()

    def col(x, ys):
        return [image.GetRed(x, y) for y in ys]

    def row(y, xs):
        return [image.GetRed(y=y and 0 or 0, x=0) if False else image.GetRed(x, y)
                for x in xs]

    mid_y = height // 2
    mid_x = width // 2
    print()
    print(f"=== ① {label}  {width}x{height}  "
          f"半径 = {button._radius} 物理像素 ===")
    edges = {
        "左边 x=0": col(0, [mid_y]),
        "左边 x=1": col(1, [mid_y]),
        "右边 x=w-1": col(width - 1, [mid_y]),
        "右边 x=w-2": col(width - 2, [mid_y]),
        "上边 y=0": row(0, [mid_x]),
        "上边 y=1": row(1, [mid_x]),
        "下边 y=h-1": row(height - 1, [mid_x]),
        "下边 y=h-2": row(height - 2, [mid_x]),
    }
    for name, values in edges.items():
        print(f"    {name:14} 红通道 = {values}")

    # 描边色（次级按钮）应当比底色深
    border_red = wx.Colour(theme.border).Red()
    card_red = wx.Colour(theme.card).Red()
    # **最外一圈是否四条边都有"描边色"**
    outer = {
        "左": image.GetRed(0, mid_y),
        "右": image.GetRed(width - 1, mid_y),
        "上": image.GetRed(mid_x, 0),
        "下": image.GetRed(mid_x, height - 1),
    }
    print(f"    最外圈 = {outer}   描边色红通道 = {border_red}"
          f"   底色红通道 = {card_red}")
    if variant == "secondary":
        present = [k for k, v in outer.items() if v < card_red - 4]
        missing = [k for k in outer if k not in present]
        print(f"    四条边都画到描边了吗 = "
              f"{'✅ 是' if not missing else f'❌ 缺 {missing}'}")
        print(f"      （缺的那条就是被裁掉的——它外侧那半像素落在位图外）")

    button.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

frame.Destroy()
