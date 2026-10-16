"""重放**真实的双击流程**，看锚点与选中到底在哪一步错掉。

## 用户给的两张截图说明

* 双击**生效了**：`D:\\Program Files` 的频次 4 → 5、时间也更新了
* **但选中跑到了 `D:\\Work\\Hobbies\\Prism logo`**（比它低 9 行）

## 已知

`on_open` / `on_dir_item_activated` / `on_open_selected` 三个入口
都走 `record_accessed_path()`，而它里面**确实**调了 `_remember_view()`。
所以不是"漏了调用" —— **必须逐步量**。

## 判据

在**每一次** `_remember_view()` 与 `_render_rows()` 处记录：

* 那一刻的 `GetFirstSelected()` / `GetTopItem()`
* 记下的锚点路径、选中路径
* 重建之后它们落在第几行

**把"我以为的"和"实际发生的"并排打出来。**
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


def settle(times: int = 25) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.005)


with probe_temp("probe-open-anchor") as scratch:
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

    # **插桩**：把 `_remember_view` 与 `_render_rows` 包起来，记录每一步
    log: list[str] = []
    orig_remember = frame._remember_view
    orig_render = frame._render_rows

    def spy_remember():
        before_sel = ctrl.GetFirstSelected()
        before_top = ctrl.GetTopItem()
        before_path = (frame._rows[before_sel].path
                       if 0 <= before_sel < len(frame._rows) else "?")
        orig_remember()
        got = getattr(frame, "_view_anchor", None)
        log.append(f"  `_remember_view()` 被调用")
        log.append(f"     当时 GetFirstSelected() = {before_sel}"
                   f"（…{before_path[-24:]}）")
        log.append(f"     当时 GetTopItem()       = {before_top}"
                   f"（…{frame._rows[before_top].path[-24:] if 0 <= before_top < len(frame._rows) else '?'}）")
        log.append(f"     记下的锚点/选中 = {got}")
        return got

    def spy_render():
        had = getattr(frame, "_view_anchor", None)
        log.append(f"  `_render_rows()` 开始，_view_anchor = {had}")
        before = (ctrl.GetFirstSelected(), ctrl.GetTopItem())
        orig_render()
        log.append(f"     重建前 (sel, top) = {before}")
        log.append(f"     重建后 (sel, top) = "
                   f"({ctrl.GetFirstSelected()}, {ctrl.GetTopItem()})")

    frame._remember_view = spy_remember
    frame._render_rows = spy_render

    # 滚到靠下、选中靠下的一条（模拟用户双击一条靠下的记录）
    target = COUNT - 40
    ctrl.EnsureVisible(target)
    ctrl.ScrollLines(target - ctrl.GetTopItem())
    settle()
    clicked = target + 9          # 与用户截图里"选中项比顶行低约 9 行"一致
    for i in range(COUNT):
        if i != clicked:
            ctrl.Select(i, False)
    ctrl.SetItemState(clicked,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    settle()

    clicked_path = frame._rows[clicked].path
    top_path = frame._rows[ctrl.GetTopItem()].path
    print(f"  双击的路径   = …{clicked_path[-30:]}")
    print(f"  当时顶行路径 = …{top_path[-30:]}")
    print()
    print("  ── 调用 record_accessed_path（双击就是走它）──")
    frame.record_accessed_path(clicked_path)
    settle(40)

    print()
    for line in log:
        print(line)
    print()
    now_sel = ctrl.GetFirstSelected()
    now_sel_path = (frame._rows[now_sel].path
                    if 0 <= now_sel < len(frame._rows) else "?")
    now_top_path = frame._rows[ctrl.GetTopItem()].path
    print(f"  ── 终态 ──")
    print(f"    选中 = {now_sel}（…{now_sel_path[-30:]}）"
          f"{'   ✅ 就是双击那条' if now_sel_path == clicked_path else '   ❌ **不是双击那条**'}")
    print(f"    顶行 = {ctrl.GetTopItem()}（…{now_top_path[-30:]}）"
          f"{'   ✅ 视角没动' if now_top_path == top_path else '   ❌ 视角动了'}")

    frame.store.close()
    frame.Destroy()
