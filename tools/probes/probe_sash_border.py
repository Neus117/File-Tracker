"""临时诊断：深色主题下导航窗格的白框线与分界线到底是什么。

用户反馈："导航窗格的外框线、导航窗格与记录窗格之间的分界线在深色主题下
为什么仍旧保持白色？有办法更改吗？"

候选来源：
  A. `GenericDirCtrl` 的 `wx.DIRCTRL_3D_INTERNAL` 画的 3D 边框
  B. `GenericDirCtrl` 内部还有一个我们没设色的子面板
  C. `wx.SplitterWindow` 的 sash（分隔条）—— 它由 wx 自绘，尊重 SetBackgroundColour 吗？
  D. 列表/树的原生 WS_BORDER / WS_EX_CLIENTEDGE

这里把每一层的类名、底色、样式位全打出来，看谁还是浅色。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx
import win32gui

from file_tracker import win32
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

user32 = ctypes.windll.user32
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_BORDER = 0x00800000
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
theme_mod.from_system = lambda: theme_mod.Theme.dark("#4CC2FF")
app_mod.theme_from_system = theme_mod.from_system


def describe(hwnd, label):
    try:
        cls = win32gui.GetClassName(hwnd)
    except Exception:
        return
    st = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
    ex = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
    marks = []
    if st & WS_BORDER:
        marks.append("WS_BORDER")
    if ex & WS_EX_CLIENTEDGE:
        marks.append("WS_EX_CLIENTEDGE")
    if ex & WS_EX_STATICEDGE:
        marks.append("WS_EX_STATICEDGE")
    print(f"    {label:24} [{cls}]")
    print(f"      {'':22} style={st:#010x} ex={ex:#010x} "
          f"边框位: {', '.join(marks) if marks else '无'}")


with probe_temp("probe-sash") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-sash")
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    print("=== 主题色 ===")
    print(f"  窗口底 background = {frame.theme.background}")
    print(f"  卡片   card       = {frame.theme.card}")
    print(f"  描边   border     = {frame.theme.border}")

    print()
    print("=== 1. GenericDirCtrl 的边框样式 ===")
    dc = frame.dir_ctrl
    print(f"  wx 样式 = {dc.GetWindowStyleFlag():#x}")
    print(f"    DIRCTRL_3D_INTERNAL = "
          f"{bool(dc.GetWindowStyleFlag() & wx.DIRCTRL_3D_INTERNAL)}")
    print(f"    wx.BORDER_NONE      = "
          f"{bool(dc.GetWindowStyleFlag() & wx.BORDER_NONE)}")
    print(f"    边框值(BORDER_MASK) = "
          f"{dc.GetWindowStyleFlag() & wx.BORDER_MASK:#x}  "
          f"(wx.BORDER_NONE={wx.BORDER_NONE:#x})")

    print()
    print("=== 2. 子窗口层次 ===")
    describe(dc.GetHandle(), "GenericDirCtrl")
    tree = dc.GetTreeCtrl()
    describe(tree.GetHandle(), "  内层 TreeCtrl")

    print()
    print("=== 3. SplitterWindow 与 sash ===")
    # 找 splitter
    for child in frame.GetChildren():
        for sub in child.GetChildren():
            if isinstance(sub, wx.SplitterWindow):
                sp = sub
                print(f"  SplitterWindow 底色 = {sp.GetBackgroundColour()}")
                print(f"    style = {sp.GetWindowStyleFlag():#x}")
                print(f"    SP_NOBORDER = "
                      f"{bool(sp.GetWindowStyleFlag() & wx.SP_NOBORDER)}")
                print(f"    SashPosition = {sp.GetSashPosition()}  "
                      f" sash 宽 = {sp.GetSashSize()}")
                print(f"    SashInvisible = {sp.GetSashInvisible()}")
                print(f"    GetSashSize() 用的是 wx 的 SASH_WIDTH")
                describe(sp.GetHandle(), "SplitterWindow")
    print()
    print("  **sash 由 wx 自绘**：它取的是 `wx.SystemSettings.GetColour(")
    print("    (wx.SYS_COLOUR_BTNFACE)` 一类系统色，**不吃 SetBackgroundColour**。")
    print("    这就是分界线在深色下仍发白的原因。")

    print()
    print("=== 4. 列表与树有没有原生边框 ===")
    describe(frame.list_ctrl.GetHandle(), "ListCtrl")

    frame.store.close()
    frame.Destroy()
