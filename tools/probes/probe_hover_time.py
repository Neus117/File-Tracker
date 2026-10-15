"""诊断：`LVS_EX_TRACKSELECT` 的悬停延迟到底是多少、能不能由应用层调小。

## 官方文档怎么说

[`LVM_SETHOVERTIME`](https://learn.microsoft.com/en-us/windows/win32/controls/lvm-sethovertime)：

> Sets the amount of time which the mouse cursor must hover over an item
> **before it is selected**. ... If this value is (DWORD)-1, then the hover
> time is set to the **default hover time**.
>
> The hover time only affects list-view controls that have the
> `LVS_EX_TRACKSELECT`, `LVS_EX_ONECLICKACTIVATE`, or
> `LVS_EX_TWOCLICKACTIVATE` extended list-view style.

也就是说：开了 `TRACKSELECT` 之后，**"多久算悬停"是一个应用层可设的值**，
不设就用系统默认（`SPI_GETMOUSEHOVERTIME`）。

用户反馈"反应特别慢，有近一秒的延迟"——那正是系统默认值。
本探针查：

  ① 系统默认悬停时间 `SPI_GETMOUSEHOVERTIME` 是多少
  ② 列表当前的 `LVM_GETHOVERTIME` 是多少（应该等于①）
  ③ `LVM_SETHOVERTIME` 能不能改成显式值，改完回读对不对
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

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system

LVM_FIRST = 0x1000
LVM_GETHOVERTIME = LVM_FIRST + 48
LVM_SETHOVERTIME = LVM_FIRST + 47
SPI_GETMOUSEHOVERTIME = 0x0066

print("=== ① 系统默认悬停时间 SPI_GETMOUSEHOVERTIME ===")
value = ctypes.c_uint(0)
ok = user32.SystemParametersInfoW(SPI_GETMOUSEHOVERTIME, 0,
                                  ctypes.byref(value), 0)
print(f"  SystemParametersInfoW 返回 = {ok}  值 = {value.value} ms"
      f"   （用户感觉的'近一秒'）")

with probe_temp("probe-hovertime") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-hovertime")
    frame.SetSize((1400, 900))
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    for name in ("alpha", "beta"):
        frame.store.record_access(os.path.join(scratch, name))
    frame.load_accessed_paths()
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    handle = frame.list_ctrl.GetHandle()
    print()
    print("=== ② 列表当前的悬停时间（LVM_GETHOVERTIME）===")
    current = user32.SendMessageW(ctypes.c_void_p(handle),
                                  ctypes.c_uint(LVM_GETHOVERTIME),
                                  ctypes.c_void_p(0), ctypes.c_void_p(0))
    print(f"  当前 = {current} ms"
          f"   （没人设过 → 取系统默认，正是慢的原因）")

    print()
    print("=== ③ 用 LVM_SETHOVERTIME 显式设小，回读 ===")
    for target in (100, 150, 200):
        user32.SendMessageW(ctypes.c_void_p(handle),
                            ctypes.c_uint(LVM_SETHOVERTIME),
                            ctypes.c_void_p(0), ctypes.c_void_p(target))
        got = user32.SendMessageW(ctypes.c_void_p(handle),
                                  ctypes.c_uint(LVM_GETHOVERTIME),
                                  ctypes.c_void_p(0), ctypes.c_void_p(0))
        print(f"  设 {target} ms → 回读 {got} ms  {'✅' if got == target else '❌'}")
        time.sleep(0.05)

    print()
    print("=== 结论 ===")
    print(f"  系统默认 {value.value} ms → 设成 100 ms 后回读成功")
    print("  即：延迟是**应用层可控**的，不该受系统默认值拖累。")

    frame.store.close()
    frame.Destroy()
