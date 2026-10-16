"""把主题按钮**渲染成位图**，看图标到底画没画出来。

## 为什么不再读代码猜

用户报"三个主题图标一个都没出来"。`foreground` / `width` / `height`
都在作用域里，逻辑看着也对 —— 那就**必须看渲染结果**，
而不是继续读代码推理。

这与我这一整轮反复得到的教训一致：**能回读实物就别推理**。

## 判据

把按钮画到 `wx.MemoryDC` 上，统计**非背景色**的像素数。
图标画出来了 ⇒ 会有几十到几百个前景像素；
一个都没画 ⇒ 只剩纯色底，前景像素数为 0。
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

with probe_temp("probe-theme-icon") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(3):
        seed.record_access(os.path.join(scratch, f"f{i}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(50):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    from file_tracker.widgets import SettingsDialog
    from file_tracker.lang import PREFERENCE_CHINESE
    dlg = SettingsDialog(frame, frame.theme, PREFERENCE_CHINESE)
    dlg.Show()
    for _ in range(30):
        wx.YieldIfNeeded()

    print(f"  主题按钮数 = {len(dlg._theme_buttons)}")
    print()
    for button in dlg._theme_buttons:
        painter = getattr(button, "icon_painter", None)
        size = button.GetSize()
        print(f"  ── 按钮 {button.label!r} ──")
        print(f"     icon_painter = {getattr(painter, '__name__', painter)}")
        print(f"     尺寸 = {size.width} x {size.height}")

        if size.width <= 0 or size.height <= 0:
            print("     ⚠️ 尺寸为 0，无法渲染")
            continue

        # 渲染到离屏位图
        bmp = wx.Bitmap(size.width, size.height)
        mem = wx.MemoryDC(bmp)
        mem.SetBackground(wx.Brush(button.GetParent().GetBackgroundColour()))
        mem.Clear()
        try:
            button.draw_to(mem, size.width, size.height)
        except Exception as error:
            print(f"     ❌ draw_to 抛异常：{type(error).__name__}: {error}")
            mem.SelectObject(wx.NullBitmap)
            continue
        mem.SelectObject(wx.NullBitmap)

        img = bmp.ConvertToImage()
        counts = {}
        for y in range(size.height):
            for x in range(size.width):
                c = (img.GetRed(x, y), img.GetGreen(x, y), img.GetBlue(x, y))
                counts[c] = counts.get(c, 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
        print(f"     出现最多的颜色：")
        for c, n in top:
            print(f"       #{c[0]:02X}{c[1]:02X}{c[2]:02X}  ×{n}")
        print(f"     **不同颜色总数 = {len(counts)}**"
              f"（1 = 纯色块，说明图标没画）")

    dlg.Destroy()
    frame.store.close()
    frame.Destroy()
