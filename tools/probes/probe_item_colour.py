"""临时诊断：wx.ListCtrl 到底能不能**按列**设文字颜色。

用户要求"路径列纯黑，其余列保持灰"。
`SetItemTextColour(index, colour)` 的语义要确认：它是整行还是某一列？
`wx.ItemAttr.SetTextColour` 只有 `(colour)` 一个参数，看起来是整行。

试三种做法，每种都把颜色**读回来**验证：
  ① 只调 SetItemTextColour（不分明细）
  ② 先设路径列、再设其它列（看后者是否覆盖前者）
  ③ 看有没有 OnGetItemColumnAttr / 虚拟列表的按列属性
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

COLUMNS = ("路径", "频次", "日期", "时间")
BLACK = wx.Colour("#000000")
GREY = wx.Colour("#6B7280")


def hexof(c):
    return "#{:02X}{:02X}{:02X}".format(c.Red(), c.Green(), c.Blue())


print("=== 建一个 4 列列表，造 2 行 ===")
frame = wx.Frame(None, size=(700, 300))
lc = wx.ListCtrl(frame, style=wx.LC_REPORT)
for i, name in enumerate(COLUMNS):
    lc.InsertColumn(i, name, width=150)
for r in range(2):
    lc.InsertItem(r, f"D:\\row{r}")
    for c in range(1, 4):
        lc.SetItem(r, c, f"v{r}{c}")
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()
    time.sleep(0.01)
print(f"  列数 = {lc.GetColumnCount()}  行数 = {lc.GetItemCount()}")

print()
print("=== ① 只设整行颜色，看读回来是什么 ===")
lc.SetItemTextColour(0, BLACK)
for _ in range(10):
    wx.YieldIfNeeded()
print(f"  设 #000000 后 GetItemTextColour(0) = "
      f"{hexof(lc.GetItemTextColour(0))}")

print()
print("=== ② 先黑后灰，看是否互相覆盖（= 是否整行）===")
lc.SetItemTextColour(1, BLACK)
lc.SetItemTextColour(1, GREY)
for _ in range(10):
    wx.YieldIfNeeded()
print(f"  先黑后灰 GetItemTextColour(1) = {hexof(lc.GetItemTextColour(1))}")
print("  若只读到一个值 → 该方法就是**整行**的，无法按列区分")

print()
print("=== ③ 有没有按列的属性接口 ===")
candidates = [n for n in dir(wx.ListCtrl) if 'Column' in n and 'Attr' in n]
print(f"  ListCtrl 里含 Column+Attr 的方法: {candidates}")
print(f"  OnGetItemColumnAttr 存在 = {hasattr(wx.ListCtrl, 'OnGetItemColumnAttr')}")
print(f"  ItemAttr.SetTextColour 参数个数 = "
      f"{wx.ItemAttr.SetTextColour.__doc__}")

print()
print("=== ④ 虚拟列表 OnGetItemAttr 能拿到列号吗 ===")
print(f"  OnGetItemAttr 签名: {wx.ListCtrl.OnGetItemAttr.__doc__.splitlines()[0]}")
print("  → 只有 item，**没有 column** —— 虚拟列表也一样是按行")

print()
print("=== 结论 ===")
print("  wx.ListCtrl 的文字颜色是**按行**的。")
print("  想要'路径列纯黑 + 其余列灰'，只能：")
print("    (a) 整行统一色（放弃列间层次）")
print("    (b) 走 LVM_SETITEMTEXT 原生自绘（重、风险高）")
print("  先用 (a)——用户明确说'灰色实在是不方便观察'，整行纯黑/纯白正合其意。")

frame.Destroy()
