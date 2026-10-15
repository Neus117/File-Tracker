"""诊断：为什么 adjust_column_widths 在一次操作里被调 5 次。

`probe_rebuild_cost.py` 量到 `_render_rows` 已经从 2 次降到 1 次，
但 `adjust_column_widths` 仍是 **5** 次。那多半是**重入**：
它内部 `SetColumnWidth` 会改变列表内容宽度 → 触发 `EVT_SIZE`
（或 `_on_list_resized`）→ 又调回自己。

这个探针把调用栈打出来，确认是不是重入，而不是猜。
"""
import ctypes
import os
import sys
import time
import traceback

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

with probe_temp("probe-reentry") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(120):
        seed.record_access(os.path.join(scratch, f"f-{i:04d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    calls = []
    real = frame.adjust_column_widths
    depth = {"n": 0}

    def traced(*a, **k):
        depth["n"] += 1
        stack = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
                 for f in traceback.extract_stack()[:-1] if "file_tracker" in f.filename]
        calls.append(stack[-3:])
        try:
            return real(*a, **k)
        finally:
            depth["n"] -= 1

    frame.adjust_column_widths = traced
    calls.clear()
    frame.record_accessed_path(os.path.join(scratch, "f-0005"))
    for _ in range(30):
        wx.YieldIfNeeded()

    print(f"  adjust_column_widths 被调 {len(calls)} 次，调用链：")
    for index, stack in enumerate(calls, 1):
        print(f"    {index}. " + "  ←  ".join(reversed(stack)))
    print()
    if any("adjust_column_widths" in " ".join(s) for s in calls[1:]):
        print("  → **确认是重入**：它自己触发了再次进入。")
    else:
        print("  → 不是重入；是别处各调了一次（看上面的调用链）。")
    frame.store.close()
    frame.Destroy()
