"""验：从导航窗格打开之后，焦点**回到树上**（于是原生选中显系统蓝）。

## 复现用户的真实序列

1. 用户先点过树（焦点在树）
2. 点「打开」按钮（**焦点转到按钮** —— 这是灰色的成因）
3. 打开动作跑完 → **焦点应当回到树**

## 判据

第 3 步之后 `wx.Window.FindFocus()` 应当是 `frame.dir_ctrl`。

**阴性对照**：从**记录列表**发起时，焦点**不该**被抢到树上。
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

results = []


def settle(times: int = 20) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def name_of_focus(frame) -> str:
    focused = wx.Window.FindFocus()
    if focused is None:
        return "（无）"
    if focused is frame.dir_ctrl:
        return "导航树"
    if focused is frame.list_ctrl:
        return "记录列表"
    if focused is getattr(frame, "open_btn", None):
        return "「打开」按钮"
    return type(focused).__name__


with probe_temp("probe-focus3") as scratch:
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

    # ── 用户序列：点树 → 点「打开」 → 打开动作 ──
    tree.SetFocus()
    settle(15)
    frame.open_btn.SetFocus()                 # 模拟"点了「打开」按钮"
    settle(15)
    before = name_of_focus(frame)

    frame._focus_pane = "tree"
    frame.record_accessed_path(os.path.join(scratch, "dir-0001"))
    settle(30)
    after = name_of_focus(frame)

    results.append(("① 点按钮后焦点确实在按钮上（复现灰色成因）",
                    before == "「打开」按钮", f"焦点 = {before}"))
    results.append(("② 从导航窗格打开后，焦点**回到树**（于是显系统蓝）",
                    after == "导航树", f"焦点 = {after}"))

    # ── 阴性对照：从列表发起，不该抢焦点 ──
    frame.list_ctrl.SetFocus()
    settle(15)
    frame._focus_pane = "list"
    frame.record_accessed_path(os.path.join(scratch, "dir-0002"))
    settle(30)
    after2 = name_of_focus(frame)
    results.append(("③ 从记录列表发起时**不抢焦点**（阴性对照）",
                    after2 != "导航树", f"焦点 = {after2}"))

    frame.store.close()
    frame.Destroy()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
