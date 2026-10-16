"""验：从导航窗格打开后，那条记录的**行底色**是不是系统高亮色（蓝）。

## 判据（可回读，不靠抓屏）

这个项目的选中蓝是**自己设的行底色**（`SetItemBackgroundColour`），
所以可以直接 `GetItemBackgroundColour(index)` 读回来比 ——
**不需要像素取样**（本环境抓屏不可靠，见 `tools/probes/README.md`）。

* 从**导航窗格**打开 ⇒ 那条记录的行底色 = 系统高亮色
* 从**记录列表**双击 ⇒ 同样
* 其余行仍是 `card` 底色
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


def settle(times: int = 25) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def hex_of(colour) -> str:
    return f"#{colour.Red():02X}{colour.Green():02X}{colour.Blue():02X}"


with probe_temp("probe-blue-row") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    newone = os.path.join(scratch, "opened-from-tree")
    os.makedirs(newone, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(50)
    ctrl = frame.list_ctrl

    highlight = hex_of(
        wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT))
    print(f"  系统高亮色 = {highlight}")
    print()

    # ── 从导航窗格打开 ──
    frame._focus_pane = "tree"
    frame.record_accessed_path(newone)
    settle(40)

    sel = ctrl.GetFirstSelected()
    sel_path = frame._rows[sel].path if 0 <= sel < len(frame._rows) else "?"
    if sel >= 0:
        got = hex_of(ctrl.GetItemBackgroundColour(sel))
    else:
        got = "（没有选中）"

    print(f"  从导航窗格打开之后：")
    print(f"    选中行 = {sel}（…{sel_path[-26:]}）")
    print(f"    该行底色 = **{got}**")
    results.append(("① 选中状态是那条新记录", sel_path == newone,
                    f"…{sel_path[-26:]}"))
    results.append(("② 该行底色 = 系统高亮色（**是蓝的**）",
                    got == highlight, f"{got} vs {highlight}"))

    # 对照：未选中的行应当不是高亮色
    other = sel + 2 if sel + 2 < ctrl.GetItemCount() else 0
    other_colour = hex_of(ctrl.GetItemBackgroundColour(other))
    results.append(("③ 对照：未选中行**不是**高亮色",
                    other_colour != highlight,
                    f"第 {other} 行 = {other_colour}"))

    # ── 从记录列表双击（已验收过的行为，不能被碰坏）──
    row = 5
    for i in range(ctrl.GetItemCount()):
        if i != row:
            ctrl.Select(i, False)
    ctrl.SetItemState(row, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    settle()
    picked = frame._rows[row].path
    frame._focus_pane = "list"
    frame.record_accessed_path(picked)
    settle(40)

    sel2 = ctrl.GetFirstSelected()
    got2 = hex_of(ctrl.GetItemBackgroundColour(sel2)) if sel2 >= 0 else "?"
    results.append(("④ 从记录列表双击 ⇒ **仍然**是蓝色（没被改坏）",
                    got2 == highlight, f"{got2}"))

    frame.store.close()
    frame.Destroy()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
