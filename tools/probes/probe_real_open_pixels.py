"""验：**真的**打开资源管理器（不换成桩）之后，列表那条还是不是蓝的。

## 为什么这条到现在才试

前面所有探针都把 `open_folder` 换成桩（怕在用户桌面上弹窗口）。
但 **桩和真货差别很大**：真货会 `os.startfile(folder)`，
于是**资源管理器抢走前台激活**，我们的窗口变成 inactive。

而"无激活窗口的 ListView 怎么画选中项"是 Windows 说了算 ——
这一条恰好是"存了什么"（永远是 `#0078D7`）和"画成什么"会分岔的地方。

## 判据

* 打开前后 `frame.IsActive()` 各是多少
* 打开后选中那行**画出来**是什么色
* 如果 inactive 时确实变灰 ⇒ 用户的"浅灰"就是这个，与选择的颜色无关

⚠️ 本探针**会真的弹一个资源管理器窗口**（这是被测对象的一部分）。
"""
from __future__ import annotations

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
lang.apply(lang.PREFERENCE_CHINESE)


def pump(rounds: int = 30, pause: float = 0.006) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def park_mouse() -> None:
    try:
        ctypes.windll.user32.SetCursorPos(6, 902)
    except Exception:
        pass


def paint(ctrl) -> wx.Image:
    ctrl.Refresh()
    ctrl.Update()
    size = ctrl.GetClientSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour("#FF00FF")))
    memory.Clear()
    ctypes.windll.user32.PrintWindow(ctypes.c_void_p(ctrl.GetHandle()),
                                    ctypes.c_void_p(memory.GetHandle()),
                                    ctypes.c_uint(0))
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def face(image: wx.Image, ctrl, row: int) -> str:
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return "（不可见）"
    width = ctrl.GetClientSize().width
    counts: dict[str, int] = {}
    total = 0
    for dy in range(2, max(rect.height - 2, 3), 3):
        for dx in range(31, max(width - 30, 32), 2):
            x, y = dx, rect.y + dy
            colour = ("#%02X%02X%02X" % (image.GetRed(x, y), image.GetGreen(x, y),
                                         image.GetBlue(x, y))
                      if 0 <= x < image.GetWidth() and 0 <= y < image.GetHeight()
                      else "越界")
            counts[colour] = counts.get(colour, 0) + 1
            total += 1
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else ("??????", 0)
    return f"{best[0]}（{best[1] * 100 // max(total, 1)}%）"


with probe_temp("probe-real-open") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, f"m{i:03d}"))
    fresh = os.path.join(scratch, "m020-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    # **不换成桩**：这一轮要的就是"真开资源管理器"的副作用
    frame.Show()
    frame.Maximize()
    pump(60)
    park_mouse()

    ctrl = frame.list_ctrl
    theme = frame.theme
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}")

    try:
        mid = max(ctrl.GetItemCount() // 3, 1)
        ctrl.EnsureVisible(mid)
        ctrl.ScrollLines(mid - ctrl.GetTopItem())
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(mid, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        pump(15)
        park_mouse()
        print(f"\n【打开前】窗口激活 = {frame.IsActive()}   "
              f"焦点 = {type(wx.Window.FindFocus()).__name__}")

        tree = frame.dir_ctrl.GetTreeCtrl()
        tree.expand_to(fresh, select=True)
        frame._focus_pane = "tree"
        pump(12)

        print(f"\n【真的按「打开」：会启动资源管理器】…{fresh[-22:]}")
        frame.on_open(None)
        pump(60, pause=0.01)          # 等资源管理器真的起来
        park_mouse()

        print(f"  窗口激活 = {frame.IsActive()}   "
              f"焦点 = {type(wx.Window.FindFocus()).__name__ if wx.Window.FindFocus() else None}")

        # ① 窗口**还是 inactive** 时抓
        image = paint(ctrl)
        selected = ctrl.GetFirstSelected()
        print(f"\n  —— inactive 时 ——")
        print(f"  选中 = {selected}（…{frame.row_path(selected)[-22:]}）  "
              f"存值 = {ctrl.GetItemBackgroundColour(selected).GetAsString(wx.C2S_HTML_SYNTAX).upper() if selected >= 0 else '?'}")
        print(f"  **画出来** = {face(image, ctrl, selected) if selected >= 0 else '?'}")

        # ② 把窗口重新激活（模拟用户点回 File Tracker）再抓
        frame.Raise()
        frame.SetFocus()
        pump(30)
        park_mouse()
        image2 = paint(ctrl)
        print(f"\n  —— 重新激活（激活={frame.IsActive()}）后 ——")
        print(f"  **画出来** = {face(image2, ctrl, selected) if selected >= 0 else '?'}")

        shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
        os.makedirs(shots, exist_ok=True)
        image.SaveFile(os.path.join(shots, "real-open-inactive.png"),
                       wx.BITMAP_TYPE_PNG)
        image2.SaveFile(os.path.join(shots, "real-open-active.png"),
                        wx.BITMAP_TYPE_PNG)
        print(f"\n  截图：{shots}\\real-open-inactive.png / real-open-active.png")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
