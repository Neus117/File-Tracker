"""临时诊断：GenericDirCtrl 的边框到底由哪个样式决定（每个变体独立一个窗口）。

之前所有对比都栽在同一件事上：**多个控件叠在同一个窗口里互相干扰**。
这次每个变体各自一个新 Frame，量 `GetWindowRect - GetClientRect` 的差值
（这个差值就是非客户区边框宽度，纯几何量，不依赖像素也不依赖绘制）。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def border_width(ctrl):
    """非客户区宽 = (窗口宽 - 客户区宽) / 2，高同理。"""
    r = RECT()
    user32.GetWindowRect(ctypes.c_void_p(ctrl.GetHandle()), ctypes.byref(r))
    ww, wh = r.right - r.left, r.bottom - r.top
    cw, ch = ctrl.GetClientSize()
    return (ww - cw) // 2, (wh - ch) // 2, ww, cw


variants = [
    ("DIRCTRL_MULTIPLE", wx.DIRCTRL_MULTIPLE),
    ("DIRCTRL_MULTIPLE|3D_INTERNAL", wx.DIRCTRL_MULTIPLE | wx.DIRCTRL_3D_INTERNAL),
    ("DIRCTRL_MULTIPLE|BORDER_NONE", wx.DIRCTRL_MULTIPLE | wx.BORDER_NONE),
    ("DIRCTRL_MULTIPLE|BORDER_SIMPLE", wx.DIRCTRL_MULTIPLE | wx.BORDER_SIMPLE),
    ("裸 wx.TreeCtrl", None),
]

print("=== 每个变体独立一个窗口，量非客户区边框 ===")
for label, style in variants:
    frame = wx.Frame(None, size=(420, 320))
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour("#242424"))
    if style is None:
        ctrl = wx.TreeCtrl(panel, style=wx.TR_HAS_BUTTONS | wx.BORDER_NONE)
    else:
        ctrl = wx.GenericDirCtrl(panel, -1, dir="D:\\", style=style)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(ctrl, 1, wx.EXPAND)
    panel.SetSizer(sizer)
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    hx, hy, ww, cw = border_width(ctrl)
    print(f"  {label:32}")
    print(f"    wx 样式 = {ctrl.GetWindowStyleFlag():#x}   窗口宽 {ww}  客户区宽 {cw}")
    print(f"    非客户区: 左右各 {hx}px, 上下各 {hy}px")
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

print()
print("=== 结论 ===")
print("  非客户区 > 0 的那些组合，就是深色下那一圈浅色边框的来源。")
print("  取 0 的那个组合就是修法。")
