"""临时诊断：深色主题下目录树的白色框线是什么。

用户反馈："深色主题下左侧导航窗格依然有白色框线。"
`wx.GenericDirCtrl` 内部结构不止一个控件，白框可能来自其中任何一层。
这里把它的子窗口层次与各自底色全打印出来。
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
app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

theme_mod.from_system = lambda: theme_mod.Theme.dark("#4CC2FF")
app_mod.theme_from_system = theme_mod.from_system


def dump(hwnd, depth=0):
    out = []

    def cb(child, _):
        try:
            cls = win32gui.GetClassName(child)
        except Exception:
            return True
        try:
            visible = bool(user32.IsWindowVisible(ctypes.c_void_p(child)))
        except Exception:
            visible = None
        out.append((depth, child, cls, visible))
        dump_children(child, depth + 1)
        return True

    def dump_children(parent, level):
        try:
            win32gui.EnumChildWindows(parent, cb, None)
        except Exception:
            pass

    dump_children(hwnd, depth)
    return out


with probe_temp("probe-tree") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-tree")
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    dc = frame.dir_ctrl
    print(f"  GenericDirCtrl hwnd = {dc.GetHandle()}  类名 = "
          f"{win32gui.GetClassName(dc.GetHandle())}")
    print(f"    wx 底色     = {dc.GetBackgroundColour()}")
    print(f"    wx 前景色   = {dc.GetForegroundColour()}")
    tree = dc.GetTreeCtrl()
    print(f"  内部 TreeCtrl hwnd  = {tree.GetHandle()}  类名 = "
          f"{win32gui.GetClassName(tree.GetHandle())}")
    print(f"    wx 底色     = {tree.GetBackgroundColour()}")
    print(f"    主题 surface= {frame.theme.card}")

    print()
    print("  子窗口层次（会画白框的很可能是其中某个原生控件）:")
    for depth, child, cls, visible in dump(dc.GetHandle()):
        print(f"    {'  ' * depth}[{cls}] hwnd={child} 可见={visible}")

    print()
    print("  原生树控件的扩展样式（深色需要 DarkMode_Explorer）:")
    native_tree = win32.find_child_window(dc.GetHandle(), "SysTreeView32")
    print(f"    SysTreeView32 hwnd = {native_tree}")
    if native_tree:
        print(f"    set_window_theme(DarkMode_Explorer) = "
              f"{win32.set_window_theme(native_tree, 'DarkMode_Explorer')}")

    frame.store.close()
    frame.Destroy()
