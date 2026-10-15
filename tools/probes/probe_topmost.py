"""临时诊断：wx.Frame.SetWindowStyle 到底有没有把 STAY_ON_TOP 应用到窗口上。

上一轮发现：处理器被调用了，但窗口的 WS_EX_TOPMOST 位一直是 0。
怀疑 `SetWindowStyle` 只改了 wx 自己的属性，没有推给 Windows。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

user32 = ctypes.windll.user32

app = wx.App()


def topmost(hwnd) -> bool:
    ex = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
    return bool(ex & WS_EX_TOPMOST)


frame = wx.Frame(None, title="probe-topmost", size=(300, 200))
frame.Show()
for _ in range(20):
    wx.YieldIfNeeded()
hwnd = frame.GetHandle()

print("=== 方式 A：wx.Frame.SetWindowStyle（当前实现）===")
print(f"  初始 WS_EX_TOPMOST = {topmost(hwnd)}")
frame.SetWindowStyle(frame.GetWindowStyle() | wx.STAY_ON_TOP)
for _ in range(20):
    wx.YieldIfNeeded()
print(f"  SetWindowStyle 之后：")
print(f"    wx 报的 STAY_ON_TOP = {bool(frame.GetWindowStyle() & wx.STAY_ON_TOP)}")
print(f"    实际 WS_EX_TOPMOST  = {topmost(hwnd)}   ← 若为 False 就是没生效")

print()
print("=== 方式 B：就在 SetWindowStyle 之后补一次 Show() ===")
frame.Hide()
frame.Show()
for _ in range(20):
    wx.YieldIfNeeded()
print(f"    Hide+Show 之后 WS_EX_TOPMOST = {topmost(hwnd)}")

print()
print("=== 方式 C：SetWindowStyle 之后发 SetWindowPos 重新应用扩展样式 ===")
style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
# 用 SetWindowPos 把扩展样式重新推一次
user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST if topmost(hwnd) else HWND_NOTOPMOST),
                   0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
for _ in range(10):
    wx.YieldIfNeeded()
print(f"    SetWindowPos 之后 WS_EX_TOPMOST = {topmost(hwnd)}")

print()
print("=== 方式 D：绕开 wx，直接用 SetWindowPos 置顶/取消 ===")
user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST),
                   0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
for _ in range(10):
    wx.YieldIfNeeded()
print(f"    HWND_TOPMOST    → WS_EX_TOPMOST = {topmost(hwnd)}")
user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_NOTOPMOST),
                   0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
for _ in range(10):
    wx.YieldIfNeeded()
print(f"    HWND_NOTOPMOST  → WS_EX_TOPMOST = {topmost(hwnd)}")

print()
print("=== 结论 ===")
print("  哪个方式真的改变了 WS_EX_TOPMOST，就用哪个。")

frame.Destroy()
