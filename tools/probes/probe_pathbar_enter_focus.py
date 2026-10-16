"""验：**地址栏输入路径 + 回车**之后，焦点与选中是否和「打开」按钮一致。

## 用户报的（2026-10-17，双击那条修好之后）

> "现在**输入路径回车也是这个问题**，一并修了"

## 为什么必须发**真的回车事件**

上一轮我在"双击树里的文件"上栽过一次：探针直接调处理函数 ⇒ 全绿，
而用户说没修好 —— 因为那个函数**根本没被调用**。

所以本探针**不调 `on_path_submitted`**，而是：
`SetValue` → `SetFocus` → **`AddPendingEvent(wx.EVT_TEXT_ENTER)`**
（与 `wx.TE_PROCESS_ENTER` 控件的真实回车走同一条链）。

## 判据

| # | 判据 |
|---|---|
| ① | 回车后**焦点到了记录列表** |
| ② | 记录列表里选中了刚记录的那个文件夹 |
| ③ | 那条被上成高亮蓝 |
| ④ | 阳性对照：「打开」按钮那条路仍然正常 |
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


class Painter:
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


with probe_temp("probe-pathbar") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    # 一个**真实存在**、但列表里还没有的文件夹
    target = os.path.join(scratch, "entered-folder")
    os.makedirs(target, exist_ok=True)

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    bar = frame.path_bar
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    painter = Painter(ctrl)
    print("系统高亮 = %s" % highlight)
    print("要回车的路径 = %s" % target)

    try:
        # ── 真实的回车事件 ──────────────────────────────────────
        ctrl.SetFocus()                  # 先让焦点在记录列表（模拟"刚在右边操作过"）
        frame._focus_pane = "list"       # **最坏情况**：残留值是 list
        pump(20)
        painter.take()
        before = ctrl.GetItemCount()

        print("\n【回车前】焦点=%s  _focus_pane=%r  列表行数=%d"
              % (focus_name(), frame._focus_pane, before))

        bar.text_ctrl.SetValue(target)
        bar.text_ctrl.SetFocus()
        pump(10)
        enter = wx.CommandEvent(wx.EVT_TEXT_ENTER.typeId, bar.text_ctrl.GetId())
        enter.SetEventObject(bar.text_ctrl)
        bar.text_ctrl.AddPendingEvent(enter)
        pump(45)

        selected = ctrl.GetFirstSelected()
        colours = [c for r, c in painter.take() if r == selected]
        print("\n【回车后】")
        print("   焦点 = %s" % focus_name())
        print("   _focus_pane = %r" % frame._focus_pane)
        print("   列表行数 = %d（前 %d）" % (ctrl.GetItemCount(), before))
        print("   选中 = %s（…%s）" % (selected, frame.row_path(selected)[-28:]))
        print("   上过的色 = %s" % colours)

        check("① 地址栏回车后：**焦点转移到记录列表**",
              focus_name() == "ListCtrl", "焦点 = %s" % focus_name())
        check("② 地址栏回车后：选中了刚记录的那个文件夹",
              frame.row_path(selected) == target,
              "选中 …%s vs 期望 …%s" % (frame.row_path(selected)[-28:], target[-28:]))
        check("③ 地址栏回车后：那条被上成**高亮蓝**",
              highlight in colours, "上色 = %s" % colours)

        # ── 阳性对照：「打开」按钮 ──────────────────────────────
        print("\n══ 阳性对照：「打开」按钮")
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        tree = frame.dir_ctrl.GetTreeCtrl()
        tree.SetFocus()
        frame._focus_pane = "tree"
        pump(15)
        fresh = os.path.join(scratch, "brand-new-folder")
        os.makedirs(fresh, exist_ok=True)
        tree.expand_to(fresh, select=True)
        pump(10)
        painter.take()
        frame.on_open(None)
        pump(35)
        sel_b = ctrl.GetFirstSelected()
        colours_b = [c for r, c in painter.take() if r == sel_b]
        print("   焦点 = %s  选中 = %s  上色 = %s" % (focus_name(), sel_b, colours_b))
        check("④ 阳性对照：「打开」按钮仍然正常",
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
