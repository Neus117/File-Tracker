"""临时诊断：地址栏输入框点击后为什么没有光标闪烁。

用户反馈"顶栏没有任何交互，鼠标点击进去应该有闪烁的提示针"。
`PathBar` 是自绘 `BufferedPanel`，输入框是它的子控件。
怀疑是自绘面板把子控件的绘制盖掉了，或者焦点拿不到。
"""
import ctypes
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_temp import probe_temp

from file_tracker import app as app_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# 用 probe_temp：退出时一定删掉，不留垃圾（见 _probe_temp.py 的说明）
with probe_temp("probe-focus") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "probe.db")

    frame = app_mod.FileTracker()
    frame.SetTitle("probe-focus")
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()

    pb = frame.path_bar
    tc = pb.text_ctrl

    print("=== 控件基本情况 ===")
    print(f"  PathBar 尺寸 = {pb.GetSize()}  位置 = {pb.GetPosition()}")
    print(f"  输入框尺寸 = {tc.GetSize()}  位置 = {tc.GetPosition()}")
    print(f"  输入框可见 = {tc.IsShown()}  可用 = {tc.IsEnabled()}")
    print(f"  输入框只读 = {tc.IsEditable() is False}")
    print(f"  输入框样式 = {tc.GetWindowStyleFlag():#x}")
    print(f"  TE_PROCESS_ENTER = {bool(tc.GetWindowStyleFlag() & wx.TE_PROCESS_ENTER)}")
    print(f"  输入框在 PathBar 客户区内吗 = "
          f"{pb.GetClientRect().Contains(tc.GetRect())}")

    print()
    print("=== PathBar 自绘会不会盖住子控件 ===")
    print(f"  PathBar 背景样式 = {pb.GetBackgroundStyle()}  "
          f"(BG_STYLE_PAINT={wx.BG_STYLE_PAINT})")
    print(f"  PathBar 有 WS_CLIPCHILDREN 吗 = "
          f"{bool(ctypes.windll.user32.GetWindowLongW(ctypes.c_void_p(pb.GetHandle()), -16) & 0x02000000)}")

    print()
    print("=== 焦点能不能拿到 ===")
    print(f"  当前焦点 = {wx.Window.FindFocus()}")
    tc.SetFocus()
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  SetFocus 之后焦点 = {wx.Window.FindFocus()}  "
          f"是输入框吗 = {wx.Window.FindFocus() is tc}")
    print(f"  输入框 HasFocus = {tc.HasFocus()}")

    print()
    print("=== 用手工点击（模拟鼠标落在输入框上）===")
    point = wx.Point(tc.GetSize().width // 2, tc.GetSize().height // 2)
    for et in (wx.wxEVT_LEFT_DOWN, wx.wxEVT_LEFT_UP):
        evt = wx.MouseEvent(et)
        evt.SetPosition(point)
        evt.SetEventObject(tc)
        tc.GetEventHandler().ProcessEvent(evt)
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  点击后焦点 = {wx.Window.FindFocus() is tc}")

    print()
    print("=== 插入符（光标）状态 ===")
    print(f"  GetInsertionPoint = {tc.GetInsertionPoint()}")
    print(f"  文字长度 = {len(tc.GetValue())}")
    print("  注意：插入符只在控件有焦点且窗口处于**前台**时才闪烁。")
    print(f"  窗口是否前台 = {frame.IsActive()}")

    print()
    print("=== 自绘底色 vs 输入框底色（「看起来能不能点」的关键）===")
    print(f"  PathBar 底色   = {pb.GetBackgroundColour()}")
    print(f"  输入框底色     = {tc.GetBackgroundColour()}")
    print(f"  两者相同吗     = {pb.GetBackgroundColour() == tc.GetBackgroundColour()}"
          "（相同的话看起来就像静态标签）")

    frame.store.close()
    frame.Destroy()
