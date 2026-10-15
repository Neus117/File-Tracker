"""临时诊断：wx 在这台机器（175% 缩放）上报告的坐标到底是什么单位。"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception as exc:  # noqa: BLE001
    print("SetProcessDpiAwareness 失败:", exc)

frame = wx.Frame(None, title="probe-dpi")
frame.SetSize(1472, 828)

print(f"Display.GetClientArea()      = {wx.Display(0).GetClientArea()}")
print(f"Display.GetGeometry()        = {wx.Display(0).GetGeometry()}")
print(f"frame.GetSize()              = {frame.GetSize()}")
print(f"frame.GetClientSize()        = {frame.GetClientSize()}")
print(f"frame.FromDIP(24)            = {frame.FromDIP(24)}")
print(f"frame.ToDIP(24)              = {frame.ToDIP(24)}")
print(f"wx.SystemSettings DPI        = {frame.GetDPI()}")
print(f"GetContentScaleFactor()      = {frame.GetContentScaleFactor()}")
print(f"SystemSettings.GetFont(pt)   = {wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()}")

print()
print("--- 请求 1472x828，实际拿到的是多少 ---")
frame.SetSize((1472, 828))
print(f"  GetSize       = {frame.GetSize()}")
print(f"  GetClientSize = {frame.GetClientSize()}")
print(f"  屏幕工作区     = {wx.Display(0).GetClientArea().width}x{wx.Display(0).GetClientArea().height}")
print(f"  放得下吗       = {1472 <= wx.Display(0).GetClientArea().width}")

frame.Destroy()
