"""临时诊断：SetPreferredAppMode 能不能让原生控件整体变深。

这是深色主题里最关键的一步。`uxtheme.dll` 有个未公开导出
`SetPreferredAppMode`（序号 135），调用后 Windows 会按深色渲染
滚动条、表头、菜单、MessageBox 等**系统绘制**的控件。

先确认：这台机器上能不能调到、调用后是否真的改变了控件的绘制。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

print("=== ① uxtheme 里有没有 SetPreferredAppMode ===")
uxtheme = ctypes.WinDLL("uxtheme")
by_name = None
try:
    by_name = uxtheme.SetPreferredAppMode
    print(f"  按名字取到: {by_name}")
except AttributeError as exc:
    print(f"  按名字取不到: {exc}")

by_ordinal = None
try:
    by_ordinal = uxtheme[135]
    print(f"  按序号 135 取到: {by_ordinal}")
except Exception as exc:  # noqa: BLE001
    print(f"  按序号 135 取不到: {exc!r}")

print()
print("=== ② 调用 ForceDark 前后，系统绘制的滚动条尺寸/配色有没有变 ===")
import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def probe(tag):
    frame = wx.Frame(None, size=(320, 200))
    lc = wx.ListCtrl(frame, style=wx.LC_REPORT)
    lc.InsertColumn(0, "列", width=200)
    for i in range(40):
        lc.InsertItem(i, f"行 {i}")
    frame.Show()
    for _ in range(30):
        wx.YieldIfNeeded()
    # 取垂直滚动条的宽度作为"系统主题是否被应用"的一个可读代理
    import win32gui
    info = win32gui.GetScrollBarInfo(lc.GetHandle(), win32gui.OBJID_VSCROLL) \
        if hasattr(win32gui, "GetScrollBarInfo") else None
    print(f"  {tag}: 列表客户区={lc.GetClientSize()}  滚动条信息={info}")
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()


try:
    import win32gui  # noqa: F401
    have_pywin32 = True
except ImportError:
    have_pywin32 = False
print(f"  pywin32 可用 = {have_pywin32}")

from file_tracker import win32 as ft_win32

print()
print("=== ③ 调用我们的封装 ===")
print(f"  set_process_dark_mode(True)  = {ft_win32.set_process_dark_mode(True)}")
print(f"  set_process_dark_mode(False) = {ft_win32.set_process_dark_mode(False)}")

print()
print("=== 结论 ===")
print("  只要 ③ 两个调用都返回 True，就说明这个接口在本机可用。")
print("  之后原生控件（滚动条/表头/菜单/MessageBox）会跟着深色走。")
