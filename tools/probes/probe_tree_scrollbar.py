"""临时诊断：导航窗格的滚动条是不是系统按浅色画的。

wx 侧的底色全部正确（树 #242424、容器 #242424、无边框位），
所以剩下的白只可能来自**系统绘制的东西**。

`SysTreeView32` 的滚动条属于控件自身（不是独立子窗口），
由当前**主题**决定画成什么样。深色需要 `SetWindowTheme(hwnd, "DarkMode_Explorer")`。

这里用 `GetScrollBarInfo`（Win32，user32）问滚动条的实际矩形与状态——
不靠截图也能知道滚动条在不在、占了多宽。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from file_tracker import win32
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
theme_mod.from_system = lambda: theme_mod.Theme.dark("#4CC2FF")
app_mod.theme_from_system = theme_mod.from_system

user32 = ctypes.windll.user32

OBJID_HSCROLL = 0xFFFFFFFA
OBJID_VSCROLL = 0xFFFFFFFB
STATE_SYSTEM_INVISIBLE = 0x00008000
STATE_SYSTEM_OFFSCREEN = 0x00010000
STATE_SYSTEM_UNAVAILABLE = 0x00000001


class SCROLLBARINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcScrollBar", ctypes.c_long * 4),   # RECT
        ("dxyLineButton", ctypes.c_int),
        ("xyThumbTop", ctypes.c_int),
        ("xyThumbBottom", ctypes.c_int),
        ("reserved", ctypes.c_int),
        ("rgstate", ctypes.c_uint32 * 6),
    ]


def scrollbar(hwnd, objid, label):
    info = SCROLLBARINFO()
    info.cbSize = ctypes.sizeof(SCROLLBARINFO)
    ok = user32.GetScrollBarInfo(ctypes.c_void_p(hwnd), ctypes.c_long(objid),
                                 ctypes.byref(info))
    if not ok:
        print(f"    {label}: GetScrollBarInfo 失败")
        return
    left, top, right, bottom = info.rcScrollBar
    width, height = right - left, bottom - top
    state = info.rgstate[0]
    marks = []
    if state & STATE_SYSTEM_INVISIBLE:
        marks.append("不可见")
    if state & STATE_SYSTEM_OFFSCREEN:
        marks.append("在屏幕外")
    if state & STATE_SYSTEM_UNAVAILABLE:
        marks.append("不可用")
    print(f"    {label}: 矩形 {width}x{height} @({left},{top})  "
          f"状态 = {', '.join(marks) if marks else '可见'}  (raw={state:#x})")


with probe_temp("probe-sb") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-sb")
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    tree = frame.dir_ctrl.GetTreeCtrl()
    hwnd = tree.GetHandle()
    print("=== 树的滚动条 ===")
    scrollbar(hwnd, OBJID_VSCROLL, "垂直滚动条")
    scrollbar(hwnd, OBJID_HSCROLL, "水平滚动条")

    print()
    print("=== 滚动的样式位 ===")
    style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), -16)
    print(f"  style = {style:#010x}")
    print(f"    WS_VSCROLL = {bool(style & 0x00200000)}")
    print(f"    WS_HSCROLL = {bool(style & 0x00100000)}")

    print()
    print("=== 现在是否已套 DarkMode_Explorer ===")
    for name, h in (("树", hwnd), ("GenericDirCtrl", frame.dir_ctrl.GetHandle())):
        try:
            theme_handle = ctypes.windll.uxtheme.GetWindowTheme(ctypes.c_void_p(h))
            print(f"  {name:16} GetWindowTheme = {theme_handle}")
        except Exception as exc:
            print(f"  {name:16} 查询失败: {exc}")
    print("    （0 = 用的是系统默认主题；非 0 说明套过某个主题类）")

    print()
    print("=== 给树套上 DarkMode_Explorer ===")
    print(f"  返回 = {win32.set_window_theme(hwnd, 'DarkMode_Explorer')}")
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    try:
        theme_handle = ctypes.windll.uxtheme.GetWindowTheme(ctypes.c_void_p(hwnd))
        print(f"  之后 GetWindowTheme = {theme_handle}")
    except Exception as exc:
        print(f"  之后查询失败: {exc}")
    scrollbar(hwnd, OBJID_VSCROLL, "垂直滚动条")

    frame.store.close()
    frame.Destroy()
