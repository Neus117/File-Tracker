"""临时诊断：改用 DataViewListCtrl 之后，四项原有行为能不能都保住。

需要确认：
  ① 按列居中（用户要的改动 ③）
  ② 顶置行的浅黄底（原实现用 ListCtrl.SetItemBackgroundColour）
  ③ 双击激活 / 右键菜单 / 列头点击排序
  ④ 列宽能动态调整（原 adjust_column_widths 用的 SetColumnWidth）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx
import wx.dataview as dv


class PinnedAwareListCtrl(dv.DataViewListCtrl):
    """用 OnGetItemAttr 给顶置行上底色。

    `DataViewListCtrl` 没有 `SetRowBackground`，但它的父类在渲染每一行时会
    调用 `OnGetItemAttr(row)`；返回一个 `DataViewItemAttr` 即可。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._row_colours = {}

    def set_row_colour(self, row, colour):
        self._row_colours[row] = colour
        self.Refresh()

    def clear_row_colours(self):
        self._row_colours.clear()

    def OnGetItemAttr(self, row):  # noqa: N802 - 跟随 wx 命名
        colour = self._row_colours.get(row)
        if colour is None:
            return None
        attr = dv.DataViewItemAttr()
        attr.SetBackgroundColour(colour)
        return attr


app = wx.App()
frame = wx.Frame(None, size=(800, 320))

lc = PinnedAwareListCtrl(frame, style=dv.DV_ROW_LINES | dv.DV_SINGLE)
lc.AppendTextColumn("访问的路径", width=240, mode=dv.DATAVIEW_CELL_INERT)
lc.AppendTextColumn("频次", width=110, align=wx.ALIGN_CENTER,
                    mode=dv.DATAVIEW_CELL_INERT)
lc.AppendTextColumn("最后访问时间", width=200, align=wx.ALIGN_CENTER,
                    mode=dv.DATAVIEW_CELL_INERT)

rows = [
    (r"C:\pinned\one", "42", "2026-10-15 12:00:00"),
    (r"C:\normal\two", "7", "2026-10-14 09:30:00"),
    (r"C:\normal\three", "3", "2026-10-13 08:00:00"),
]
for values in rows:
    lc.AppendItem(list(values))

lc.set_row_colour(0, wx.Colour(255, 255, 200))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()

print("① 列对齐：")
for index in range(lc.GetColumnCount()):
    column = lc.GetColumn(index)
    print(f"   列 {index} {column.GetTitle()!r:14} align={column.GetAlignment()} "
          f"({('居中' if column.GetAlignment() == wx.ALIGN_CENTER else '左对齐')})")

print()
print("② 顶置行底色：")
item_attr = lc.OnGetItemAttr(0)
print(f"   第 0 行 attr = {item_attr}")
if item_attr is not None:
    print(f"   背景色 = {item_attr.GetBackgroundColour()}")
print(f"   第 1 行 attr = {lc.OnGetItemAttr(1)}（普通行应为 None）")

print()
print("③ 取值与选中：")
print(f"   GetItemCount       = {lc.GetItemCount()}")
print(f"   GetTextValue(0,1)  = {lc.GetTextValue(0, 1)!r}")
lc.SelectRow(1)
print(f"   SelectRow(1) 之后 GetSelectedRow = {lc.GetSelectedRow()}")
print(f"   取该行路径 -> {lc.GetTextValue(lc.GetSelectedRow(), 0)!r}")

print()
print("④ 列宽动态调整：")
print(f"   调整前列 1 宽度 = {lc.GetColumn(1).GetWidth()}")
lc.GetColumn(1).SetWidth(150)
print(f"   调整后列 1 宽度 = {lc.GetColumn(1).GetWidth()}")

print()
print("⑤ 重排（排序后重建全部行）：")
lc.DeleteAllItems()
for values in reversed(rows):
    lc.AppendItem(list(values))
print(f"   重建后 GetItemCount = {lc.GetItemCount()}")
print(f"   第一行 = {lc.GetTextValue(0, 0)!r}")

print()
print("⑥ 清除全部：")
lc.DeleteAllItems()
print(f"   DeleteAllItems 之后 GetItemCount = {lc.GetItemCount()}")

print()
print("⑦ 中文字体下的表头渲染（用 wx 自带表头控件）：")
header = lc.GetHeaderCtrl()
print(f"   GetHeaderCtrl() = {header}")

frame.Destroy()
