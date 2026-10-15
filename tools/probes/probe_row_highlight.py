"""诊断：能不能用 item 颜色做出**稳得住**的行高亮（选中 = 系统高亮色）。

## 为什么要自己设

实测（`probe_row_selected_pixels.py`）：本项目的选中行**底色完全不变**
（浅色 `#FFFFFF`、深色 `#242424`，与未选中时一模一样）。
也就是说"选中了哪一行"完全靠文字本身，**没有任何高亮反馈**。

用户反馈"深色有鼠标预选跟随、浅色没有"——那是纯白/纯黑文字的观感差，
不是高亮色。

## 要验的是什么

`SetItemBackgroundColour` + `SetItemTextColour` 在**选中状态**下
到底谁说了算：

  A. 只靠原生 → 选中行由系统画（本机实测：**没变化**）
  B. 选中时显式把该行设成 `#0078D7` 底 + 白字 → 能不能压过原生？
  C. 取消选中后能不能还原回原来的 item 颜色？

只有 B/C 都成立，才可能用这条做"即时选中高亮"。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def pixels(hwnd, points):
    hdc = user32.GetDC(ctypes.c_void_p(hwnd))
    out = []
    try:
        for x, y in points:
            v = gdi32.GetPixel(ctypes.c_void_p(hdc), x, y)
            out.append(None if v == 0xFFFFFFFF
                       else (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
    finally:
        user32.ReleaseDC(ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc))
    return out


def hx(rgb):
    return "None" if rgb is None else "#{:02X}{:02X}{:02X}".format(*rgb)


def row_colours(lc, row):
    rect = lc.GetItemRect(row)
    y = rect.y + rect.height // 2
    # 取一行里靠右的空白处（路径文字之后），那里只有底色
    pts = [(x, y) for x in range(rect.x + 620, rect.x + 700, 8)]
    return [hx(p) for p in pixels(lc.GetHandle(), pts)]


for tag, dark in (("light", False), ("dark", True)):
    theme_mod.from_system = (
        (lambda: theme_mod.Theme.dark("#4CC2FF")) if dark
        else (lambda: theme_mod.Theme.light("#2959CB"))
    )
    app_mod.theme_from_system = theme_mod.from_system
    with probe_temp("probe-hl") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        frame = app_mod.FileTracker()
        frame.SetTitle(f"probe-hl-{tag}")
        frame.SetSize((1400, 900))
        frame.Show()
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
        print(f"=== {tag} ===")
        print(f"  A 未选中  行1 底色 = {row_colours(lc, 1)}")

        # 原生选中
        lc.Select(1)
        lc.Focus(1)
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        print(f"  B 原生选中 行1 底色 = {row_colours(lc, 1)}"
              f"   ← 与 A 相同就说明原生不给高亮")

        # 显式设成系统高亮色 + 白字
        highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        lc.SetItemBackgroundColour(1, highlight)
        lc.SetItemTextColour(1, wx.Colour("#FFFFFF"))
        lc.Refresh()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        print(f"  C 显式设高亮色 行1 底色 = {row_colours(lc, 1)}"
              f"   ← 期望 #{highlight.Red():02X}{highlight.Green():02X}{highlight.Blue():02X}")

        # 还原
        lc.SetItemBackgroundColour(1, wx.Colour(frame.theme.card))
        lc.SetItemTextColour(1, wx.Colour(frame.theme.list_text))
        lc.Refresh()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        print(f"  D 还原后   行1 底色 = {row_colours(lc, 1)}"
              f"   ← 期望 {frame.theme.card}")
        frame.store.close()
        frame.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()
    print()
