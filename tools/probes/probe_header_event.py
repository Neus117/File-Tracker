"""临时诊断：列头点击事件里到底有没有列号可用。

wxPython 4.2 没有公开 wx.DataViewEvent 这个类，所以上一轮
`_header_index` 取不到列号 —— 用户点击列头因此毫无反应。
这里把事件对象翻个底朝天，看有没有别的路。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx
import wx.dataview as dv

app = wx.App()
frame = wx.Frame(None, size=(700, 300), pos=(80, 80))
lc = dv.DataViewListCtrl(frame, style=dv.DV_ROW_LINES | dv.DV_SINGLE)
lc.AppendTextColumn("路径", width=240)
lc.AppendTextColumn("频次", width=90, align=wx.ALIGN_CENTER)
lc.AppendTextColumn("日期", width=120, align=wx.ALIGN_CENTER)
for i in range(4):
    lc.AppendItem([rf"C:\p{i}", str(i), "2026-10-15"])
frame.Show()
frame.Raise()
for _ in range(50):
    wx.YieldIfNeeded()

seen = []


def on_header(event):
    seen.append(event)
    print(f"\n  捕获列头点击: {type(event).__name__}")
    print(f"    GetEventType() = {event.GetEventType()}")
    print(f"    dir(event) 里含 olumn 的: "
          f"{[m for m in dir(event) if 'olumn' in m]}")
    print(f"    dir(event) 里含 Item/Model 的: "
          f"{[m for m in dir(event) if 'Item' in m or 'Model' in m]}")
    for method in ("GetColumn", "GetDataViewColumn", "GetItem", "GetModel",
                   "GetPosition", "GetDataViewItem"):
        if hasattr(event, method):
            try:
                print(f"    {method}() = {getattr(event, method)()}")
            except Exception as exc:  # noqa: BLE001
                print(f"    {method}() 抛 {exc!r}")
    event.Skip()


lc.Bind(dv.EVT_DATAVIEW_COLUMN_HEADER_CLICK, on_header)

# --- 真实鼠标点击表头 ---
pos = lc.GetScreenPosition()
size = lc.GetSize()
client = lc.GetClientSize()
nonclient = size.height - client.height
col0 = lc.GetColumn(0).GetWidth()
x = pos[0] + col0 + lc.GetColumn(1).GetWidth() // 2
y = pos[1] - max(nonclient, 20) // 2
print(f"列表尺寸={size} 客户区={client} 非客户区高={nonclient}")
print(f"点击坐标=({x},{y})  列表左上角={pos}")

user32 = ctypes.windll.user32
for attempt, offset in enumerate((0, -8, -14, -20)):
    user32.SetCursorPos(int(x), int(y + offset))
    for _ in range(6):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    for _ in range(4):
        wx.YieldIfNeeded()
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    for _ in range(20):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    print(f"  第 {attempt + 1} 次点击（y偏移 {offset}）后累计捕获 {len(seen)} 个事件")

print()
print(f"合计捕获 {len(seen)} 个列头点击事件")
print()
print("=== 结论怎么用 ===")
print("  若始终捕获不到 / 事件里没有列号 → 列头排序做不到，")
print("  应当**移除**这个绑定，而不是留一个点了没反应的死功能。")
print("  ('切换排序' 按钮本来就是可用的替代入口。)")

frame.Destroy()
