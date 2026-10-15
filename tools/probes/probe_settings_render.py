"""把我做的设置窗口离屏重画成图片，好核对"长得对不对"。

本环境的窗口抓图已被证明不可靠（`PrintWindow` 丢客户区内容、
`GetDC`+`GetPixel` 返回值自相矛盾），所以照 `probe_layout_render.py`
的办法：**把窗口按 Layout 的几何画到自建位图上**。

产出：`_shots/settings-{zh,en}.png`
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import lang, theme as theme_mod
from file_tracker.widgets import RoundedButton, SettingsDialog

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shots")
os.makedirs(OUT, exist_ok=True)

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def render(dialog, path: str) -> bool:
    width, height = dialog.GetClientSize()
    bitmap = wx.Bitmap(width, height)
    dc = wx.MemoryDC(bitmap)
    theme = dialog.theme

    dc.SetBackground(wx.Brush(wx.Colour(theme.background)))
    dc.Clear()

    # 语言行标签（原生 StaticText，这里按它的矩形画字）
    label = dialog._label
    dc.SetFont(label.GetFont())
    dc.SetTextForeground(wx.Colour(theme.text))
    dc.DrawText(label.GetLabel(), label.GetPosition().x, label.GetPosition().y)

    # 语言分段与底部按钮（都是自绘的 RoundedButton）
    #
    # **不要传 `parent_colour=`。** 踩过：`draw_to(parent_colour=...)` 内部会
    # `dc.Clear()`，而 `MemoryDC.Clear()` 抹的是**整张位图**，
    # 于是每画一个按钮就把前面画的全部擦掉——实测"只有最后一个可见"。
    # 圆角外那点父底色，改成只铺该按钮自己的矩形。
    for child in dialog.GetChildren():
        if not isinstance(child, RoundedButton):
            continue
        rect = child.GetRect()
        if rect.width <= 0 or rect.height <= 0:
            continue
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(theme.background)))
        dc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)
        dc.SetDeviceOrigin(rect.x, rect.y)
        child.draw_to(dc, rect.width, rect.height)
        dc.SetDeviceOrigin(0, 0)

    dc.SelectObject(wx.NullBitmap)

    # **自检：每种按钮的底色必须真的画出来了。**
    # 踩过：我一开始取"按钮正中心"当样本，读到的是**文字的白色抗锯齿**
    # （accent 中心读到 (255,206,220)），于是误判成"按钮没画"。
    # 所以取样点要避开文字——取靠左、靠上的位置。
    image = bitmap.ConvertToImage()
    for child in dialog.GetChildren():
        if not isinstance(child, RoundedButton):
            continue
        rect = child.GetRect()
        if rect.width <= 0:
            continue
        x, y = rect.x + 12, rect.y + 8
        got = (image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))
        want = wx.Colour(child._colours()[0])
        ok = all(abs(a - b) <= 6 for a, b in
                 zip(got, (want.Red(), want.Green(), want.Blue())))
        print(f"      {child.label!r} {child.variant}: "
              f"底色 = {got} 期望 {(want.Red(), want.Green(), want.Blue())} "
              f"{'✅' if ok else '❌'}")
    return bitmap.SaveFile(path, wx.BITMAP_TYPE_PNG)


frame = wx.Frame(None, size=(1200, 700))
frame.SetBackgroundColour(wx.Colour("#F3F4F6"))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()

for tag, pref in (("zh", lang.PREFERENCE_CHINESE),
                  ("en", lang.PREFERENCE_ENGLISH)):
    lang.apply(pref)
    dialog = SettingsDialog(frame, theme_mod.Theme.light("#2959CB"), pref)
    dialog.Show()
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    path = os.path.join(OUT, f"settings-{tag}.png")
    print(f"  {tag}: 客户区={dialog.GetClientSize()}  "
          f"标题={dialog.GetTitle()!r}  已存={render(dialog, path)}")
    dialog.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

lang.apply(None)
frame.Destroy()
print(f"  图片在 {os.path.normpath(OUT)}")
