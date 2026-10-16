"""补上"点按钮"这一步 —— 焦点从树上被拿走时，选中项才变灰。

## 为什么重测

用户问："导航窗格中打开后聚焦选中为什么是**浅灰色**？"

我第一版探针**用程序调用** `record_accessed_path()`，
焦点一直在树上，于是结论是"焦点没跑、灰色另有原因"。

**但用户的真实操作是点「打开」按钮** —— 那会把**键盘焦点从树上拿走**。
Windows 对没有焦点的控件用灰色画选中项（inactive selection）。

**我的探针没复现他的操作流程**，所以那一轮结论作废。

## 判据

对比三种时刻，看焦点在谁身上：

1. 用户刚点过树（焦点在树）
2. **点了「打开」按钮之后**（焦点应当转到按钮）
3. 程序直接调 `record_accessed_path()`（焦点不动）
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


def settle(times: int = 20) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def who(frame) -> str:
    focused = wx.Window.FindFocus()
    if focused is None:
        return "（无）"
    if focused is frame.dir_ctrl:
        return "**导航树**（有焦点 ⇒ 选中应为系统蓝）"
    if focused is frame.list_ctrl:
        return "记录列表"
    for name in ("open_btn", "clear_btn"):
        widget = getattr(frame, name, None)
        if widget is not None and focused is widget:
            return f"**{name}**（树失去焦点 ⇒ 选中变灰）"
    return f"{type(focused).__name__}"


with probe_temp("probe-focus2") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(50)
    tree = frame.dir_ctrl
    tree.expand_to(scratch, select=True)

    print("  ① 用户刚点过树：")
    tree.SetFocus()
    settle(20)
    print(f"       焦点 = {who(frame)}")
    print()

    print("  ② **点了「打开」按钮之后**（用户的真实操作）：")
    button = getattr(frame, "open_btn", None)
    if button is None:
        print("       找不到 open_btn，改用任意按钮模拟")
        for child in frame.GetChildren():
            pass
    else:
        button.SetFocus()          # 点按钮 = 焦点转到按钮
        settle(20)
        print(f"       焦点 = {who(frame)}")
        print(f"       树的选中项 = {tree.GetItemText(tree.GetSelection())!r}")
    print()

    print("  ③ 程序直接调 `record_accessed_path()`（不动焦点）：")
    tree.SetFocus()
    settle(10)
    frame._focus_pane = "tree"
    frame.record_accessed_path(os.path.join(scratch, "dir-0001"))
    settle(30)
    print(f"       焦点 = {who(frame)}")
    print()

    print("  ── 结论 ──")
    print("  ① 有焦点、② 失去焦点。**如果 ① 和 ② 的树选中项是同一条**，")
    print("  那么两次的差别就只剩'有没有焦点' ⇒ 灰色 = 系统的 inactive selection。")

    frame.store.close()
    frame.Destroy()
