"""把弹窗的**布局与配色**离屏重画成图片，用来核对"长得对不对"。

## 为什么要离屏重画

这个环境里的窗口抓图**已被证明不可靠**：
  * `PrintWindow` 抓本进程窗口能拿到标题栏，但**客户区正文丢了**
  * `GetDC(hwnd)` + `GetPixel` 返回自相矛盾的值
    （同一段文字在每个 y 都"出现"，按钮位置读到纯白）
  * `ScreenDC` 抓到的是别的窗口（本进程窗口没被合成）

所以把弹窗按 Layout 的几何**重画到一块自建位图**。
这验证的是"布局算得对不对、颜色对不对"——那才是我能修的。

## 一个踩过的坑

**别对同一块 `wx.Bitmap` 同时开两个 `wx.MemoryDC`。**
第一版就这么写了（先画正文、再画按钮各开一个），结果位图被第二个 DC
接管，正文被丢掉——看上去像"正文画不出来"，其实是自己把位图搞坏了。
正确做法：**一个 DC 画到底**；按钮要偏移，就用 `dc.DrawBitmap` 贴。

产出：`_shots/layout-{light,dark}.png`
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
from file_tracker.widgets import RoundedButton, ThemedDialog

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shots")
os.makedirs(OUT, exist_ok=True)

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def render(dialog, path: str) -> tuple[bool, int]:
    """一个 DC 画到底：背景 → 正文 → 各按钮（贴到各自位置）。"""
    width, height = dialog.GetClientSize()
    if width <= 0 or height <= 0:
        return False, 0
    bitmap = wx.Bitmap(width, height)
    dc = wx.MemoryDC(bitmap)
    theme = dialog.theme

    dc.SetBackground(wx.Brush(wx.Colour(theme.background)))
    dc.Clear()

    # 正文（弹窗自己的画法）
    dialog._draw_body(dc)

    # 按钮：**在同一个 DC 上**先铺父底色、再画圆角（与 `_on_paint` 一致）。
    #
    # 早先把按钮各自画到小块位图再贴回来，圆角外那四个角留的是位图底色（黑），
    # 图上看就像"按钮四角是黑的"——**那是探针没照着实现在画**。
    # `draw_to` 画在 (0,0)，所以用 `SetDeviceOrigin` 把它挪到各自位置。
    for child in dialog.GetChildren():
        if not isinstance(child, RoundedButton):
            continue
        rect = child.GetRect()
        if rect.width <= 0 or rect.height <= 0:
            continue
        dc.SetDeviceOrigin(rect.x, rect.y)
        child.draw_to(dc, rect.width, rect.height,
                      parent_colour=wx.Colour(theme.background))
        dc.SetDeviceOrigin(0, 0)

    # **先把位图从 DC 上摘下来，再读它。**
    #
    # 踩过：`SaveFile` 在位图仍被 `MemoryDC` 选中时调用，写出来的 PNG
    # 是坏的/空的（实测 2.5 KB、全无内容），而**同一个函数在深色下却正常**——
    # 因为深色的按钮面积大，恰好把内容留在了别处，掩盖了这个问题。
    dc.SelectObject(wx.NullBitmap)
    image = bitmap.ConvertToImage()
    left, top, right, _bottom = dialog._body_rect
    dark = sum(
        1
        for y in range(top, min(top + 32, height), 2)
        for x in range(left, min(right, width), 4)
        if image.GetRed(x, y) < 128
    )
    return bitmap.SaveFile(path, wx.BITMAP_TYPE_PNG), dark


for label, dark in (("light", False), ("dark", True)):
    theme_mod.from_system = (
        (lambda: theme_mod.Theme.dark("#4CC2FF")) if dark
        else (lambda: theme_mod.Theme.light("#2959CB"))
    )
    app_mod.theme_from_system = theme_mod.from_system
    with probe_temp("probe-render") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        frame = app_mod.FileTracker()
        frame.SetSize((1500, 900))
        frame.Show()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        dialog = ThemedDialog(frame, frame.theme, "⚠️ 确定要清空所有记录吗？",
                              title="确认清空")
        dialog.Show()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        path = os.path.join(OUT, f"layout-{label}.png")
        saved, dark_px = render(dialog, path)
        print(f"  {label}: 客户区={dialog.GetClientSize()} 已存={saved} "
              f"正文暗像素={dark_px} {'✅' if dark_px > 5 else '❌ 正文没画出来'}")
        dialog.Destroy()
        frame.store.close()
        frame.Destroy()
        for _ in range(10):
            wx.YieldIfNeeded()
