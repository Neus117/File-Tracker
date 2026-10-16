"""把探针改成**新旧对比**：同一个场景分别跑 `Focus()` 与 `SetItemState()`。

## 为什么要改

原探针在 ③ 里跑的是**它自己写死的旧序列**（`ctrl.Focus(...)`），
所以修复之后它**仍然显示 top=262** —— 那是在复现 bug，不是在验证修复。

**"复现"和"验证"是两件事**，探针必须能同时做这两件，
否则改完之后你不知道到底修好没有。

## 判据

同一场景、同一选中项、同一视角锚点，各跑一次：

* 用 `Focus()`        → 期望 top **离开** 锚点（bug）
* 用 `SetItemState()` → 期望 top **停在** 锚点（修复）
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
from file_tracker import lang

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

COUNT = 300


def settle(times: int = 20) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()


def run_case(frame, use_focus: bool) -> tuple:
    """重建 → 全清 → 选同一条（分别用两种方式）→ 回位。返回终态。"""
    ctrl = frame.list_ctrl
    anchor_path = frame._rows[ctrl.GetTopItem()].path
    selected_path = frame._rows[ctrl.GetFirstSelected()].path

    ctrl.DeleteAllItems()
    for record in frame._rows:
        ctrl.InsertItem(ctrl.GetItemCount(), record.path)
    settle()

    sel_index = frame._index_of_path(selected_path)
    for i in range(ctrl.GetItemCount()):
        if i != sel_index:
            ctrl.Select(i, False)

    if use_focus:
        ctrl.Select(sel_index, True)
        ctrl.Focus(sel_index)                       # ← 旧做法
    else:
        ctrl.SetItemState(                           # ← 新做法
            sel_index,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    after_select = ctrl.GetTopItem()
    settle()

    anchor_index = frame._index_of_path(anchor_path)
    delta = anchor_index - ctrl.GetTopItem()
    if delta:
        ctrl.ScrollLines(delta)
    settle()
    return anchor_index, after_select, ctrl.GetTopItem(), ctrl.GetFirstSelected()


with probe_temp("probe-scroll-anchor") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(60)
    ctrl = frame.list_ctrl

    for use_focus in (True, False):
        # 每次都回到同一个初始状态：滚到靠下 + 选中更下面的一条
        target = COUNT - 40
        ctrl.EnsureVisible(target)
        ctrl.ScrollLines(target - ctrl.GetTopItem())
        settle()
        far = min(target + 25, COUNT - 1)
        for i in range(COUNT):
            if i != far:
                ctrl.Select(i, False)
        ctrl.Select(far, True)
        settle()

        anchor_index, after_select, final_top, final_sel = run_case(frame, use_focus)
        label = "Focus()（旧）" if use_focus else "SetItemState()（新）"
        print(f"  ── {label} ──")
        print(f"    锚点行号 = {anchor_index}")
        print(f"    设完选中之后顶行 = {after_select}"
              f"{'   ← **被滚走了**' if after_select != 0 and after_select != anchor_index else ''}")
        print(f"    回位之后顶行     = {final_top}"
              f"{'   ✅ 停在锚点' if final_top == anchor_index else '   ❌ 没回到锚点'}")
        print(f"    选中行 = {final_sel}"
              f"{'   ✅' if final_sel == anchor_index + 25 else ''}")
        print()

    frame.store.close()
    frame.Destroy()
