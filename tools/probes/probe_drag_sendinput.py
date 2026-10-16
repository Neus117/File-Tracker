"""拖拽多选：用**真的鼠标输入**（`SendInput`）重验。

## 为什么要重验

前一个探针试了 7 种 `SendMessage(WM_LBUTTONDOWN/MOUSEMOVE/LBUTTONUP)`
的组合，**全都只选中按下那一行**，于是写下"没有一种组合能拖出多行，
需要自己实现"。

但那个结论**可能是我的测量手段的问题**：`SendMessage` 是**投递消息**，
而 ListView 的拖拽/框选状态机可能依赖**真正的鼠标输入**
（`SendInput` 产生的那种，会更新系统级的光标位置与按键状态）。

本项目的老教训：**仪器读不到 ≠ 那东西不存在**（`01` 错误七）。
所以在动手自己实现之前，必须用真输入再验一次。

## 做法

`SendInput` 真的移动光标 + 真的按左键 + 真的拖到目标行 + 真的松开。
坐标用 `ClientToScreen` 换算到屏幕坐标。

⚠️ 会真的移动用户的鼠标（探针结束会挪到角落）。
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
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

user32 = ctypes.windll.user32
GWL_STYLE = -16
LVS_SINGLESEL = 0x0004

# ── SendInput 需要的结构 ────────────────────────────────────────────
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]


def send_mouse(flags, x=0, y=0):
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    absolute_x = int(x * 65535 / max(screen_w - 1, 1))
    absolute_y = int(y * 65535 / max(screen_h - 1, 1))
    item = INPUT(type=INPUT_MOUSE,
                 u=_INPUTunion(mi=MOUSEINPUT(
                     dx=absolute_x, dy=absolute_y, mouseData=0,
                     dwFlags=flags | MOUSEEVENTF_ABSOLUTE, time=0,
                     dwExtraInfo=None)))
    user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))


def pump(rounds=20, pause=0.006):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def selected_rows(ctrl):
    rows = []
    index = ctrl.GetFirstSelected()
    while index != -1:
        rows.append(index)
        index = ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    return rows


def row_screen_point(ctrl, row):
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return None
    client = wx.Point(min(150, max(rect.width // 5, 10)),
                      rect.y + rect.height // 2)
    return ctrl.ClientToScreen(client)


with probe_temp("probe-drag-input") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(60):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    frame.Raise()
    pump(70)

    ctrl = frame.list_ctrl
    hwnd = ctrl.GetHandle()
    count = ctrl.GetItemCount()
    user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE,
                          user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
                          & ~LVS_SINGLESEL)
    pump(20)
    ctrl.SetFocus()
    pump(15)
    print("行数 = %d   LVS_SINGLESEL 已清 = %s"
          % (count, not (user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
                         & LVS_SINGLESEL)))

    try:
        for i in range(count):
            ctrl.Select(i, False)
        pump(10)

        start = row_screen_point(ctrl, 3)
        end = row_screen_point(ctrl, 9)
        print("\n起点(屏幕) = %s   终点(屏幕) = %s" % (start, end))

        if start and end:
            send_mouse(MOUSEEVENTF_MOVE, start.x, start.y)
            pump(8)
            send_mouse(MOUSEEVENTF_LEFTDOWN, start.x, start.y)
            pump(8)
            steps = 12
            for step in range(1, steps + 1):
                y = start.y + (end.y - start.y) * step // steps
                send_mouse(MOUSEEVENTF_MOVE, start.x, y)
                time.sleep(0.012)
            pump(8)
            send_mouse(MOUSEEVENTF_LEFTUP, start.x, end.y)
            pump(35)

        rows = selected_rows(ctrl)
        print("\n── 真鼠标输入拖拽（第 3 行 → 第 9 行）──")
        print("   选中 = %s" % rows)
        if len(rows) >= 3:
            print("   ✅ **真输入能拖出多行** ⇒ 原生拖拽可用，"
                  "之前 7 种失败是我的测量手段（SendMessage）不够真。")
        else:
            print("   ❌ 真输入也拖不出多行 ⇒ 原生拖拽确实不可用，需要自己实现。")

        # 再验一次 Ctrl 点击（真输入）
        for i in range(count):
            ctrl.Select(i, False)
        pump(10)
        user32.keybd_event(0x11, 0, 0, 0)          # Ctrl down
        p1 = row_screen_point(ctrl, 1)
        send_mouse(MOUSEEVENTF_MOVE, p1.x, p1.y)
        pump(6)
        send_mouse(MOUSEEVENTF_LEFTDOWN, p1.x, p1.y)
        pump(6)
        send_mouse(MOUSEEVENTF_LEFTUP, p1.x, p1.y)
        pump(12)
        p2 = row_screen_point(ctrl, 5)
        send_mouse(MOUSEEVENTF_MOVE, p2.x, p2.y)
        pump(6)
        send_mouse(MOUSEEVENTF_LEFTDOWN, p2.x, p2.y)
        pump(6)
        send_mouse(MOUSEEVENTF_LEFTUP, p2.x, p2.y)
        pump(20)
        user32.keybd_event(0x11, 0, 0x0002, 0)     # Ctrl up
        print("\n── 真鼠标输入 Ctrl 点击（第 1 行 + 第 5 行）──")
        print("   选中 = %s" % selected_rows(ctrl))
    finally:
        try:
            user32.SetCursorPos(6, 900)            # 把鼠标挪开
        except Exception:
            pass
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
