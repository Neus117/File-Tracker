"""临时诊断：用像素判定 LVM_SETCOLUMN 到底有没有改变绘制（修正版）。

上一版失败的原因：窗口没被置前，把别的程序截了进来，
于是"两次渲染不同"其实是别人在动。

这一版三件事：
① 窗口 `Raise()` + 居中，确保它在最前面；
② 先做**同格式连续两次**的对照，量出真实噪声基线；
③ 只比较"频次"列那一竖条的像素，不比较整块客户区。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx
import win32gui

from file_tracker import win32

LVM_SETCOLUMN = win32.LVM_FIRST + 24

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_render"))
os.makedirs(OUT, exist_ok=True)


def set_fmt(hwnd, index, fmt):
    col = win32.LVCOLUMN()
    col.mask = win32.LVCF_FMT
    col.fmt = fmt
    return ctypes.windll.user32.SendMessageW(
        ctypes.c_void_p(hwnd), ctypes.c_uint(LVM_SETCOLUMN),
        ctypes.c_void_p(index), ctypes.c_void_p(ctypes.addressof(col)),
    )


app = wx.App()
frame = wx.Frame(None, size=(720, 300), pos=(60, 60))
lc = wx.ListCtrl(frame, style=wx.LC_REPORT)
lc.InsertColumn(0, "路径", width=240)
lc.InsertColumn(1, "频次", width=110)
lc.InsertColumn(2, "最后访问时间", width=200)
for i in range(6):
    row = lc.InsertItem(lc.GetItemCount(), rf"C:\some\path\{i}")
    lc.SetItem(row, 1, str((i + 1) * 1111))
    lc.SetItem(row, 2, "2026-10-15 12:00:00")
frame.Show()
frame.Raise()
for _ in range(60):
    wx.YieldIfNeeded()

hwnd = lc.GetHandle()
print(f"hwnd={hwnd} 类名={win32gui.GetClassName(hwnd)}")
print(f"frame 位置={frame.GetPosition()} 尺寸={frame.GetSize()}")


def capture():
    """抓列表客户区，返回像素矩阵（r,g,b 的列表）。"""
    rect = lc.GetClientRect()
    width, height = rect.width, rect.height
    origin = lc.ClientToScreen((0, 0))
    screen_dc = wx.ScreenDC()
    bitmap = wx.Bitmap(width, height)
    memory_dc = wx.MemoryDC(bitmap)
    memory_dc.Blit(0, 0, width, height, screen_dc, origin[0], origin[1])
    memory_dc.SelectObject(wx.NullBitmap)
    image = bitmap.ConvertToImage()
    return [[image.GetRed(x, y) for x in range(width)] for y in range(height)], width, height


def column_band(cells, width, height, x0, x1, y0, y1):
    """只取指定矩形区域。"""
    return [
        [cells[y][x] for x in range(max(x0, 0), min(x1, width))]
        for y in range(max(y0, 0), min(y1, height))
    ]


def diff(a, b):
    return sum(
        1
        for row_a, row_b in zip(a, b)
        for va, vb in zip(row_a, row_b)
        if va != vb
    )


# 频次列的横向范围：列 0 宽 240，列 1 宽 110（客户区坐标）
col0_w = lc.GetColumnWidth(0)
col1_w = lc.GetColumnWidth(1)
band = (col0_w, col0_w + col1_w, 0, lc.GetClientRect().height)
print(f"频次列横向范围 x=[{band[0]}, {band[1]})")

# ---- 噪声基线：同格式连拍两次 ----
set_fmt(hwnd, 1, win32.LVCFMT_LEFT)
for _ in range(60):
    wx.YieldIfNeeded()
cells_a, width, height = capture()
band_a = column_band(cells_a, width, height, *band)

set_fmt(hwnd, 1, win32.LVCFMT_LEFT)
for _ in range(60):
    wx.YieldIfNeeded()
cells_b, width, height = capture()
band_b = column_band(cells_b, width, height, *band)

noise = diff(band_a, band_b)
print(f"噪声基线（同为 LEFT，连拍两次）: {noise} 个像素不同")

# ---- 真正的对照：LEFT vs CENTER ----
set_fmt(hwnd, 1, win32.LVCFMT_CENTER)
for _ in range(60):
    wx.YieldIfNeeded()
cells_c, width, height = capture()
band_c = column_band(cells_c, width, height, *band)

signal = diff(band_a, band_c)
print(f"LEFT vs CENTER 差异        : {signal} 个像素不同")
print()
if signal <= noise:
    print("结论：信号 <= 噪声 —— **fmt 对绘制没有可测的影响**，方案 A 不成立。")
else:
    print("结论：信号 > 噪声 —— fmt 确实改变了绘制。")

# 存图供人眼确认
for tag, cells in [("left", cells_a), ("center", cells_c)]:
    image = wx.Image(width, height)
    for y in range(height):
        for x in range(width):
            value = cells[y][x]
            image.SetRGB(x, y, value, value, value)
    image.SaveFile(os.path.join(OUT, f"band-{tag}.png"), wx.BITMAP_TYPE_PNG)
print(f"两张客户区图已存到 {OUT}")

frame.Destroy()
