"""多选可行性（原生口径）：直接读/改 `GWL_STYLE`，再用**真鼠标消息**验。

## 上一版探针的疑点

`probe_multiselect_feasibility.py` 的结果是分裂的：

* ① API 多选（`Select(0)`+`Select(2)`）→ **成功**（选中 `[0, 2]`）
* ② 真 Ctrl 点击 → **失败**（只选中 `[4]`）
* ③ 真拖拽 → **失败**（只选中 `[0]`）

API 能多选、鼠标不能 —— 这个组合本身可疑。最可能的原因：
**我用 `SetWindowStyleFlag()` 只改了 wx 侧，原生的 `LVS_SINGLESEL` 位还在**。
本项目对"wx 样式 ≠ 原生样式"有先例（`LVS_NOCOLUMNHEADER` 被 wx 丢掉那次）。

## 本探针的口径

**一切以原生样式位为准**（`GetWindowLongW(hwnd, GWL_STYLE)`），
不用 wx 的自报值：

1. 读原生 `LVS_SINGLESEL` / `LVS_SHOWSELALWAYS`
2. 用 `SetWindowLongW` **真的清掉** `LVS_SINGLESEL`
3. **真 Ctrl 点击**、**真拖拽**，看选中集

## 判据

| # | 判据 |
|---|---|
| ① | 清掉原生 `LVS_SINGLESEL` 后，**真 Ctrl 点击**能累加选中 |
| ② | **真拖拽**能选出一段 |
| ③ | 选中集里**每一项**都能被我们的高亮画成蓝色（交给后续实现） |
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

GWL_STYLE = -16
LVS_SINGLESEL = 0x0004
LVS_SHOWSELALWAYS = 0x0008
LVS_OWNERDRAWFIXED = 0x0400

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
MK_LBUTTON, MK_CONTROL, MK_SHIFT = 0x0001, 0x0008, 0x0004
VK_CONTROL, VK_SHIFT = 0x11, 0x10
KEYEVENTF_KEYUP = 0x0002

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=25, pause=0.005):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def native_style(hwnd):
    return user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)


def set_native_style(hwnd, style):
    user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE, style)


def selected_rows(ctrl):
    rows = []
    index = ctrl.GetFirstSelected()
    while index != -1:
        rows.append(index)
        index = ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    return rows


def clear_selection(ctrl, count):
    for i in range(count):
        ctrl.Select(i, False)
    pump(10)


def modifiers(keys):
    """按下若干修饰键，返回一个"抬起"用的闭包。"""
    for vk in keys:
        user32.keybd_event(vk, 0, 0, 0)
    def release():
        for vk in reversed(keys):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    return release


def click(ctrl, row, *, ctrl_down=False, shift_down=False):
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return False
    x = min(150, max(rect.width // 5, 10))
    y = rect.y + rect.height // 2
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    lp = ctypes.c_void_p((y << 16) | (x & 0xFFFF))
    keys = []
    if ctrl_down:
        keys.append(VK_CONTROL)
    if shift_down:
        keys.append(VK_SHIFT)
    release = modifiers(keys) if keys else (lambda: None)
    flags = MK_LBUTTON | (MK_CONTROL if ctrl_down else 0) \
        | (MK_SHIFT if shift_down else 0)
    try:
        send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(flags), lp)
        send_message(hwnd, WM_LBUTTONUP, ctypes.c_void_p(flags & ~MK_LBUTTON), lp)
    finally:
        release()
    return True


def drag(ctrl, row_from, row_to):
    a, b = ctrl.GetItemRect(row_from), ctrl.GetItemRect(row_to)
    if a.height <= 0 or b.height <= 0:
        return False
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    x = min(150, max(a.width // 5, 10))
    y0 = a.y + a.height // 2
    y1 = b.y + b.height // 2
    send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON),
                 ctypes.c_void_p((y0 << 16) | (x & 0xFFFF)))
    steps = 8
    for step in range(1, steps + 1):
        y = y0 + (y1 - y0) * step // steps
        send_message(hwnd, WM_MOUSEMOVE, ctypes.c_void_p(MK_LBUTTON),
                     ctypes.c_void_p((y << 16) | (x & 0xFFFF)))
        pump(3)
    send_message(hwnd, WM_LBUTTONUP, None,
                 ctypes.c_void_p((y1 << 16) | (x & 0xFFFF)))
    return True


with probe_temp("probe-multisel-native") as scratch:
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
    hwnd = ctrl.GetHandle()
    count = ctrl.GetItemCount()

    before = native_style(hwnd)
    print("=== ① 原生样式位（GWL_STYLE = %#010x）===" % before)
    print("   LVS_SINGLESEL     = %s" % bool(before & LVS_SINGLESEL))
    print("   LVS_SHOWSELALWAYS = %s" % bool(before & LVS_SHOWSELALWAYS))
    print("   LVS_OWNERDRAWFIXED= %s   ← True 的话自绘/多选会互相干扰"
          % bool(before & LVS_OWNERDRAWFIXED))
    print("   wx 自报 LC_SINGLE_SEL = %s" % bool(ctrl.GetWindowStyleFlag() & wx.LC_SINGLE_SEL))

    try:
        # ══ ② 真的用 SetWindowLongW 清掉 LVS_SINGLESEL ═══════════
        set_native_style(hwnd, before & ~LVS_SINGLESEL)
        pump(25)
        after = native_style(hwnd)
        print("\n=== ② 清掉之后原生样式 = %#010x   LVS_SINGLESEL = %s ==="
              % (after, bool(after & LVS_SINGLESEL)))
        check("① 原生 LVS_SINGLESEL 能被清掉", not (after & LVS_SINGLESEL),
              "清前=%#x 清后=%#x" % (before, after))

        ctrl.SetFocus()
        pump(15)

        # ══ ③ 真 Ctrl 点击 ═══════════════════════════════════════
        clear_selection(ctrl, count)
        click(ctrl, 1)
        pump(20)
        first = selected_rows(ctrl)
        click(ctrl, 4, ctrl_down=True)
        pump(25)
        ctrl_rows = selected_rows(ctrl)
        print("\n=== ③ 真 Ctrl 点击 ===")
        print("   点第 1 行后       = %s" % first)
        print("   Ctrl 点第 4 行后  = %s" % ctrl_rows)
        check("② 真按 Ctrl 点击能**累加**选中", len(ctrl_rows) >= 2,
              "选中 = %s（点一次=%s）" % (ctrl_rows, first))

        # ══ ④ 真 Shift 点击（连选一段）═══════════════════════════
        clear_selection(ctrl, count)
        click(ctrl, 2)
        pump(15)
        click(ctrl, 6, shift_down=True)
        pump(25)
        shift_rows = selected_rows(ctrl)
        print("\n=== ④ 真 Shift 点击（2 → 6）===")
        print("   选中 = %s" % shift_rows)
        check("③ 真按 Shift 点击能选中一段", len(shift_rows) >= 3,
              "选中 = %s" % shift_rows)

        # ══ ⑤ 真拖拽 ═════════════════════════════════════════════
        clear_selection(ctrl, count)
        drag(ctrl, 3, 8)
        pump(30)
        drag_rows = selected_rows(ctrl)
        print("\n=== ⑤ 真拖拽（3 → 8）===")
        print("   选中 = %s" % drag_rows)
        check("④ 真拖拽能选中一段", len(drag_rows) >= 3, "选中 = %s" % drag_rows)
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
