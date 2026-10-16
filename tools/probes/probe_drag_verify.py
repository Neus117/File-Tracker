"""拖拽多选：**先验证光标真的落在列表上**，再拖。

## 上一版的错

`probe_drag_sendinput.py` 用 `SendInput` 拖拽，结果 `选中 = []` ——
**连 Ctrl 点击都没点中**，而同样的 Ctrl 点击用 `SendMessage` 是成功的
（`[1, 4]`）。⇒ 那次是**坐标/激活**的问题，不是"原生拖拽不可用"。

**不能拿一次"什么都没选中"的读数去支持"不可用"的结论**
（`01` 错误七：仪器读不到 ≠ 那东西不存在）。

## 本探针

**每一步都验证**"光标现在真的在列表客户区里、并且在第 N 行上"：

* `SetCursorPos` 移到目标
* `WindowFromPoint(点)` 必须是那个 `ListCtrl` 的 hwnd
* `HitTest(客户区坐标)` 必须返回期望的行号

验完再拖。拖拽用 `SendInput`（真输入）+ 逐点 `SetCursorPos` 兜底。
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
user32.WindowFromPoint.restype = ctypes.c_void_p
GWL_STYLE = -16
LVS_SINGLESEL = 0x0004

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def pump(rounds=18, pause=0.006):
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


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return wx.Point(p.x, p.y)


def hit_row(ctrl, screen_point):
    """屏幕点 → 该控件客户区坐标 → 行号（不在控件上返回 -1）。"""
    client = ctypes.wintypes.POINT(screen_point.x, screen_point.y) \
        if hasattr(ctypes, "wintypes") else None
    local = ctrl.ScreenToClient(screen_point)
    row, _flags = ctrl.HitTest(local)
    return row


def verify_on_row(ctrl, row, screen_point):
    """三件事都对才算"光标真的落在第 row 行上"。"""
    under = user32.WindowFromPoint(POINT(screen_point.x, screen_point.y))
    local = ctrl.ScreenToClient(screen_point)
    hit, _flags = ctrl.HitTest(local)
    ok_window = (under == ctrl.GetHandle())
    ok_row = (hit == row)
    return ok_window, ok_row, hit


with probe_temp("probe-drag-verify") as scratch:
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

        # ── 先验证坐标 ────────────────────────────────────────
        print("\n── 坐标验证（每行：窗口归属 + HitTest 行号）──")
        points = {}
        for row in (3, 6, 9):
            rect = ctrl.GetItemRect(row)
            client = wx.Point(min(150, max(rect.width // 5, 10)),
                              rect.y + rect.height // 2)
            screen = ctrl.ClientToScreen(client)
            user32.SetCursorPos(screen.x, screen.y)
            pump(8)
            actual = cursor_pos()
            ok_window, ok_row, hit = verify_on_row(ctrl, row, actual)
            points[row] = actual
            print("   row %d: 目标屏幕=%s 实际光标=%s  归属正确=%s  行号命中=%s"
                  % (row, screen, actual, ok_window, ok_row))
            print("           HitTest = %s（期望 %d）" % (hit, row))

        if not all(verify_on_row(ctrl, r, points[r])[1] for r in points):
            print("\n   ❌ 坐标没对准 —— 那就不该继续拖拽（结论会不可信）")
        else:
            # ── 真拖拽 ────────────────────────────────────────
            print("\n── 真拖拽（第 3 行 → 第 9 行）──")
            start, end = points[3], points[9]
            user32.SetCursorPos(start.x, start.y)
            pump(6)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            pump(4)
            steps = 14
            for step in range(1, steps + 1):
                y = start.y + (end.y - start.y) * step // steps
                user32.SetCursorPos(start.x, y)
                time.sleep(0.015)
            pump(6)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            pump(30)
            rows = selected_rows(ctrl)
            print("   选中 = %s" % rows)
            if len(rows) >= 3:
                print("   ✅ **原生拖拽可用**（真输入 + 坐标对准）")
            else:
                print("   ❌ 坐标对准了仍然拖不出多行 ⇒ 原生拖拽确实不可用")

            # ── 真 Ctrl 点击（同一套坐标，作为对照）────────────
            for i in range(count):
                ctrl.Select(i, False)
            pump(10)
            user32.keybd_event(0x11, 0, 0, 0)
            for row in (1, 5):
                point = points.get(row)
                if point is None:
                    rect = ctrl.GetItemRect(row)
                    point = ctrl.ClientToScreen(wx.Point(
                        min(150, max(rect.width // 5, 10)),
                        rect.y + rect.height // 2))
                user32.SetCursorPos(point.x, point.y)
                pump(6)
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                pump(5)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                pump(12)
            user32.keybd_event(0x11, 0, 0x0002, 0)
            pump(20)
            print("\n── 对照：真 Ctrl 点击（第 1 + 第 5 行）──")
            print("   选中 = %s" % selected_rows(ctrl))
    finally:
        try:
            user32.SetCursorPos(6, 900)
        except Exception:
            pass
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
