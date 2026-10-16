"""量：`_select_path_after_render` 到底有没有被消费、被消费在哪一次。

## 已知

* ① 通过（视角不动）⇒ `_focus_pane == "tree"` 那个分支**执行了**
* ② 失败（选中没换到新记录）

⇒ 分支跑了，但"覆盖选中"没生效。**两种可能**：

1. `_select_path_after_render` 被**更早的一次** `_render_rows()` 消费掉了
   （那时新记录还不在 `_rows` 里 ⇒ 找不到下标 ⇒ 静默不换）
2. 它**根本没被设置**（比如属性名写错、或 `sort_list_items` 用了别的入口）

**打点看每一次 `_render_rows()` 时的状态即可分辨。**
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

COUNT = 120
log: list[str] = []

with probe_temp("probe-override") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    fresh = os.path.join(scratch, "brand-new-target")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    for _ in range(50):
        wx.YieldIfNeeded()
        time.sleep(0.005)
    ctrl = frame.list_ctrl

    # ── 插桩 ──
    original_render = frame._render_rows

    def spy_render():
        override = getattr(frame, "_select_path_after_render", None)
        sel_before = ctrl.GetFirstSelected()
        log.append(
            f"  `_render_rows()` 第 {len(log) + 1} 次")
        log.append(f"    进入时 _select_path_after_render = "
                   f"{'（已设置）' if override else 'None'}")
        log.append(f"    进入时 _focus_pane = {getattr(frame, '_focus_pane', '?')!r}")
        log.append(f"    进入时 _rows 里有 fresh 吗 = "
                   f"{any(r.path == fresh for r in frame._rows)}")
        original_render()
        log.append(f"    结束后 选中 = {ctrl.GetFirstSelected()}")
        return None

    frame._render_rows = spy_render

    # 摆好位置
    top = COUNT - 35
    ctrl.EnsureVisible(top)
    ctrl.ScrollLines(top - ctrl.GetTopItem())
    other = top + 3
    for i in range(COUNT):
        if i != other:
            ctrl.Select(i, False)
    ctrl.SetItemState(other, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    for _ in range(15):
        wx.YieldIfNeeded()

    print(f"  fresh = …{fresh[-28:]}")
    print(f"  打开前 顶行 = {ctrl.GetTopItem()}  选中 = {ctrl.GetFirstSelected()}")
    print()
    log.clear()
    frame._focus_pane = "tree"
    frame.record_accessed_path(fresh)
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.005)

    for line in log:
        print(line)

    sel = ctrl.GetFirstSelected()
    sel_path = frame._rows[sel].path if 0 <= sel < len(frame._rows) else "?"
    fresh_row = next((i for i, r in enumerate(frame._rows)
                      if r.path == fresh), -1)
    print()
    print(f"  fresh 在 _rows 里的行号 = {fresh_row}")
    print(f"  最终选中 = {sel}（…{sel_path[-26:]}）")
    print(f"  最终顶行 = {ctrl.GetTopItem()}")

    frame.store.close()
    frame.Destroy()
