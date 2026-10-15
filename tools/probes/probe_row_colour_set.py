"""诊断：显式设置选中行的 item 底色/文字色，**读回来**是不是设的值。

## 为什么不用像素

`GetDC`+`GetPixel` 在这个环境里已被证明不可靠
（`probe_row_highlight.py` 里四个不同状态读回**一模一样**的图案，
连文字位置都一样——那是缓存，不是屏幕）。

所以改用**属性回读**：设完之后 `GetItemBackgroundColour` /
`GetItemTextColour` 会不会保持我设的值。这是控件自己的状态，
读得准；能确认"设置没被拒绝"。

**它不能证明"屏幕上真的变色了"**——那需要人眼。这里只排除
"设了没生效"这一种可能。
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
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system


def show(tag, colour):
    return None if colour is None else f"#{colour.Red():02X}{colour.Green():02X}{colour.Blue():02X}"


with probe_temp("probe-set") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-set")
    frame.SetSize((1400, 900))
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    for name in ("alpha", "beta", "gamma"):
        frame.store.record_access(os.path.join(scratch, name))
    # 让 beta 成为**顶置**行，检验"取消选中后能不能还原顶置黄"
    frame.pinned_paths = [os.path.join(scratch, "beta")]
    frame.load_accessed_paths()
    frame.sort_list_items(frame.sort_column)
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    lc = frame.list_ctrl
    print(f"  theme.card = {frame.theme.card}   theme.pinned_row = {frame.theme.pinned_row}")
    print(f"  顶置行 = {frame.pinned_paths}")
    for row in range(lc.GetItemCount()):
        print(f"    行{row} {lc.GetItemText(row)[-12:]:14}"
              f" 底色={show('', lc.GetItemBackgroundColour(row))}"
              f" 文字={show('', lc.GetItemTextColour(row))}")

    print()
    print("=== 把第 0 行设成系统高亮 + 白字，回读 ===")
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
    print(f"  系统高亮 = {show('', highlight)}")
    lc.SetItemBackgroundColour(0, highlight)
    lc.SetItemTextColour(0, wx.Colour("#FFFFFF"))
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  回读 底色={show('', lc.GetItemBackgroundColour(0))}"
          f"  文字={show('', lc.GetItemTextColour(0))}")
    ok_set = (lc.GetItemBackgroundColour(0).Red() == highlight.Red()
              and lc.GetItemTextColour(0).Red() == 255)
    print(f"  设置保持住了吗 = {ok_set}")

    print()
    print("=== 选不选中，这个颜色会不会被原生覆盖 ===")
    lc.Select(0)
    lc.Focus(0)
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    print(f"  选中后 回读 底色={show('', lc.GetItemBackgroundColour(0))}"
          f"  文字={show('', lc.GetItemTextColour(0))}")

    print()
    print("=== 还原（模拟取消选中） ===")
    lc.SetItemBackgroundColour(0, wx.Colour(frame.theme.card))
    lc.SetItemTextColour(0, wx.Colour(frame.theme.list_text))
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  还原后 底色={show('', lc.GetItemBackgroundColour(0))}"
          f"  文字={show('', lc.GetItemTextColour(0))}")

    frame.store.close()
    frame.Destroy()
