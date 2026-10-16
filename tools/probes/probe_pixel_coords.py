"""验：探针的"屏幕采样"坐标与颜色到底对不对（**校准仪器**）。

## 为什么先验仪器

前一版探针量到第 0 行是 `#F9FAFB` —— 那个颜色**根本不在主题里**。
仪器给出"不可能的值"时，**先怀疑仪器**，不要急着解释数据。

## 已经查到的一个仪器缺陷：鼠标位置污染

`app.on_list_motion` 用 `wx.GetMousePosition()`（**全局真实鼠标**）
判断"鼠标在哪一行"，然后 `_apply_selection_highlight()` 会把
**那一行的底色按主题重设**。探针里每 `wx.YieldIfNeeded()` 一次，
Windows 就可能投递一次 `WM_MOUSEMOVE`，于是：

* 我把 row 3 涂成纯红做校准
* 一 Yield，悬停逻辑把它**改回主题白**

⇒ 量到的"白"是**我自己制造的事件**造成的，不是程序的行为。
本探针先用 `SetCursorPos` 把鼠标**移出列表**，再校准颜色。

## 校准判据

把 row 3 涂纯红、row 4 涂纯绿，然后采样：
**必须读到红/绿**，否则采样本身不可信，后面所有像素结论都不作数。
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
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

RED, GREEN = "#FF0000", "#00FF00"


def park_mouse() -> None:
    """把鼠标挪到屏幕左下角（远离窗口），免得悬停逻辑改我们的测试行。"""
    ctypes.windll.user32.SetCursorPos(6, 900)


def pump(rounds: int = 20) -> None:
    park_mouse()
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.005)
    park_mouse()


def image_of_screen() -> wx.Image:
    screen = wx.ScreenDC()
    width, height = screen.GetSize()
    bitmap = wx.Bitmap(width, height)
    memory = wx.MemoryDC(bitmap)
    memory.Blit(0, 0, width, height, screen, 0, 0)
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def pixel(image: wx.Image, x: int, y: int) -> str:
    if not (0 <= x < image.GetWidth() and 0 <= y < image.GetHeight()):
        return "越界"
    return "#%02X%02X%02X" % (image.GetRed(x, y), image.GetGreen(x, y),
                              image.GetBlue(x, y))


def sample_row(image: wx.Image, ctrl, row: int, offsets=(30, 200, 400, 700, 950)) -> str:
    rect = ctrl.GetItemRect(row)
    origin = ctrl.ClientToScreen(wx.Point(rect.x, rect.y))
    y = origin.y + rect.height // 2
    return "  ".join(f"{dx}:{pixel(image, origin.x + dx, y)}" for dx in offsets)


with probe_temp("probe-coords") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"dir-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    park_mouse()
    pump(60)

    ctrl = frame.list_ctrl
    print(f"屏幕 = {wx.ScreenDC().GetSize()}   窗口 {frame.GetScreenPosition()} "
          f"{frame.GetSize()}   列表 pos {ctrl.GetScreenPosition()} "
          f"size {ctrl.GetSize()}")
    for row in (0, 3, 4):
        rect = ctrl.GetItemRect(row)
        print(f"  row {row}: rect={rect} → 屏幕 "
              f"{ctrl.ClientToScreen(wx.Point(rect.x, rect.y))}")

    # ── 校准：必须读到红/绿 ──
    for row, colour in ((3, RED), (4, GREEN)):
        ctrl.SetItemBackgroundColour(row, wx.Colour(colour))
        ctrl.SetItemTextColour(row, wx.Colour("#FFFF00"))
    park_mouse()
    ctrl.Refresh()
    ctrl.Update()
    pump(10)
    image = image_of_screen()
    print("\n── 校准（鼠标已移出列表）──")
    print(f"  row 3 期望 {RED}：{sample_row(image, ctrl, 3)}")
    print(f"  row 4 期望 {GREEN}：{sample_row(image, ctrl, 4)}")

    # ── 再验一次"悬停逻辑会不会改掉我们的颜色" ──
    ctypes.windll.user32.SetCursorPos(*ctrl.ClientToScreen(wx.Point(300, 120)))
    pump(12)
    hovered = image_of_screen()
    print("\n── 把鼠标**移回列表**（第 3 行附近）──")
    print(f"  row 3 现在：{sample_row(hovered, ctrl, 3)}"
          f"   （theme.row_hover = {frame.theme.row_hover.upper()}）")
    print(f"  row 4 现在：{sample_row(hovered, ctrl, 4)}")
    print(f"  程序认为悬停行 = {getattr(frame, '_hover_row', None)}")

    park_mouse()
    frame.store.close()
    frame.Destroy()
    pump(5)
