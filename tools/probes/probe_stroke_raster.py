"""诊断：`wx.GraphicsContext.DrawRoundedRectangle` 的**描边到底落在哪几列**。

## 要回答的问题

用户两次反馈按钮右边有"裁断感"。已知：

  * `DrawRoundedRectangle(x, y, w, h, r)` 画的是**路径**，
    1px 描边以路径为中心向两侧各扩半个像素
  * 内缩半个笔宽 → 边界落在像素**中间**，抗锯齿在相邻两列分摊覆盖
  * 内缩整 1 像素 → 实测左边描边落在第 1 列（满覆盖），
    右边却落在第 w-1 列（偏移 0）——**左右不对称**

所以直接把一组 `(inset, 矩形宽)` 组合都画一遍，**量出描边落在哪**，
用数据定规则，而不是继续推。

## 判据

在一张纯白位图上画一个**只有描边**（`wx.TRANSPARENT_BRUSH`）的圆角矩形，
然后找出非白像素所在的最左/最右列。左右两支竖线的列号应当关于中心对称。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

W, H, R = 189, 42, 9
STROKE = "#000000"
print(f"目标位图 {W}x{H}，半径 {R}，描边 {STROKE}（1px）")
print()
print(f"{'inset':>7} {'矩形宽/高':>12}  左列  右列  偏移L  偏移R  {'结果'}")
print("-" * 62)

for inset in (0, 0.5, 1, 1.5, 2):
    for width_shrink in (0, 1, 2):
        rect_w = W - width_shrink
        rect_h = H - width_shrink
        bitmap = wx.Bitmap(W, H)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(wx.Colour("#FFFFFF")))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            print("  取不到 GraphicsContext")
            raise SystemExit(1)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(STROKE), 1))
        gc.DrawRoundedRectangle(inset, inset, rect_w, rect_h, R)
        dc.SelectObject(wx.NullBitmap)
        image = bitmap.ConvertToImage()

        mid = H // 2
        row = [image.GetRed(x, mid) for x in range(W)]
        # 非白（<250）的列
        inked = [x for x, v in enumerate(row) if v < 250]
        if not inked:
            print(f"{inset:>7} {rect_w:>5}x{rect_h:<6}  —      没有描边?!")
            continue
        # 左边第一段与右边最后一段
        left_cols = [x for x in inked if x < W // 2]
        right_cols = [x for x in inked if x >= W // 2]
        # **右半边可能一列都没有**（矩形右边界超出位图时，右支竖线被裁掉）
        # ——那正是"裁断"本身，要如实报出来，不能崩。
        if not left_cols or not right_cols:
            print(f"{inset:>7} {rect_w:>5}x{rect_h:<6}  "
                  f"  {'无' if not left_cols else left_cols[0]:>2}    "
                  f"{'无' if not right_cols else right_cols[-1]:>2}    "
                  f"      {'—' if not left_cols else left_cols[0]}"
                  f"       {'—' if not right_cols else W - 1 - right_cols[-1]}"
                  f"    ❌ 有一侧完全没有描边（被裁掉了）")
            continue
        lc = left_cols[0]
        rc = right_cols[-1]
        l_depth = lc
        r_depth = W - 1 - rc
        # 覆盖强度（0=白，255=纯黑）
        l_cov = 255 - row[lc]
        r_cov = 255 - row[rc]
        ok = (l_depth == r_depth) and abs(l_cov - r_cov) <= 8
        left_detail = ",".join(f"{x}:{255 - row[x]}" for x in left_cols[:3])
        right_detail = ",".join(f"{x}:{255 - row[x]}" for x in right_cols[-3:])
        print(f"{inset:>7} {rect_w:>5}x{rect_h:<6}  "
              f"  {lc}    {rc}    {l_depth}     {r_depth}    "
              f"{'✅ 对称' if ok else '❌'}   L[{left_detail}] R[{right_detail}]")

print()
print("列号 = 距该侧边缘的像素数（0 = 最外那一列）")
print("覆盖 = 该列的墨量（255 = 满覆盖 1 像素）")
