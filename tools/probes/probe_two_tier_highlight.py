"""诊断：**两档高亮**（预选 / 选中）是不是都真的画上了，两个主题各查一遍。

## 判据用属性回读，不用像素

像素取样在这个环境里已被证明不可靠。而
`GetItemBackgroundColour(row)` 是控件自己的状态，读得准
（`probe_row_colour_set.py` 已确认它反映真实设置）。

## 怎么在不移动真实鼠标的情况下验证悬停

悬停靠 `EVT_MOTION`，模拟鼠标不可靠。所以**直接调
`_set_hover_row(row)`**——那是 `on_list_motion` 唯一的出口，
行号算得对不对由 `HitTest` 负责，这里验的是"拿到行号之后画得对不对"。
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


def hexof(colour):
    return f"#{colour.Red():02X}{colour.Green():02X}{colour.Blue():02X}"


for tag, dark in (("light", False), ("dark", True)):
    theme_mod.from_system = (
        (lambda: theme_mod.Theme.dark("#4CC2FF")) if dark
        else (lambda: theme_mod.Theme.light("#2959CB"))
    )
    app_mod.theme_from_system = theme_mod.from_system
    with probe_temp("probe-2tier") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        frame = app_mod.FileTracker()
        frame.SetTitle(f"probe-2tier-{tag}")
        frame.SetSize((1400, 900))
        frame.Show()
        for _ in range(60):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        for name in ("alpha", "beta", "gamma", "delta"):
            frame.store.record_access(os.path.join(scratch, name))
        frame.pinned_paths = []
        frame.load_accessed_paths()
        frame.sort_list_items(frame.sort_column)
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        lc = frame.list_ctrl
        print(f"=== {tag} ===")
        print(f"  theme.row_hover = {frame.theme.row_hover}"
              f"   theme.card = {frame.theme.card}")
        system_hl = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        print(f"  SYS_COLOUR_HIGHLIGHT = {hexof(system_hl)}")

        def snap(label):
            rows = [hexof(lc.GetItemBackgroundColour(i))
                    for i in range(lc.GetItemCount())]
            print(f"    {label:26} 行底色 = {rows}")

        snap("初始")

        # ① 预选：悬停第 1 行，**不选中**
        frame._set_hover_row(1)
        for _ in range(20):
            wx.YieldIfNeeded()
        snap("悬停行1（预选）")
        hover_ok = hexof(lc.GetItemBackgroundColour(1)).upper() \
            == frame.theme.row_hover.upper()
        print(f"    行1 == row_hover ? {hover_ok}"
              f"   选中数 = {lc.GetSelectedItemCount()}（应为 0）")

        # ② 选中 + 预选同时存在（用户说的"两条高亮"）
        lc.Select(3)
        for _ in range(30):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        frame._apply_selection_highlight()
        for _ in range(20):
            wx.YieldIfNeeded()
        snap("悬停行1 + 选中行3")
        both_ok = (hexof(lc.GetItemBackgroundColour(1)).upper()
                   == frame.theme.row_hover.upper()
                   and hexof(lc.GetItemBackgroundColour(3)).upper()
                   == hexof(system_hl).upper())
        print(f"    两档同时成立 ? {both_ok}")

        # ③ 选中优先：悬停到已选中的那一行，应当仍是选中色
        frame._set_hover_row(3)
        for _ in range(20):
            wx.YieldIfNeeded()
        snap("悬停行3（=选中行）")
        precedence_ok = hexof(lc.GetItemBackgroundColour(3)).upper() \
            == hexof(system_hl).upper()
        print(f"    选中优先于预选 ? {precedence_ok}")

        # ④ 鼠标离开：预选收掉，只剩选中
        frame._set_hover_row(-1)
        for _ in range(20):
            wx.YieldIfNeeded()
        snap("鼠标离开")
        leave_ok = hexof(lc.GetItemBackgroundColour(1)).upper() \
            == frame.theme.card.upper()
        print(f"    行1 还原成 card ? {leave_ok}")

        print(f"  ---- 小结 ----")
        print(f"    预选色生效      : {hover_ok}")
        print(f"    两档同时可见    : {both_ok}")
        print(f"    选中优先        : {precedence_ok}")
        print(f"    离开后还原      : {leave_ok}")

        frame.store.close()
        frame.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()
    print()
