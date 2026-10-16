"""量：列表的**双缓冲**现在是开还是关，`SetDoubleBuffered(True)` 有没有用。

## 为什么要先量

表头那几轮里见过 `LVS_EX_DOUBLEBUFFER`（扩展样式位 `0x00010000`），
所以**很可能已经开着了** —— 那就没必要再加一句。

判据三条：

1. 扩展样式里 `LVS_EX_DOUBLEBUFFER` 位**现在是不是 1**
2. `SetDoubleBuffered(True)` 之后那一位变没变
3. 调它**前后重建耗时**有没有差别（没差别就说明早就开着）

**"我觉得会更快"不算证据。**
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
import file_tracker.win32 as win32
from file_tracker import lang

LVS_EX_DOUBLEBUFFER = 0x00010000

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

COUNT = 1500


def settle(times: int = 20) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()


def ext_style(handle: int) -> int:
    GWL_EXSTYLE = -20
    return ctypes.windll.user32.GetWindowLongW(ctypes.c_void_p(handle), GWL_EXSTYLE)


def rebuild_cost(frame, rounds: int = 3) -> float:
    """跑几轮 `_render_rows()`，取平均毫秒数。"""
    best = []
    for _ in range(rounds):
        started = time.perf_counter()
        frame._render_rows()
        settle(8)
        best.append((time.perf_counter() - started) * 1000)
    return sum(best) / len(best)


with probe_temp("probe-doublebuffer") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:05d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(60)
    ctrl = frame.list_ctrl
    handle = ctrl.GetHandle()

    before = ext_style(handle)
    print(f"  行数 = {ctrl.GetItemCount()}")
    print(f"  ── 现状 ──")
    print(f"    扩展样式 = {before:#010x}")
    print(f"    LVS_EX_DOUBLEBUFFER 位 = "
          f"{'**1（已开）**' if before & LVS_EX_DOUBLEBUFFER else '0（未开）'}")
    print(f"    wx 的 IsDoubleBuffered() = {ctrl.IsDoubleBuffered()}")
    print()

    cost_before = rebuild_cost(frame)
    print(f"    重建耗时（加之前）= {cost_before:.0f} ms")

    ctrl.SetDoubleBuffered(True)
    settle(20)
    after = ext_style(handle)
    print()
    print(f"  ── SetDoubleBuffered(True) 之后 ──")
    print(f"    扩展样式 = {after:#010x}")
    print(f"    LVS_EX_DOUBLEBUFFER 位 = "
          f"{'**1**' if after & LVS_EX_DOUBLEBUFFER else '0'}")
    print(f"    wx 的 IsDoubleBuffered() = {ctrl.IsDoubleBuffered()}")
    print(f"    样式位有没有变化 = {'**有**' if before != after else '没有'}")

    cost_after = rebuild_cost(frame)
    print(f"    重建耗时（加之后）= {cost_after:.0f} ms")
    print()
    if before & LVS_EX_DOUBLEBUFFER:
        print("  ⚠️ **本来就是开的** —— 再加一句 `SetDoubleBuffered(True)` 没有意义")
    elif after & LVS_EX_DOUBLEBUFFER:
        delta = cost_before - cost_after
        print(f"  ✅ 原本没开，现在开了。耗时变化 {delta:+.0f} ms")
    else:
        print("  ❌ 调了也没开 —— 这个接口在原生列表上不生效")

    frame.store.close()
    frame.Destroy()
