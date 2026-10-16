"""拖拽多选（框选）到底怎么才能work —— 逐项试。

## 已知

清掉**原生** `LVS_SINGLESEL`（`SetWindowLongW`）之后：
* Ctrl 点击 → ✅ 累加选中 `[1, 4]`
* Shift 点击 → ✅ 连选 `[2,3,4,5,6]`
* **拖拽 → ❌ 只选中按下那一行 `[3]`**

## 本探针逐个排除

| # | 试什么 | 为什么怀疑它 |
|---|---|---|
| ① | 拖动时 `WM_MOUSEMOVE` 的 `wParam` 带不带 `MK_LBUTTON` | 不带时 ListView 可能不认为在拖 |
| ② | 拖动中间**多插几步 + 更长延时** | 消息太快，拖拽状态机没跟上 |
| ③ | 拖动前先 `SetCapture` | 原生拖拽可能依赖捕获 |
| ④ | 先选中起点行再拖 | 某些实现要求起点已在选中集里 |
| ⑤ | 加 `LVS_EX_DOUBLEBUFFER` | 框选会画橡皮筋，可能需要它 |
| ⑥ | `WM_MOUSEMOVE` 直接发到**桌面/父窗口** | 捕获后消息去向变了 |

## 判据

哪一种组合能让**拖动**选出**多于一行**。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang, win32

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

user32 = ctypes.windll.user32
send_message = user32.SendMessageW
send_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                         ctypes.c_void_p, ctypes.c_void_p]
send_message.restype = ctypes.c_void_p
post_message = user32.PostMessageW
post_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                         ctypes.c_void_p, ctypes.c_void_p]

GWL_STYLE = -16
LVS_SINGLESEL = 0x0004
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
MK_LBUTTON = 0x0001


def pump(rounds=20, pause=0.006):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def set_native_style(hwnd, style):
    user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE, style)


def selected_rows(ctrl):
    rows = []
    index = ctrl.GetFirstSelected()
    while index != -1:
        rows.append(index)
        index = ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    return rows


def clear(ctrl, count):
    for i in range(count):
        ctrl.Select(i, False)
    pump(8)


def try_drag(ctrl, r_from, r_to, *, label,
             move_with_button=True, steps=8, pause=6,
             set_capture=False, preselect=False, double_buffer=False):
    a, b = ctrl.GetItemRect(r_from), ctrl.GetItemRect(r_to)
    if a.height <= 0 or b.height <= 0:
        return None
    if double_buffer:
        win32.set_extended_style(ctrl.GetHandle(),
                                win32.LVS_EX_DOUBLEBUFFER,
                                win32.LVS_EX_DOUBLEBUFFER)
    if preselect:
        ctrl.Select(r_from, True)
        pump(8)
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    x = min(150, max(a.width // 5, 10))
    y0 = a.y + a.height // 2
    y1 = b.y + b.height // 2
    lp0 = ctypes.c_void_p((y0 << 16) | (x & 0xFFFF))
    send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON), lp0)
    if set_capture:
        user32.SetCapture(hwnd)
    for step in range(1, steps + 1):
        y = y0 + (y1 - y0) * step // steps
        flags = MK_LBUTTON if move_with_button else 0
        send_message(hwnd, WM_MOUSEMOVE, ctypes.c_void_p(flags),
                     ctypes.c_void_p((y << 16) | (x & 0xFFFF)))
        time.sleep(pause / 1000.0)
    send_message(hwnd, WM_LBUTTONUP, None,
                 ctypes.c_void_p((y1 << 16) | (x & 0xFFFF)))
    if set_capture:
        user32.ReleaseCapture()
    pump(20)
    rows = selected_rows(ctrl)
    print("   %-42s 选中 = %s" % (label, rows))
    return rows


with probe_temp("probe-drag") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    hwnd = ctrl.GetHandle()
    count = ctrl.GetItemCount()
    set_native_style(hwnd, user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
                     & ~LVS_SINGLESEL)
    pump(20)
    ctrl.SetFocus()
    pump(15)
    print("行数 = %d   LVS_SINGLESEL 已清 = %s\n"
          % (count, not (user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
                         & LVS_SINGLESEL)))

    try:
        variants = [
            ("① 带 MK_LBUTTON（基线）", dict()),
            ("② 带 MK_LBUTTON + 更多步/更慢", dict(steps=16, pause=20)),
            ("③ 带 MK_LBUTTON + SetCapture", dict(set_capture=True)),
            ("④ 先选中起点再拖", dict(preselect=True)),
            ("⑤ 加 LVS_EX_DOUBLEBUFFER", dict(double_buffer=True)),
            ("⑥ 步数多+捕获+预选+双缓冲", dict(steps=16, pause=15,
                                              set_capture=True,
                                              preselect=True,
                                              double_buffer=True)),
            ("⑦ **不带** MK_LBUTTON", dict(move_with_button=False)),
        ]
        best = []
        for label, kwargs in variants:
            clear(ctrl, count)
            pump(6)
            rows = try_drag(ctrl, 3, 8, label=label, **kwargs)
            if rows and len(rows) >= 3:
                best.append((label, rows))
        print("\n── 结论 ──")
        if best:
            print("   能拖出一段的有 %d 种：" % len(best))
            for label, rows in best:
                print("     %s → %s" % (label, rows))
        else:
            print("   ❌ **没有一种组合**能让拖拽选出多行。")
            print("      ⇒ 需要自己实现拖拽选择（拦截鼠标事件 + 用行号算范围）。")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
