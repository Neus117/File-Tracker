"""量「记录窗格」与「导航窗格」的**行距比例**，好把前者对齐到后者。

## 为什么要按比例，不按像素

用户说："记录窗格的行距再增加一点点，视觉上的间隔比例就和导航窗格同步了
—— 导航窗格那个比例是最舒服的。"

**"比例"不是"像素"。** 两个控件的字号不同（列表 11pt、树是系统默认 9pt），
所以"都加 10px"在视觉上并不一致。要对齐的是：

```
行距比例 = 行高 / 文字高
```

## 判据

分别量两个控件的「行高」与「文字高」，算出各自比例，再反推列表该设多少。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

from file_tracker import win32


def text_height_of(win) -> int:
    """某个控件按**自己的字体**画一行文字有多高。"""
    dc = wx.ClientDC(win)
    dc.SetFont(win.GetFont())
    return dc.GetTextExtent("Ag路径")[1]


with probe_temp("probe-ratio") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(10):
        seed.record_access(os.path.join(scratch, f"folder-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    dpi = None
    from file_tracker.widgets import dpi_of
    dpi = dpi_of(frame)

    # ── 记录窗格 ──
    lst = frame.list_ctrl
    list_row = lst.GetItemRect(0).height
    list_text = text_height_of(lst)
    list_ratio = list_row / list_text
    list_pt = lst.GetFont().GetPointSize()

    # ── 导航窗格 ──
    tree_native = win32.find_child_window(frame.dir_ctrl.GetHandle(),
                                          "SysTreeView32")
    tree_row = win32.get_tree_item_height(tree_native)
    tree_text = text_height_of(frame.dir_ctrl)
    tree_ratio = tree_row / tree_text
    tree_pt = frame.dir_ctrl.GetFont().GetPointSize()

    print(f"  DPI = {dpi}")
    print()
    print(f"  {'':14}{'字号':>6}{'行高':>7}{'文字高':>8}{'比例(行/字)':>13}")
    print("  " + "-" * 50)
    print(f"  {'记录窗格':14}{list_pt:>5}pt{list_row:>7}{list_text:>8}"
          f"{list_ratio:>13.3f}")
    print(f"  {'导航窗格':14}{tree_pt:>5}pt{tree_row:>7}{tree_text:>8}"
          f"{tree_ratio:>13.3f}")

    print()
    print("  ── 比例是否一致 ──")
    print(f"    记录窗格 {list_ratio:.3f}｜导航窗格 {tree_ratio:.3f}"
          f"｜差 {abs(list_ratio - tree_ratio):.3f}")
    from file_tracker.theme import METRICS
    print(f"    目标比例（METRICS.row_ratio）= {METRICS.row_ratio}")
    print()
    print("    **现在两边都由 `文字高 × row_ratio` 现算**，不存在"
          "\"额外像素\"这种字段了：")
    print("    字号怎么变，比例都锁死——正是用户要的\"同一种呼吸感\"。")
    print("    （曾经用\"自然行高 + 固定像素\"实现，那个在缩字号时会漂，")
    print("      因为 TVM_SETITEMHEIGHT 收的是绝对高度、读不回自然高。）")

    frame.store.close()
    frame.Destroy()
