"""诊断：M3 的性能改动**真的**减少了吗。

判据用**计数**而不是秒表：数出"每记一次访问，列表被清空重建几次、
跨语言原生调用发生几次"。时间在这里不可靠（本机负载、wx 内部缓存），
而调用次数是确定性的、可重复的。

做法：把要害方法包一层计数器，然后模拟一次"打开一条记录"。
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

with probe_temp("probe-perf") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    # 造 500 条记录 —— 够看出 O(N) 与 O(样本) 的差别
    seed = app_mod.PathStore(db)
    for i in range(500):
        seed.record_access(os.path.join(scratch, f"folder-{i:04d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    print(f"  列表行数 = {frame.list_ctrl.GetItemCount()}")

    counters = {"render": 0, "adjust": 0, "getitemtext": 0,
                "gettextextent": 0, "load": 0}

    real_render = frame._render_rows
    real_adjust = frame.adjust_column_widths
    real_load = frame._ordered_records

    def counting_render(*a, **k):
        counters["render"] += 1
        return real_render(*a, **k)

    import traceback as _tb
    _stacks = []

    def counting_adjust(*a, **k):
        # **数"真正做了事"的次数，不是"被进入"的次数。**
        # 加了重入护栏之后，`adjust_column_widths` 仍会被事件打回来几次，
        # 但内层会立刻返回——只数进入次数会把"已经修好了"看成"没修"。
        before = counters["getitemtext"]
        result = real_adjust(*a, **k)
        if counters["getitemtext"] > before:
            counters["adjust"] += 1
            _stacks.append([f"{f.name}:{f.lineno}" for f in
                            _tb.extract_stack()[:-1] if "app.py" in f.filename][-3:])
        return result

    def counting_load(*a, **k):
        counters["load"] += 1
        return real_load(*a, **k)

    frame._render_rows = counting_render
    frame.adjust_column_widths = counting_adjust
    frame._ordered_records = counting_load

    # 再包一层原生的两个热点
    real_git = frame.list_ctrl.GetItemText
    real_gte = frame.list_ctrl.GetTextExtent

    def counting_git(*a, **k):
        counters["getitemtext"] += 1
        return real_git(*a, **k)

    def counting_gte(*a, **k):
        counters["gettextextent"] += 1
        return real_gte(*a, **k)

    frame.list_ctrl.GetItemText = counting_git
    frame.list_ctrl.GetTextExtent = counting_gte

    for key in counters:
        counters[key] = 0

    sw = time.perf_counter()
    frame.record_accessed_path(os.path.join(scratch, "folder-0250"))
    for _ in range(30):
        wx.YieldIfNeeded()
    elapsed = (time.perf_counter() - sw) * 1000

    print()
    print("  一次 record_accessed_path 的代价：")
    print(f"    _render_rows（整表清空重建）次数 = {counters['render']}")
    print(f"    adjust_column_widths 次数        = {counters['adjust']}")
    print(f"    _ordered_records（读库）次数      = {counters['load']}")
    print(f"    GetItemText 原生调用             = {counters['getitemtext']}")
    print(f"    GetTextExtent 原生调用           = {counters['gettextextent']}")
    print(f"    墙钟耗时                         = {elapsed:.0f} ms")
    print("    两次真正做事的调用链：")
    for s in _stacks:
        print("      " + "  <-  ".join(reversed(s)))
    print()
    print("  期望（修好之后）：")
    print("    _render_rows = 1，adjust_column_widths = 1")
    print(f"    GetItemText ≈ 3 列 × {frame.COLUMN_WIDTH_SAMPLE} 采样 = "
          f"{3 * frame.COLUMN_WIDTH_SAMPLE}（与行数无关）")
    print(f"    ⚠️ 列表有 {frame.list_ctrl.GetItemCount()} 行，"
          f"所以 O(N) 的话会是 {3 * frame.list_ctrl.GetItemCount()}")

    frame.store.close()
    frame.Destroy()
