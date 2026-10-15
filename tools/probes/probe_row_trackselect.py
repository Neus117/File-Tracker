"""诊断：`LVS_EX_TRACKSELECT` 能不能给列表行做出"鼠标悬停跟随"。

## 背景

用户反馈："深色主题有鼠标预选跟随，浅色主题没有。"
但代码里**没有任何 hover 实现**，而且实测（`probe_row_selected_pixels.py`）
**选中行的底色根本没变**——所以那多半是"纯黑/纯白文字本身更跳"的观感差。

不管怎样，Explorer 的行悬停是真实存在的（`LVS_EX_TRACKSELECT` +
`LVIS_DROPHILITED`）。这个探针查：

  ① 打开 `LVS_EX_TRACKSELECT` 能不能成（回读扩展样式）
  ② 鼠标移上去之后，那一行有没有拿到 `LVIS_DROPHILITED`
  ③ 有没有副作用（`LVS_EX_TRACKSELECT` 通常要配 `LVS_EX_ONECLICKACTIVATE`，
     那会改变单击行为——这是我最担心的）

## 判据用 **item state**，不用像素

这个环境的像素取样已被证明不可靠（同一个 DC 每一步读回一模一样的图案）。
`GetItemState()` 是控件自己的属性，读得准。
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

LVS_EX_TRACKSELECT = 0x00000008
LVS_EX_ONECLICKACTIVATE = 0x00000040
LVIS_DROPHILITED = 0x0008
LVIS_SELECTED = 0x0002

theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system

with probe_temp("probe-track") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-track")
    frame.SetSize((1400, 900))
    frame.Show()
    frame.Raise()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    for name in ("alpha", "beta", "gamma"):
        frame.store.record_access(os.path.join(scratch, name))
    frame.pinned_paths = []
    frame.load_accessed_paths()
    frame.sort_list_items(frame.sort_column)
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    lc = frame.list_ctrl
    handle = lc.GetHandle()

    print("=== ① 打开 LVS_EX_TRACKSELECT ===")
    before = win32.get_extended_style(handle)
    print(f"  之前 = {before:#010x}  TRACKSELECT={bool(before & LVS_EX_TRACKSELECT)}")
    ok = win32.set_extended_style(handle, LVS_EX_TRACKSELECT)
    after = win32.get_extended_style(handle)
    print(f"  之后 = {after:#010x}  TRACKSELECT={bool(after & LVS_EX_TRACKSELECT)}"
          f"  调用返回={ok}")
    print(f"  ONECLICKACTIVATE 被顺带打开了吗 = "
          f"{bool(after & LVS_EX_ONECLICKACTIVATE)}  ← 不希望它变 True")
    print(f"  FULLROWSELECT 还在吗 = {bool(after & win32.LVS_EX_FULLROWSELECT)}")

    print()
    print("=== ② 把鼠标移到第 1 行上，看 state ===")
    rect = lc.GetItemRect(1)
    inside = wx.Point(rect.x + 40, rect.y + rect.height // 2)
    screen = lc.ClientToScreen(inside)
    print(f"  目标客户区坐标 = {inside}  屏幕坐标 = {screen}")
    # 用 SendMessage 直接投递鼠标移动（不需要真的移动系统指针）
    WM_MOUSEMOVE = 0x0200
    lparam = (inside.y << 16) | (inside.x & 0xFFFF)
    for _ in range(5):
        ctypes.windll.user32.SendMessageW(
            ctypes.c_void_p(handle), ctypes.c_uint(WM_MOUSEMOVE),
            ctypes.c_void_p(0), ctypes.c_void_p(lparam))
        wx.YieldIfNeeded()
        time.sleep(0.05)
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    state = lc.GetItemState(1, 0xFFFF)
    print(f"  第 1 行 state = {state:#06x}  "
          f"DROPHILITED={bool(state & LVIS_DROPHILITED)}  "
          f"SELECTED={bool(state & LVIS_SELECTED)}")

    print()
    print("=== ③ 副作用检查：单击行为有没有变 ===")
    print("  打开 TRACKSELECT 后，`LVS_EX_ONECLICKACTIVATE` 若也为真，")
    print("  单击就会触发展开/激活——那会改掉用户习惯的单击选中。")
    print(f"  实测 ONECLICKACTIVATE = {bool(after & LVS_EX_ONECLICKACTIVATE)}")

    print()
    print("=== 结论 ===")
    if (after & LVS_EX_TRACKSELECT) and not (after & LVS_EX_ONECLICKACTIVATE):
        print("  TRACKSELECT 单独打开是安全的（没有顺带打开 ONECLICKACTIVATE）")
    else:
        print("  注意：要么没打开成功，要么顺带改了单击行为")

    frame.store.close()
    frame.Destroy()
