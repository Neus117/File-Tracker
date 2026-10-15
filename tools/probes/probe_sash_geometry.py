"""临时诊断：sash 的几何与属性（不靠像素，像素抓不准）。

关键问题：`SetSashInvisible(True)` 之后
  * sash 还占不占 4 像素的位置？（决定那条线还在不在）
  * 分隔条还能不能拖动？
  * 那块区域露出的是谁的底色？（决定我们能不能用自己的颜色填它）
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def build(sash_invisible: bool, splitter_bg: str | None):
    frame = wx.Frame(None, size=(700, 340))
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour("#191919"))
    sp = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_NOBORDER)
    if splitter_bg:
        sp.SetBackgroundColour(wx.Colour(splitter_bg))
    left = wx.Panel(sp)
    right = wx.Panel(sp)
    left.SetBackgroundColour(wx.Colour("#191919"))
    right.SetBackgroundColour(wx.Colour("#242424"))
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(sp, 1, wx.EXPAND)
    panel.SetSizer(sizer)
    sp.SplitVertically(left, right, 300)
    if sash_invisible:
        sp.SetSashInvisible(True)
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)
    return frame, panel, sp, left, right


print("=== 三种做法的几何对比 ===")
for label, invisible, bg in (
    ("① 默认（sash 可见）", False, None),
    ("② SetSashInvisible(True)", True, None),
    ("③ SashInvisible + splitter 底色=描边色", True, "#3A3A3A"),
):
    frame, panel, sp, left, right = build(invisible, bg)
    print(f"  {label}")
    print(f"    GetSashSize()      = {sp.GetSashSize()}")
    print(f"    左窗右边界 x       = {left.GetPosition().x + left.GetSize().width}")
    print(f"    右窗左边界 x       = {right.GetPosition().x}")
    print(f"    两者之间的间隙     = "
          f"{right.GetPosition().x - (left.GetPosition().x + left.GetSize().width)}")
    print(f"    splitter 底色      = {sp.GetBackgroundColour()}")
    print(f"    SashPosition       = {sp.GetSashPosition()}")
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

print()
print("=== 读一眼 wx 的 SplitterWindow 源码，确认 sash 是怎么画的 ===")
import inspect
try:
    src = inspect.getsource(wx.SplitterWindow)
    has = [l.strip() for l in src.splitlines()
           if 'Sash' in l and ('def ' in l or 'SASH' in l)]
    for line in has[:12]:
        print(f"    {line}")
except Exception as exc:
    print(f"    取源码失败: {exc}")
