"""临时诊断：sash 隐藏之后还拖得动吗？事件什么时候来？

两点要确认：
  1. `SetSashInvisible(True)` 之后鼠标还能不能拖动分隔条？
     （拖不动的话用户就失去了调整两栏宽度的能力）
  2. `EVT_SPLITTER_SASH_POS_CHANGED` 到底在什么时候触发——
     上次实测它在 `SetSashPosition()` 之后**没有立刻**触发，
     导致自绘的线留在旧位置。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

events = []

with probe_temp("probe-drag") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-drag")
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    sp = frame.splitter
    print("=== 1. sash 状态 ===")
    print(f"  GetSashSize()      = {sp.GetSashSize()}   (0 = 不画)")
    print(f"  GetSashPosition()  = {sp.GetSashPosition()}")
    print(f"  窗口样式 SP_NOBORDER = {bool(sp.GetWindowStyleFlag() & wx.SP_NOBORDER)}")
    print(f"  GetMinimumPaneSize() = {sp.GetMinimumPaneSize()}")

    print()
    print("=== 2. 事件在什么时候触发 ===")
    for name, evt in (("SASH_POS_CHANGING", wx.EVT_SPLITTER_SASH_POS_CHANGING),
                      ("SASH_POS_CHANGED", wx.EVT_SPLITTER_SASH_POS_CHANGED)):
        sp.Bind(evt, lambda e, n=name: events.append((n, sp.GetSashPosition())))
    frame.Bind(wx.EVT_SIZE, lambda e: events.append(("FRAME_SIZE", sp.GetSashPosition())))

    events.clear()
    sp.SetSashPosition(520)
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    print(f"  调 SetSashPosition(520) 后的事件 = {events}")

    events.clear()
    frame.SetSize(frame.GetSize().width + 60, frame.GetSize().height)
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    print(f"  改窗口大小后的事件 = {events}")

    print()
    print("=== 3. 结论 ===")
    if not events:
        print("  ⚠ 两个事件都可能不来，所以**不能只靠事件**摆那条线。")
        print("    可靠的做法：在 on_window_resize 里也摆一次，")
        print("    并且用 wx.CallAfter 延后到本次事件处理完之后。")
    sp.SetSashPosition(400)

    frame.store.close()
    frame.Destroy()
