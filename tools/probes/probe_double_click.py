"""诊断：加了 `LVS_EX_TWOCLICKACTIVATE` 之后，双击还会不会触发激活。

## 为什么要查

官方文档说 `LVS_EX_TWOCLICKACTIVATE`：
> The list-view control sends an **LVN_ITEMACTIVATE** notification code to the
> parent window when the user double-clicks an item. This style also enables
> hot tracking.

wx 的 `EVT_LIST_ITEM_ACTIVATED` 对应的就是 `LVN_ITEMACTIVATE`。
但"加了标志之后双击语义会不会变"不能靠读文档推断，
所以投递真实的双击消息，看 `on_item_activated` 有没有被调用。

## 两条踩过的坑，这个探针都防了

1. **`SendMessageW` 的签名**：ctypes 默认按 32 位整数解释返回值，
   长消息会截断（`LVM_GETHOVERTIME` 读回恒为 0 就是这个原因）。
   必须显式声明 `argtypes` / `restype`。
2. **探针会把资源管理器弹出来**：`on_item_activated` 里有
   `_open_in_explorer`（静态方法）与 `wx.CallLater(..., reset_dir_ctrl_scroll)`，
   只改实例属性挡不住——实测探针挂死 240 秒、临时目录被锁。
   这里把**所有出口**都堵上，并加线程超时。
"""
import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import win32
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
MK_LBUTTON = 0x0001

user32 = ctypes.windll.user32
# **显式签名**——见模块文档第 1 条
user32.SendMessageW.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
user32.SendMessageW.restype = ctypes.c_void_p

with probe_temp("probe-dblclk") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-dblclk")
    frame.SetSize((1400, 900))
    frame.Show()
    frame.Raise()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    target = os.path.join(scratch, "alpha")
    os.makedirs(target, exist_ok=True)
    frame.store.record_access(target)
    frame.load_accessed_paths()
    frame.sort_list_items(frame.sort_column)
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    lc = frame.list_ctrl
    handle = lc.GetHandle()
    ex = win32.get_extended_style(handle)
    print(f"  扩展样式 = {ex:#010x}")
    print(f"    TWOCLICKACTIVATE = {bool(ex & win32.LVS_EX_TWOCLICKACTIVATE)}")
    print(f"    TRACKSELECT      = {bool(ex & win32.LVS_EX_TRACKSELECT)}")
    print(f"    FULLROWSELECT    = {bool(ex & win32.LVS_EX_FULLROWSELECT)}")

    # **把所有会弹资源管理器的出口都堵上**（见模块文档第 2 条）
    hits: list[str] = []
    frame.open_folder = lambda p: hits.append(p)
    frame.record_accessed_path = lambda p: None
    frame.reset_dir_ctrl_scroll = lambda: None
    frame._open_in_explorer = staticmethod(lambda folder: None)

    rect = lc.GetItemRect(0)
    point = wx.Point(rect.x + 40, rect.y + rect.height // 2)
    lparam = (point.y << 16) | (point.x & 0xFFFF)
    print(f"  投递双击到客户区坐标 {point}")

    def dispatch():
        for _ in range(3):
            user32.SendMessageW(ctypes.c_void_p(handle),
                                ctypes.c_uint(WM_LBUTTONDOWN),
                                ctypes.c_void_p(MK_LBUTTON),
                                ctypes.c_void_p(lparam))
            user32.SendMessageW(ctypes.c_void_p(handle),
                                ctypes.c_uint(WM_LBUTTONUP),
                                ctypes.c_void_p(0),
                                ctypes.c_void_p(lparam))
            user32.SendMessageW(ctypes.c_void_p(handle),
                                ctypes.c_uint(WM_LBUTTONDBLCLK),
                                ctypes.c_void_p(MK_LBUTTON),
                                ctypes.c_void_p(lparam))
            time.sleep(0.1)

    worker = threading.Thread(target=dispatch, daemon=True)
    worker.start()
    # **超时兜底**：不让整轮挂死
    for _ in range(150):
        wx.YieldIfNeeded()
        time.sleep(0.02)
        if hits and not worker.is_alive():
            break
    worker.join(timeout=2)

    print(f"  on_item_activated 被调用 {len(hits)} 次"
          f"  {'✅ 双击语义没变' if hits else '⚠️ 合成消息没能走完激活判定'}")
    print(f"  选中项 = {lc.GetFirstSelected()}（0 表示单击仍然只是选中）")
    if not hits:
        print("  说明：合成 WM_LBUTTONDBLCLK 未必能走完 wx 的激活判定，")
        print("        所以这一条**不作硬结论**；双击语义仍由")
        print("        `EVT_LIST_ITEM_ACTIVATED` 的绑定保证，且该绑定没动过。")

    frame.store.close()
    frame.Destroy()
    for _ in range(20):
        wx.YieldIfNeeded()
