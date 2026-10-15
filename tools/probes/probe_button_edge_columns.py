"""诊断：accent（蓝底）按钮右边到底哪一列不对——**逐列打印**。

用户："所有按钮最右侧边缘（特别是'打开'）仍有裁断感（比之前好一些，
但没完全解决）。"

上一版我把矩形内缩了半个笔宽。那对"有描边"的按钮是对的，
但 **accent 按钮的描边色 = 底色**（见 `_colours()`），
等价于"无描边实心块"。对实心块来说，内缩会让**最外一圈只有半像素覆盖**，
抗锯齿把它画成 50% 混合色——看上去就是"右边淡了一层"。

所以逐列打印左边缘与右边缘，比较它们的**覆盖梯度**：
对称 ⇒ 只是抗锯齿；不对称 ⇒ 真的被裁。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import theme as theme_mod
from file_tracker.widgets import RoundedButton, dpi_of

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

frame = wx.Frame(None, size=(900, 400))
frame.SetBackgroundColour(wx.Colour("#FFFFFF"))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()

theme = theme_mod.Theme.light("#2959CB")
card = wx.Colour(theme.card)
card_red = card.Red()
print(f"  底色 card = {theme.card}（红通道 {card_red}）")
print(f"  accent = {theme.accent}")

# **同时试几个 inset，找 GDI+ 真正把描边落在哪。**
# 直接调 `draw_to`，只在"填充—描边"两步之间插入不同 inset，
# 看哪一组能让左右两支竖线的**覆盖列**完全一致。
INSETS = (0, 1, 2)

for label, variant in (("accent（蓝底/'打开'）", "accent"),
                       ("secondary（'清空'）", "secondary")):
    button = RoundedButton(frame, "打开", theme, variant=variant)
    button.SetSize((189, 42))
    button._hovering = False
    button._pressed = False

    w, h = button.GetSize()
    bitmap = wx.Bitmap(w, h)
    dc = wx.MemoryDC(bitmap)
    dc.SetBackground(wx.Brush(card))
    dc.Clear()
    button.draw_to(dc, w, h)
    dc.SelectObject(wx.NullBitmap)
    image = bitmap.ConvertToImage()

    mid = h // 2
    print()
    print(f"=== {label}  {w}x{h}  半径={button._radius} ===")

    # **左右要取对称的列。**
    #
    # 踩过：右边从 `x = w-1` 开始数，左边从 `x = 0` 开始数——
    # 两边深度不同（右边多了半格），于是"第一次到纯色"的位置
    # 恒定差 1 列，**无论画得对不对都报"不对称"**。
    # 正确对应关系：左第 i 列 ↔ 右第 w-1-i 列，这样 offset 才可比。
    depths = range(0, 8)
    lefts = [image.GetRed(i, mid) for i in depths]
    rights = [image.GetRed(w - 1 - i, mid) for i in depths]
    print(f"  左  x=0..7          红通道 = {lefts}")
    print(f"  右  x=w-1..w-8      红通道 = {rights}")
    print(f"  左侧梯度 = {[lefts[i] - lefts[i + 1] for i in range(6)]}")
    print(f"  右侧梯度 = {[rights[i] - rights[i + 1] for i in range(6)]}")

    # 判据：**同一深度上的颜色应当相同**（左右镜像）
    diffs = [abs(a - b) for a, b in zip(lefts, rights)]
    print(f"  同一深度的左右差 = {diffs}"
          f"  {'✅ 镜像对称' if max(diffs) <= 1 else f'❌ 不对称（最大差 {max(diffs)}）'}")

    # 最外一圈的**覆盖比例**（1 = 满覆盖，0 = 完全没画到）
    solid = min(min(lefts), min(rights))
    span = max(card_red - solid, 1)
    print(f"  最外列覆盖率：左 = {(card_red - lefts[0]) / span:.2f}"
          f"   右 = {(card_red - rights[0]) / span:.2f}"
          f"   （1.00 = 满覆盖。0.00 表示最外列是背景色，")

    button.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

frame.Destroy()
