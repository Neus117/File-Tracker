"""实测：**report 视图下怎么才能真的加高行距**。

## 背景（上一条探针的结论）

`LVM_SETITEMSPACING` 在 report 视图下是**空操作**（extra 0→40，行高恒为 39）。
行高**只由字号决定**：9pt→32、10pt→34、11pt→39、12pt→40。

所以"把行距加大"必须换一条路。

## 要试的三条路

| # | 做法 | 原理 |
|---|---|---|
| A | `LVM_SETIMAGELIST(LVSIL_SMALL)` 塞一张 1×H 的空图 | report 行高 = max(文字高, 小图标高) |
| B | `LVM_SETICONSPACING` | 那是 icon 视图的消息，预期无效（**对照组**） |
| C | 只改字号 | 已知有效，作为基准对照 |

**判据**：回读 `GetItemRect(0).height`，看它随 H 变不变。

⚠️ 必须确认**塞了图之后列表仍然正常**——文字还在、行数还对、没有多余留白。
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

with probe_temp("probe-row-height") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(12):
        seed.record_access(os.path.join(scratch, f"folder-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    ctrl = frame.list_ctrl
    print(f"  行数 = {ctrl.GetItemCount()}，当前字号 = {ctrl.GetFont().GetPointSize()}pt")
    print(f"  当前行高 = {ctrl.GetItemRect(0).height}，文字高 = {ctrl.GetTextExtent('Ag')[1]}")
    print()

    def row_h() -> int:
        for _ in range(10):
            wx.YieldIfNeeded()
        return ctrl.GetItemRect(0).height

    # ── 路 A：1×H 的空小图标表 ──
    print("  ── 路 A：wx.ImageList(1, H) 作为 SMALL 图列表 ──")
    print(f"  {'H':>5}{'行高':>8}{'文字还在吗':>12}")
    print("  " + "-" * 26)
    keep = []
    for H in (1, 8, 16, 24, 32, 40, 48):
        bmp = wx.Bitmap(1, H)
        il = wx.ImageList(1, H)
        il.Add(bmp, wx.Bitmap(1, H))
        ctrl.SetImageList(il, wx.IMAGE_LIST_SMALL)
        keep.append(il)                 # **必须留引用**，否则被回收
        h = row_h()
        text_ok = bool(ctrl.GetItemText(0, 0))
        print(f"  {H:>5}{h:>8}{str(text_ok):>12}")

    # ── 路 B：LVM_SETICONSPACING（预期无效，对照）──
    print()
    print("  ── 路 B：LVM_SETICONSPACING（对照组，预期无效）──")
    LVM_SETICONSPACING = 0x1039
    before = row_h()
    packed = ((60 & 0xFFFF) << 16) | (60 & 0xFFFF)
    ctypes.windll.user32.SendMessageW(ctypes.c_void_p(ctrl.GetHandle()),
                                      LVM_SETICONSPACING, 0, ctypes.c_void_p(packed))
    after = row_h()
    print(f"    改前 {before} → 改后 {after}"
          f"  {'（无效，符合预期）' if before == after else '（居然有效？）'}")

    print()
    print("  ── 结论 ──")
    print("  路 A 是否可行：看上面行高有没有随 H 变。")
    print("  若可行，'行距'就应当由**小图标高度**承担，")
    print("  而不是继续用那条在 report 视图下无效的 LVM_SETITEMSPACING。")

    frame.store.close()
    frame.Destroy()
