"""把"一次重建"拆开，看时间花在哪一段。

`probe_scale_cost.py` 量到 6000 行时一次重建要 1.9 秒。但这个数字
**不能直接用来决策**：它可能花在

* 读库（`load_unpinned` 取出全部行）
* 逐行 `InsertItem` + `SetItem`（跨语言原生调用）
* 逐行设颜色 / 字体（`SetItemBackgroundColour` 等）
* 量列宽（**已有 200 行采样上限，与规模无关**）
* 排序（Python 侧）

修法完全不同，所以先把秒表分段。
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

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

SIZE = 6000

with probe_temp("probe-profile") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(SIZE):
        seed.record_access(os.path.join(scratch, f"folder-{i:05d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)
    print(f"  列表 {frame.list_ctrl.GetItemCount()} 行")
    print()

    # 给每一段包一个秒表
    spans: dict[str, float] = {}
    counts: dict[str, int] = {}

    def timed(name, real):
        def wrapper(*a, **k):
            sw = time.perf_counter()
            try:
                return real(*a, **k)
            finally:
                spans[name] = spans.get(name, 0.0) + (time.perf_counter() - sw) * 1000
                counts[name] = counts.get(name, 0) + 1
        return wrapper

    real_load = frame.store.load_unpinned
    frame.store.load_unpinned = timed("读库 load_unpinned", real_load)
    real_pinned = frame.store.load_pinned
    frame.store.load_pinned = timed("读库 load_pinned", real_pinned)
    real_render = frame._render_rows
    frame._render_rows = timed("_render_rows 整体", real_render)
    real_adjust = frame._adjust_column_widths
    frame._adjust_column_widths = timed("量列宽 _adjust_column_widths", real_adjust)
    real_center = frame.center_frequency_column
    frame.center_frequency_column = timed("频次列居中", real_center)
    real_sync = frame._sync_header
    frame._sync_header = timed("表头同步", real_sync)

    # `InsertItem` / `SetItem` 是真正的热点，单独数次数与时间
    real_insert = frame.list_ctrl.InsertItem
    real_setitem = frame.list_ctrl.SetItem
    real_bg = frame.list_ctrl.SetItemBackgroundColour
    real_fg = frame.list_ctrl.SetItemTextColour
    frame.list_ctrl.InsertItem = timed("InsertItem", real_insert)
    frame.list_ctrl.SetItem = timed("SetItem", real_setitem)
    frame.list_ctrl.SetItemBackgroundColour = timed("SetItemBackgroundColour", real_bg)
    frame.list_ctrl.SetItemTextColour = timed("SetItemTextColour", real_fg)

    for key in list(spans):
        spans[key] = 0.0
        counts[key] = 0

    sw = time.perf_counter()
    frame.record_accessed_path(os.path.join(scratch, "folder-00007"))
    for _ in range(20):
        wx.YieldIfNeeded()
    total = (time.perf_counter() - sw) * 1000

    print(f"  一次 record_accessed_path 总计 = {total:.0f} ms")
    print()
    print(f"  {'分段':34} {'耗时':>10} {'调用次数':>10}")
    print("  " + "-" * 58)
    for key in sorted(spans, key=lambda k: -spans[k]):
        print(f"  {key:34} {spans[key]:8.0f} ms {counts[key]:10}")
    print()
    print("  ⚠️ 分段之间会**重叠**（`_render_rows 整体` 里包含 InsertItem/SetItem），")
    print("     所以不要把它们相加；看的是**哪一项最贵**。")

    frame.store.close()
    frame.Destroy()
