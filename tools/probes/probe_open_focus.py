"""诊断：「打开」为什么不跟着记录窗格的选中（**真实鼠标事件版**）。

上一版探针用 `list_ctrl.Select(0)` —— 那是**程序化**选中，事件顺序与
用户真的用鼠标点不一样。用户报的问题只在真实点击下出现，所以这里
合成真实的 `wx.MouseEvent`，并把**所有相关事件**按发生顺序打出来。

要看的是：点列表之后，**还有没有别的事件把 `_focus_pane` 改回 tree**。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App()
lang.apply(lang.PREFERENCE_CHINESE)

with probe_temp("probe-click") as scratch:
    db = os.path.join(scratch, "p.db")
    cfg = os.path.join(scratch, "config.json")
    seed = app_mod.PathStore(db)
    for name in ("alpha", "beta", "gamma"):
        seed.record_access(os.path.join(scratch, name))
    seed.close()
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: cfg

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    log = []

    def note(what):
        log.append((what, frame._focus_pane))
        print(f"    {what:34} → _focus_pane = {frame._focus_pane!r}")

    # ---- 记录所有相关事件 ----
    tree = frame.dir_ctrl.GetTreeCtrl()
    frame.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED,
                         lambda e: (note("列表 ITEM_SELECTED"), e.Skip()))
    frame.list_ctrl.Bind(wx.EVT_LEFT_DOWN,
                         lambda e: (note("列表 LEFT_DOWN"), e.Skip()))
    frame.list_ctrl.Bind(wx.EVT_SET_FOCUS,
                         lambda e: (note("列表 SET_FOCUS"), e.Skip()))
    frame.list_ctrl.Bind(wx.EVT_KILL_FOCUS,
                         lambda e: (note("列表 KILL_FOCUS"), e.Skip()))
    tree.Bind(wx.EVT_TREE_SEL_CHANGED,
              lambda e: (note("树 SEL_CHANGED"), e.Skip()))
    tree.Bind(wx.EVT_LEFT_DOWN,
              lambda e: (note("树 LEFT_DOWN"), e.Skip()))
    tree.Bind(wx.EVT_SET_FOCUS,
              lambda e: (note("树 SET_FOCUS"), e.Skip()))
    tree.Bind(wx.EVT_KILL_FOCUS,
              lambda e: (note("树 KILL_FOCUS"), e.Skip()))

    def click(win, pos):
        """合成一次真实的左键按下+抬起。"""
        for kind in (wx.wxEVT_LEFT_DOWN, wx.wxEVT_LEFT_UP):
            event = wx.MouseEvent(kind)
            event.SetPosition(pos)
            event.SetEventObject(win)
            win.GetEventHandler().ProcessEvent(event)
        for _ in range(20):
            wx.YieldIfNeeded()
            time.sleep(0.005)

    print(f"  启动后 _focus_pane = {frame._focus_pane!r}")
    print()
    print("  ── ① 真实点击列表第 1 行 ──")
    log.clear()
    rect = frame.list_ctrl.GetItemRect(1)
    click(frame.list_ctrl, (rect.x + 30, rect.y + rect.height // 2))
    print(f"  点完 _focus_pane = {frame._focus_pane!r}")
    print(f"  列表选中 = {frame.selected_path()[-26:]!r}")
    print(f"  open_targets() = {[p[-26:] for p in frame.open_targets()]}")
    print()

    print("  ── ② 真实点击导航窗格里的树 ──")
    log.clear()
    root = tree.GetRootItem()
    click(tree, (30, 10))
    print(f"  点完 _focus_pane = {frame._focus_pane!r}")
    print(f"  导航选中 = {[p[-26:] for p in frame.dir_ctrl.GetPaths()]}")
    print(f"  open_targets() = {[p[-26:] for p in frame.open_targets()]}")
    print()

    print("  ── ③ 再真实点击列表第 2 行（复现用户的操作）──")
    log.clear()
    rect = frame.list_ctrl.GetItemRect(2)
    click(frame.list_ctrl, (rect.x + 30, rect.y + rect.height // 2))
    print(f"  点完 _focus_pane = {frame._focus_pane!r}")
    print(f"  列表选中 = {frame.selected_path()[-26:]!r}")
    print(f"  导航选中 = {[p[-26:] for p in frame.dir_ctrl.GetPaths()]}")
    print(f"  open_targets() = {[p[-26:] for p in frame.open_targets()]}")
    print(f"    ← 期望是列表第 2 行")

    frame.store.close()
    frame.Destroy()
