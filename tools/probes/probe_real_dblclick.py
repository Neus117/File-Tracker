"""用**真的双击**（Windows 鼠标消息）测导航窗格里的文件 —— 只看行为，不碰接线。

## 为什么这个探针改了三版

| 版本 | 做法 | 结果 |
|---|---|---|
| 1 | 直接调 `on_dir_item_activated(伪造事件)` | 全绿，**而用户说没修好** |
| 2 | 真双击 + `spy` 替换 handler | 发现真双击**不进**那个 handler |
| **3（本版）** | 真双击、**完全不碰事件绑定**、只看行为 | ← 你在这里 |

前两版的毛病是同一个（`01` 错误一）：**测的是我以为的链路，不是用户的链路**。
版本 2 还用 `Unbind` 把程序的接线摘掉再自己绑，那测的又是我自己的接线。

⇒ 本版**一行绑定都不动**，只观测行为结果。

## 判据

| # | 判据 |
|---|---|
| ① | 双击文件后**焦点到了记录列表**（用户报的就是这一条） |
| ② | 记录列表里**选中了**刚记录的那条（= 文件的**父文件夹**） |
| ③ | 那条被**上成高亮蓝** |
| ④ | 阳性对照：「打开」按钮那条路仍然正常（没被改坏） |
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

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
MK_LBUTTON = 0x0001

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=25, pause=0.005):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def focus_name():
    focus = wx.Window.FindFocus()
    return type(focus).__name__ if focus else "None"


def item_point(tree, item):
    rect = tree.GetBoundingRect(item)
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None
    return rect.x + max(rect.width // 6, 8), rect.y + rect.height // 2


def real_double_click(tree, item):
    """发真正的双击鼠标消息序列（DOWN/UP/DBLCLK/UP）。"""
    point = item_point(tree, item)
    if point is None:
        return False
    x, y = point
    hwnd = ctypes.c_void_p(tree.GetHandle())
    lparam = ctypes.c_void_p((y << 16) | (x & 0xFFFF))
    send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON), lparam)
    send_message(hwnd, WM_LBUTTONUP, None, lparam)
    send_message(hwnd, WM_LBUTTONDBLCLK, ctypes.c_void_p(MK_LBUTTON), lparam)
    send_message(hwnd, WM_LBUTTONUP, None, lparam)
    return True


class Painter:
    """记录给哪一行上过什么色（只观测，不改行为）。"""

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.rows = []
        self.original = ctrl.SetItemBackgroundColour

        def wrapper(row, colour):
            self.rows.append((row, colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()))
            return self.original(row, colour)

        wrapper.__name__ = "wrapped"
        ctrl.SetItemBackgroundColour = wrapper

    def take(self):
        out, self.rows = self.rows, []
        return out

    def stop(self):
        self.ctrl.SetItemBackgroundColour = self.original


with probe_temp("probe-real-dblclick") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    victim_file = os.path.join(scratch, "target-file.txt")
    with open(victim_file, "w", encoding="utf-8") as handle:
        handle.write("probe\n")
    victim_folder = scratch      # 双击文件 → 应当记录**父文件夹**

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    tree = frame.dir_ctrl.GetTreeCtrl()
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    painter = Painter(ctrl)
    print("系统高亮 = %s" % highlight)
    print("双击的文件 = %s" % victim_file)
    print("应记录（父文件夹）= …%s" % victim_folder[-26:])

    try:
        item = tree.expand_to(victim_file, select=True)
        if item is None or not item.IsOk():
            print("（树里定位不到该文件，退回父目录）")
            item = tree.expand_to(victim_folder, select=True)
        tree.EnsureVisible(item)
        pump(25)
        print("树里目标项 = …%s" % frame.dir_ctrl.GetPath(item)[-30:])

        # ══ 真双击 ══════════════════════════════════════════════════
        tree.SetFocus()                  # 模拟"用户刚在导航窗格操作"
        frame._focus_pane = "list"       # 故意留个残留值，复刻修复前的处境
        pump(20)
        painter.take()
        before_count = ctrl.GetItemCount()

        print("\n【真双击前】焦点=%s 列表行数=%d" % (focus_name(), before_count))
        real_double_click(tree, item)
        pump(45)

        selected = ctrl.GetFirstSelected()
        painted = painter.take()
        colours = [c for r, c in painted if r == selected]
        print("\n【真双击后】")
        print("   焦点 = %s" % focus_name())
        print("   列表行数 = %d（前 %d）" % (ctrl.GetItemCount(), before_count))
        print("   选中 = %s（…%s）" % (selected, frame.row_path(selected)[-28:]))
        print("   上过的色 = %s" % colours)

        check("① 真双击文件后：**焦点转移到记录列表**",
              focus_name() == "ListCtrl", "焦点 = %s" % focus_name())
        check("② 真双击文件后：选中了刚记录的那条（= 文件的父文件夹）",
              frame.row_path(selected) == victim_folder,
              "选中 …%s vs 期望 …%s" % (frame.row_path(selected)[-28:], victim_folder[-28:]))
        check("③ 真双击文件后：那条被上成**高亮蓝**",
              highlight in colours, "上色 = %s" % colours)

        # ══ 阳性对照：「打开」按钮 ═══════════════════════════════════
        print("\n══ 阳性对照：「打开」按钮")
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        tree.SetFocus()
        frame._focus_pane = "tree"
        pump(15)
        fresh_folder = os.path.join(scratch, "brand-new-folder")
        os.makedirs(fresh_folder, exist_ok=True)
        tree.expand_to(fresh_folder, select=True)
        pump(10)
        painter.take()
        frame.on_open(None)
        pump(35)

        sel_b = ctrl.GetFirstSelected()
        colours_b = [c for r, c in painter.take() if r == sel_b]
        print("   焦点 = %s  选中 = %s  上色 = %s" % (focus_name(), sel_b, colours_b))
        check("④ 阳性对照：「打开」按钮那条路仍然正常（焦点+上色）",
              focus_name() == "ListCtrl" and highlight in colours_b,
              "焦点=%s 上色=%s" % (focus_name(), colours_b))
    finally:
        painter.stop()
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
