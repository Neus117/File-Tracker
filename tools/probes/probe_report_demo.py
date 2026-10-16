"""端到端：**照用户的操作方式**跑一次诊断，看报告到底长什么样。

和 `probe_paint_tracer.py` 的区别：这个不检查"装没装上"，
而是**把报告打印出来给人读** —— 用户跑一次拿到的就是这份东西。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang, paint_trace

# **两个开关一起开**（用户的用法）
os.environ[paint_trace.ENV_FOCUS_FLAG] = "1"
os.environ[paint_trace.ENV_FLAG] = "1"

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)


def pump(rounds: int = 25) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)


with probe_temp("probe-report") as scratch:
    db = os.path.join(scratch, "p.db")
    report = os.path.join(scratch, "paint-trace.txt")
    paint_trace.report_path = lambda: report
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"m{i:03d}"))
    fresh = os.path.join(scratch, "m020-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(50)

    # —— 用户的操作：在导航窗格里选中，然后按「打开」——
    ctrl = frame.list_ctrl
    mid = max(ctrl.GetItemCount() // 3, 1)
    ctrl.EnsureVisible(mid)
    ctrl.ScrollLines(mid - ctrl.GetTopItem())
    for i in range(ctrl.GetItemCount()):
        ctrl.Select(i, False)
    ctrl.SetItemState(mid, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    tree = frame.dir_ctrl.GetTreeCtrl()
    tree.expand_to(fresh, select=True)
    frame._focus_pane = "tree"
    pump(12)

    print("\n########## 控制台输出（记录 + 焦点诊断）##########\n")
    frame.on_open(None)
    pump(35)

    print("\n########## 关窗时落盘的报告 ##########\n")
    frame.on_close(wx.PyCommandEvent(wx.EVT_CLOSE.typeId, frame.GetId()))
    pump(10)

    try:
        frame.store.close()
    except Exception:
        pass
    try:
        frame.Destroy()
    except Exception:
        pass
    pump(5)
