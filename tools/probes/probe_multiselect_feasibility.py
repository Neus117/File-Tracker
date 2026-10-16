"""可行性：把 `LC_SINGLE_SEL` 去掉之后，多选到底能不能用。

## 为什么先做这个

用户要"按住 CTRL 多选、还能拖动多选"。而现在列表是
`wx.LC_REPORT | wx.LC_SINGLE_SEL | ...`（单选），
且本项目的高亮是**自己画的**（`SetItemBackgroundColour`），
不是原生的 —— 所以有两个未知数：

1. **原生多选**（Ctrl 点选 / 拖拽框选）在这个控件上开不开得起来
2. 开了之后，**我方自绘高亮**能不能正确画出"多行蓝色"，
   会不会和原生高亮打架（本项目的历史：逐行设了底色之后原生高亮就不画了）

## 判据

| # | 判据 |
|---|---|
| ① | 去掉 `LC_SINGLE_SEL` 后，`Select(0)` + `Select(2)` 能同时选中两行 |
| ② | **真按 Ctrl 点击**两行，`GetSelectedItemCount()` == 2（原生行为，不是我调 API） |
| ③ |**真拖拽**（按下→移动→抬起）能选出一段 |
| ④ | 我方 `_apply_selection_highlight` 能给**多行**上蓝色 |
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
send_message = user32.SendMessageW
send_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                         ctypes.c_void_p, ctypes.c_void_p]
send_message.restype = ctypes.c_void_p

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
MK_LBUTTON, MK_CONTROL = 0x0001, 0x0008
VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=25, pause=0.005):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def click(ctrl, row, *, ctrl_down=False, motion=False):
    """在某一行的中心发真的鼠标消息。`ctrl_down` 时先按下 Ctrl 键。"""
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return False
    x = min(200, max(rect.width // 4, 10))
    y = rect.y + rect.height // 2
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    lp = ctypes.c_void_p((y << 16) | (x & 0xFFFF))
    if ctrl_down:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
    try:
        send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON), lp)
        if motion:
            send_message(hwnd, WM_MOUSEMOVE, ctypes.c_void_p(MK_LBUTTON), lp)
        send_message(hwnd, WM_LBUTTONUP, None, lp)
    finally:
        if ctrl_down:
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    return True


def selected_rows(ctrl):
    rows = []
    index = ctrl.GetFirstSelected()
    while index != -1:
        rows.append(index)
        index = ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    return rows


with probe_temp("probe-multisel-feasibility") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    style = ctrl.GetWindowStyleFlag()
    print("当前样式: LC_SINGLE_SEL = %s" % bool(style & wx.LC_SINGLE_SEL))

    try:
        # ── ① 去掉 LC_SINGLE_SEL，再试 API 多选 ──────────────────
        ctrl.SetWindowStyleFlag(style & ~wx.LC_SINGLE_SEL)
        pump(20)
        for i in range(15):
            ctrl.Select(i, False)
        ctrl.Select(0, True)
        ctrl.Select(2, True)
        pump(15)
        api_rows = selected_rows(ctrl)
        print("\n① API 多选（Select(0)+Select(2)） = %s  count=%d"
              % (api_rows, len(api_rows)))
        check("① 去掉 LC_SINGLE_SEL 后 API 能多选", len(api_rows) >= 2,
              "选中 = %s" % api_rows)

        # ── ② 真按 Ctrl 点击两行 ──────────────────────────────────
        for i in range(15):
            ctrl.Select(i, False)
        pump(10)
        ctrl.SetFocus()
        pump(10)
        click(ctrl, 1)
        pump(15)
        after_first = selected_rows(ctrl)
        click(ctrl, 4, ctrl_down=True)
        pump(20)
        ctrl_rows = selected_rows(ctrl)
        print("② 真 Ctrl 点击：第一次后 = %s，Ctrl 点第二行后 = %s"
              % (after_first, ctrl_rows))
        check("② 真按 Ctrl 点击能多选（原生行为）", len(ctrl_rows) >= 2,
              "选中 = %s" % ctrl_rows)

        # ── ③ 真拖拽（按下第 0 行 → 移到第 5 行 → 抬起）──────────
        for i in range(15):
            ctrl.Select(i, False)
        pump(10)
        r0, r5 = ctrl.GetItemRect(0), ctrl.GetItemRect(5)
        if r0.height > 0 and r5.height > 0:
            hwnd = ctypes.c_void_p(ctrl.GetHandle())
            x = min(200, max(r0.width // 4, 10))
            y0 = r0.y + r0.height // 2
            y5 = r5.y + r5.height // 2
            send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON),
                         ctypes.c_void_p((y0 << 16) | (x & 0xFFFF)))
            for step in range(6):
                y = y0 + (y5 - y0) * step // 5
                send_message(hwnd, WM_MOUSEMOVE, ctypes.c_void_p(MK_LBUTTON),
                             ctypes.c_void_p((y << 16) | (x & 0xFFFF)))
                pump(3)
            send_message(hwnd, WM_LBUTTONUP, None,
                         ctypes.c_void_p((y5 << 16) | (x & 0xFFFF)))
        pump(25)
        drag_rows = selected_rows(ctrl)
        print("③ 真拖拽（0 → 5）后选中 = %s" % drag_rows)
        check("③ 真拖拽能选中一段", len(drag_rows) >= 2, "选中 = %s" % drag_rows)

        # ── ④ 我方高亮能不能画多行蓝 ──────────────────────────────
        for i in range(15):
            ctrl.Select(i, False)
        ctrl.Select(2, True)
        ctrl.Select(3, True)
        ctrl.Select(4, True)
        pump(10)
        events = []
        original = ctrl.SetItemBackgroundColour

        def spy(row, colour):
            events.append((row, colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()))
            return original(row, colour)

        ctrl.SetItemBackgroundColour = spy
        frame._paint_key = None
        frame._apply_selection_highlight()
        ctrl.SetItemBackgroundColour = original
        pump(15)
        blues = sorted({r for r, c in events if c == highlight})
        print("\n④ 我方高亮画出的蓝行 = %s" % blues)
        print("   （选中行 = %s）" % selected_rows(ctrl))
        check("④ 我方高亮能给多行上蓝色（当前实现）", len(blues) >= 2,
              "蓝行 = %s（单选的 GetFirstSelected 只认一条）" % blues)
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
