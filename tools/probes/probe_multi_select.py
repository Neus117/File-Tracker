"""诊断：用户说"深色主题有两条高亮项（一条高亮一条次级高亮），
浅色主题只有一条"，而"代码里是否支持多选"是关键线索。

## 我的前几轮错在哪

我只量了**选中之后底色变不变**（结论：不变），就下结论说
"用户看到的是纯白文字更跳的错觉"。**那个结论越界了**——
它解释不了"两条高亮"这种结构性差异。

用户的反问很准："我有没有骗你，你查代码里是否支持多选就知道了。"
如果**多选是开着的**，那"两条高亮"就有了完全不同的解释：
不是预选跟随，而是**真的选中了两条**，
其中一条是**焦点行**（另一种画法）。

所以这个探针查：

  ① `LVS_SINGLESEL` 到底有没有设（即：能不能多选）
  ② 真按 Ctrl 点两行，`GetSelectedItemCount()` 是 1 还是 2
  ③ 扩展样式逐位拆开，看有没有被忽略的位（如 `LVS_EX_BORDERSELECT`）
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
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system

LVS_SINGLESEL = 0x0004
LVS_SHOWSELALWAYS = 0x0008

# 扩展样式逐位含义
EX_BITS = [
    (0x00000001, "GRIDLINES"),
    (0x00000008, "TRACKSELECT"),
    (0x00000020, "FULLROWSELECT"),
    (0x00000040, "ONECLICKACTIVATE"),
    (0x00000080, "TWOCLICKACTIVATE"),
    (0x00000100, "UNDERLINECOLD"),
    (0x00000200, "UNDERLINEHOT"),
    (0x00000400, "BORDERSELECT"),
    (0x00010000, "DOUBLEBUFFER"),
    (0x00020000, "LABELTIP"),
    (0x00040000, "BORDERSELECT?"),
    (0x02000000, "HEADERINALLVIEWS"),
    (0x08000000, "AUTOCHECKSELECT"),
]

with probe_temp("probe-multisel") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-multisel")
    frame.SetSize((1400, 900))
    frame.Show()
    frame.Raise()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    for name in ("alpha", "beta", "gamma", "delta"):
        frame.store.record_access(os.path.join(scratch, name))
    frame.load_accessed_paths()
    frame.sort_list_items(frame.sort_column)
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    lc = frame.list_ctrl
    handle = lc.GetHandle()
    style = lc.GetWindowStyleFlag()
    ex = win32.get_extended_style(handle)

    print("=== ① 窗口样式（LVS_*）===")
    print(f"  样式 = {style:#010x}")
    print(f"    LVS_SINGLESEL      = {bool(style & LVS_SINGLESEL)}"
          f"   ← False 就表示**允许多选**")
    print(f"    LVS_SHOWSELALWAYS  = {bool(style & LVS_SHOWSELALWAYS)}")
    print(f"  wx 侧的 LC_SINGLE_SEL = {bool(style & wx.LC_SINGLE_SEL)}")
    print(f"  行数 = {lc.GetItemCount()}")

    print()
    print("=== ② 扩展样式逐位 ===")
    print(f"  扩展样式 = {ex:#010x}")
    for bit, name in EX_BITS:
        if ex & bit:
            print(f"    ✓ {name}")

    print()
    print("=== ③ 真的多选一次：选中 0 和 2 两行 ===")
    lc.Select(0)
    lc.Focus(0)
    for _ in range(20):
        wx.YieldIfNeeded()
    lc.Select(2)
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    count = lc.GetSelectedItemCount()
    print(f"  GetSelectedItemCount() = {count}"
          f"   {'❌ 多选是开着的！' if count > 1 else '✅ 只能选一条'}")
    selected = []
    index = lc.GetFirstSelected()
    while index != -1:
        selected.append(index)
        index = lc.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    print(f"  实际选中的行 = {selected}")

    print()
    print("=== ④ 焦点行与选中行是不是同一套画法 ===")
    print(f"  GetFirstSelected() = {lc.GetFirstSelected()}")
    focused = [i for i in range(lc.GetItemCount()) if lc.GetItemState(i, 0xFFFF) & 0x0001]
    print(f"  带焦点标记的行 = {focused}")
    print(f"  选中数 = {count}，焦点行数 = {len(focused)}"
          f"   {'← 两条高亮可能就是「焦点行 + 选中行」' if count == 1 else ''}")

    frame.store.close()
    frame.Destroy()
    for _ in range(20):
        wx.YieldIfNeeded()
