"""验：能不能把**窗口真实的画面**抓成一张图存下来。

## 为什么还要试

屏幕抓图已经证明不可信（把某行涂成 `#FF0000` 抓回来仍是白）。
但"看不见画面"是这一整轮最大的障碍 —— 用户看到的是**画出来的东西**，
而我只能读属性。所以值得再试一条路：

`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT=2)`
—— 它请求窗口把自己**完整渲染**一遍到给定 DC，是给
"被遮挡/合成窗口"截图用的接口。

## 判据

把两行涂成**不可能认错**的颜色（纯红 / 纯绿）再抓。
存成 PNG，**用眼睛看那张图** —— 不要只看汇总数字。
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

RED, GREEN, BLUE = "#FF0000", "#00FF00", "#0000FF"


def park_mouse() -> None:
    ctypes.windll.user32.SetCursorPos(6, 900)


def pump(rounds: int = 24) -> None:
    park_mouse()
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.005)


def print_window(target: wx.Window, flag: int) -> wx.Bitmap | None:
    size = target.GetSize()
    if size.width <= 0 or size.height <= 0:
        return None
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    # 先刷成显眼的洋红：如果 PrintWindow 什么都没画，我们一眼能看出来
    memory.SetBackground(wx.Brush(wx.Colour("#FF00FF")))
    memory.Clear()
    ok = ctypes.windll.user32.PrintWindow(
        ctypes.c_void_p(target.GetHandle()),
        ctypes.c_void_p(memory.GetHDC()), ctypes.c_uint(flag))
    memory.SelectObject(wx.NullBitmap)
    print(f"    PrintWindow(flag={flag}) 返回 {ok}  尺寸 {size}")
    return bitmap if ok else None


def report(bitmap: wx.Bitmap, label: str, points: list[tuple[str, wx.Point]]) -> None:
    image = bitmap.ConvertToImage()
    print(f"    {label}:")
    for name, point in points:
        if 0 <= point.x < image.GetWidth() and 0 <= point.y < image.GetHeight():
            colour = "#%02X%02X%02X" % (image.GetRed(point.x, point.y),
                                        image.GetGreen(point.x, point.y),
                                        image.GetBlue(point.x, point.y))
        else:
            colour = "越界"
        print(f"       {name:22} {point} → {colour}")


with probe_temp("probe-printwin") as scratch:
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
    pump(60)

    ctrl = frame.list_ctrl
    # **把控件属性的真相一起打出来**，免得又出现"存了却没画"的歧义
    for row, colour in ((3, RED), (4, GREEN), (6, BLUE)):
        ctrl.SetItemBackgroundColour(row, wx.Colour(colour))
        ctrl.SetItemTextColour(row, wx.Colour("#FFFF00"))
    print("  设置后回读（控件自报）：")
    for row in (3, 4, 6):
        print(f"    row {row} 底色 = "
              f"{ctrl.GetItemBackgroundColour(row).GetAsString(wx.C2S_HTML_SYNTAX).upper()}")
    ctrl.Refresh()
    ctrl.Update()
    pump(20)

    # 采样点用**控件客户区坐标**（与 PrintWindow 的坐标系一致）
    points = []
    for row, label in ((3, "row3 应为纯红"), (4, "row4 应为纯绿"),
                       (6, "row6 应为纯蓝")):
        rect = ctrl.GetItemRect(row)
        points.append((f"{label} (客户区)",
                       wx.Point(min(300, rect.width - 10),
                                rect.y + rect.height // 2)))

    print("\n  ── ① 抓列表控件本身（客户区坐标）──")
    for flag in (0, 2):
        bitmap = print_window(ctrl, flag)
        if bitmap is None:
            continue
        report(bitmap, f"PrintWindow flag={flag}", points)
        out = os.path.join(scratch, f"list-flag{flag}.png")
        bitmap.SaveFile(out, wx.BITMAP_TYPE_PNG)
        print(f"       已存 {out}")

    print("\n  ── ② 抓整个窗口（窗口客户区坐标）──")
    window_points = []
    for row, label in ((3, "row3 应为纯红"), (4, "row4 应为纯绿"),
                       (6, "row6 应为纯蓝")):
        rect = ctrl.GetItemRect(row)
        local = frame.ScreenToClient(ctrl.ClientToScreen(wx.Point(0, rect.y)))
        window_points.append((label, wx.Point(min(300, rect.width - 10),
                                              local.y + rect.height // 2)))
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
    os.makedirs(out_dir, exist_ok=True)
    for flag in (0, 2):
        bitmap = print_window(frame, flag)
        if bitmap is None:
            continue
        report(bitmap, f"PrintWindow flag={flag}", window_points)
        for folder, tag in ((scratch, "临时"), (out_dir, "留档")):
            out = os.path.join(folder, f"frame-flag{flag}.png")
            bitmap.SaveFile(out, wx.BITMAP_TYPE_PNG)
            print(f"       已存（{tag}） {out}")

    park_mouse()
    frame.store.close()
    frame.Destroy()
    pump(5)
