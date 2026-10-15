"""诊断：列表行的"选中"与"鼠标悬停"到底是什么机制、什么颜色。

用户反馈："深色主题有鼠标预选跟随，浅色主题没有。也可能是浅色主题下的
鼠标预选跟随提示色被设置成了纯白。"

已知：本项目的列表是 `wx.ListCtrl`（原生 `SysListView32`），
**代码里没有任何 hover 实现**（只有自绘表头有 `_hover_column`）。
所以先查清楚：

  ① 原生 `SysListView32` 有没有"悬停高亮"这种东西
     （`LVS_EX_TRACKSELECT` / `LVIS_DROPHILITED` / `LVIS_HOT`）
  ② 选中行的颜色从哪来、能不能读出来
  ③ 我给每一项设的 `SetItemTextColour(list_text)` 会不会
     **覆盖掉选中行的高亮文字色**
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import win32
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32

# 系统高亮色
for name in ("SYS_COLOUR_HIGHLIGHT", "SYS_COLOUR_HIGHLIGHTTEXT",
             "SYS_COLOUR_HOTLIGHT", "SYS_COLOUR_BTNFACE", "SYS_COLOUR_WINDOW"):
    value = getattr(wx, name, None)
    if value is None:
        continue
    c = wx.SystemSettings.GetColour(value)
    print(f"  {name:26} = #{c.Red():02X}{c.Green():02X}{c.Blue():02X}")
print()

LVS_EX_TRACKSELECT = 0x00000008
LVS_EX_ONECLICKACTIVATE = 0x00000040
LVS_EX_TWOCLICKACTIVATE = 0x00000080
LVS_EX_HEADERINALLVIEWS = 0x02000000


def report(tag, dark):
    theme_mod.from_system = (
        (lambda: theme_mod.Theme.dark("#4CC2FF")) if dark
        else (lambda: theme_mod.Theme.light("#2959CB"))
    )
    app_mod.theme_from_system = theme_mod.from_system
    with probe_temp("probe-hot") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        frame = app_mod.FileTracker()
        frame.SetTitle(f"probe-hot-{tag}")
        frame.SetSize((1400, 900))
        frame.Show()
        for _ in range(60):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        # 造几行
        for name in ("alpha", "beta", "gamma"):
            frame.store.record_access(os.path.join(scratch, name))
        frame.pinned_paths = []
        frame.load_accessed_paths()
        frame.sort_list_items(frame.sort_column)
        for _ in range(30):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        lc = frame.list_ctrl
        handle = lc.GetHandle()
        ex = win32.get_extended_style(handle)
        print(f"=== {tag} ===")
        print(f"  扩展样式 = {ex:#010x}")
        for name, bit in (("TRACKSELECT", LVS_EX_TRACKSELECT),
                          ("ONECLICKACTIVATE", LVS_EX_ONECLICKACTIVATE),
                          ("TWOCLICKACTIVATE", LVS_EX_TWOCLICKACTIVATE),
                          ("FULLROWSELECT", win32.LVS_EX_FULLROWSELECT),
                          ("DOUBLEBUFFER", win32.LVS_EX_DOUBLEBUFFER)):
            print(f"    {name:18} = {bool(ex & bit)}")
        print(f"  行数 = {lc.GetItemCount()}")

        # 选中一行，读回它的属性
        lc.Select(0)
        for _ in range(20):
            wx.YieldIfNeeded()
        print(f"  选中行 = {lc.GetFirstSelected()}")
        print(f"  GetItemTextColour(0) = {lc.GetItemTextColour(0)}"
              f"   （我设的是 {frame.theme.list_text}）")
        print(f"  GetItemBackgroundColour(0) = {lc.GetItemBackgroundColour(0)}"
              f"   （我设的是 {frame.theme.pinned_row} 或 {frame.theme.card}）")
        print(f"  控件 GetTextColour     = {lc.GetTextColour()}")
        print(f"  控件 GetBackgroundColour = {lc.GetBackgroundColour()}")
        # 选中项的 state 位
        LVIS_SELECTED = 0x0002
        LVIS_FOCUSED = 0x0001
        LVIS_DROPHILITED = 0x0008
        state = lc.GetItemState(0, 0xFFFF)
        print(f"  第 0 行 state = {state:#06x}"
              f"  SELECTED={bool(state & LVIS_SELECTED)}"
              f"  FOCUSED={bool(state & LVIS_FOCUSED)}"
              f"  DROPHILITED={bool(state & LVIS_DROPHILITED)}")
        frame.store.close()
        frame.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()


report("light", False)
print()
report("dark", True)
