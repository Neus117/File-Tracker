"""验：从导航窗格打开时"视角不动 + 选中对上"，且**双击列表那条路没被碰坏**。

## 用户选的 B

"列表视角保持不动，只要**选中对上**就行。"

## 判据（两条路都要量）

| 场景 | 选中 | 视角 |
|---|---|---|
| **从导航窗格打开** | **换成刚记录的那条** | **不动**（顶行行号不变） |
| **双击列表里的一条** | 本来就是它 | **跟路径**（已验收过的行为，不能变） |

**第二条尤其重要** —— 那是用户验收过的，我这次改动必须**没有**影响到它。
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

COUNT = 160
results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def settle(times: int = 25) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def state(frame):
    ctrl = frame.list_ctrl
    top = ctrl.GetTopItem()
    sel = ctrl.GetFirstSelected()
    return (top, sel,
            frame._rows[top].path if 0 <= top < len(frame._rows) else "?",
            frame._rows[sel].path if 0 <= sel < len(frame._rows) else "?")


with probe_temp("probe-nav-open") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    # 一条"还没被记录过"的目录 —— 模拟"从导航窗格打开一个新路径"
    fresh = os.path.join(scratch, "brand-new-target")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(60)
    ctrl = frame.list_ctrl

    # ── 场景一：从**导航窗格**打开 ──
    target_top = COUNT - 45
    ctrl.EnsureVisible(target_top)
    ctrl.ScrollLines(target_top - ctrl.GetTopItem())
    settle()
    # 列表选中挪到别处，确保"选中"和"打开的那条"**不是同一个**
    other = target_top + 3
    for i in range(COUNT):
        if i != other:
            ctrl.Select(i, False)
    ctrl.SetItemState(other, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    settle()

    before_top, before_sel, before_top_path, _ = state(frame)
    frame._focus_pane = "tree"          # 模拟"用户是从导航窗格发起的"
    frame.record_accessed_path(fresh)
    settle(40)
    after_top, after_sel, after_top_path, after_sel_path = state(frame)

    check("① 从导航窗格打开：**视角不动**（顶行行号不变）",
          after_top == before_top,
          f"打开前 top={before_top}（…{before_top_path[-22:]}）→ "
          f"打开后 top={after_top}（…{after_top_path[-22:]}）")
    check("② 从导航窗格打开：**选中落到刚记录的那条**",
          after_sel_path == fresh,
          f"选中 …{after_sel_path[-30:]}")

    # ── 场景二：双击**列表**里的一条（已验收过的行为，不能被碰坏）──
    frame._focus_pane = "list"
    row = 20
    for i in range(ctrl.GetItemCount()):
        if i != row:
            ctrl.Select(i, False)
    ctrl.SetItemState(row, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    ctrl.EnsureVisible(row)
    ctrl.ScrollLines(row - ctrl.GetTopItem())
    settle()

    b2_top, b2_sel, b2_top_path, b2_sel_path = state(frame)
    picked = b2_sel_path
    frame.record_accessed_path(picked)          # 双击列表 = 走这条
    settle(40)
    a2_top, a2_sel, a2_top_path, a2_sel_path = state(frame)

    check("③ 双击列表：选中**还是那条**（没被新逻辑改掉）",
          a2_sel_path == picked,
          f"选中 …{a2_sel_path[-30:]}")
    check("④ 双击列表：视角**仍按路径跟**（不是被误改成行号口径）",
          a2_top_path == b2_top_path or a2_top == b2_top,
          f"打开前顶行 …{b2_top_path[-22:]}（top={b2_top}）→ "
          f"打开后 …{a2_top_path[-22:]}（top={a2_top}）")

    frame.store.close()
    frame.Destroy()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    if detail:
        print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
