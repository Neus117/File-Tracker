r"""性能细分：把"整表重建"内部**逐项**量出来，找出真正的调用热点。

## 为什么需要细分

`probe_perf_baseline.py` 给出的是"一个操作多久"，但重建占了每次操作的大头。
6000 行重建 ~1195ms 已经知道**瓶颈在原生调用**，但"具体是哪种调用、
各占多少、能不能减少次数"没量过 —— 而**优化只能从"减少调用次数"入手**。

## 量什么

* 每种原生调用（`InsertItem` / `SetItem` / `SetItemBackgroundColour` /
  `SetItemTextColour`）的**次数**与**总耗时**
* 拖拽的**两种真实姿态**分开量：
  * "逐行拖"（每帧只多一行）—— 用户慢慢拖的常态
  * "跳着拖"（一帧跨一大段）—— 快速划过
* 删除路径里"清选中"那一步单独量（看它值不值得省）
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

SIZE = 6000
if "--size" in sys.argv:
    SIZE = int(sys.argv[sys.argv.index("--size") + 1])

calls: dict[str, list[float]] = {}


def instrument(ctrl) -> dict:
    """包住列表控件的写操作，统计**次数**与**总耗时**。"""
    stat: dict[str, list[float]] = {}
    originals = {}
    for name in ("InsertItem", "SetItem", "SetItemBackgroundColour",
                 "SetItemTextColour", "SetItemState", "Select", "DeleteAllItems",
                 "GetColumnWidth", "GetTextExtent", "Refresh"):
        original = getattr(ctrl, name, None)
        if original is None:
            continue
        originals[name] = original

        def make(name=name, original=original):
            def wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    stat.setdefault(name, []).append(time.perf_counter() - start)
            wrapper.__name__ = name
            return wrapper

        setattr(ctrl, name, make())
    return {"stat": stat, "originals": originals}


def restore(ctrl, bundle) -> None:
    for name, original in bundle["originals"].items():
        setattr(ctrl, name, original)


def report(stat, label: str) -> None:
    print("\n── %s ──" % label)
    items = sorted(stat.items(), key=lambda kv: -sum(kv[1]))
    total = sum(sum(v) for v in stat.values())
    print("  %-26s %8s %12s %10s" % ("调用", "次数", "总耗时(ms)", "占比"))
    for name, times in items:
        spent = sum(times) * 1000
        share = spent / (total * 1000) * 100 if total else 0
        print("  %-26s %8d %12.1f %9.1f%%"
              % (name, len(times), spent, share))
    print("  %-26s %8s %12.1f" % ("合计", "", total * 1000))


with probe_temp("probe-perf-detail") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    for _ in range(40):
        wx.YieldIfNeeded()
    ctrl = frame.list_ctrl

    try:
        for i in range(SIZE):
            frame.store.record_access(os.path.join(scratch, "s%05d" % i))

        # ══ 1. 重建的内部构成 ═══════════════════════════════════
        bundle = instrument(ctrl)
        start = time.perf_counter()
        frame._rows = frame._ordered_records()
        frame._render_rows()
        elapsed = (time.perf_counter() - start) * 1000
        stat = bundle["stat"]
        restore(ctrl, bundle)
        print("整表重建 %d 行：总计 %.1f ms（含未插桩部分）" % (SIZE, elapsed))
        report(stat, "重建期间的控件调用")

        # ══ 2. 拖拽两种姿态 ═════════════════════════════════════
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        wx.YieldIfNeeded()

        # 2a. 逐行拖：每帧只多一行（**用户慢慢拖的常态**）
        #
        # 帧数按规模走：6000 行跑 200 帧要几十秒，探针会假死。
        frames = 200 if SIZE <= 1000 else 60
        frame._drag_prev_rows = None
        frame._select_range(0, 0)
        times = []
        for row in range(1, frames + 1):
            start = time.perf_counter()
            frame._select_range(0, row)
            times.append((time.perf_counter() - start) * 1000)
        print("\n── 拖拽：逐行拖（每帧多一行，%d 帧）──" % frames, flush=True)
        print("  每帧平均 %.2f ms   最大 %.2f ms   合计 %.1f ms"
              % (sum(times) / len(times), max(times), sum(times)), flush=True)

        # 2a2. 往回拖（区间变小，考验"取消选中"那一支）
        times = []
        for row in range(frames, frames // 2, -1):
            start = time.perf_counter()
            frame._select_range(0, row)
            times.append((time.perf_counter() - start) * 1000)
        print("── 拖拽：往回拖（每帧少一行）──", flush=True)
        print("  每帧平均 %.2f ms   最大 %.2f ms"
              % (sum(times) / len(times), max(times)), flush=True)

        # 2b. 跳着拖：一帧跨一大段（快速划过，**最坏情况**）
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        frame._drag_prev_rows = None
        span = max(SIZE // 10, 10)
        times = []
        for step in range(1, 6):
            start = time.perf_counter()
            frame._select_range(0, step * span - 1)
            times.append((time.perf_counter() - start) * 1000)
        print("── 拖拽：跳着拖（每帧跨 %d 行，5 帧）──" % span, flush=True)
        print("  每帧平均 %.1f ms   最大 %.1f ms" % (sum(times) / len(times), max(times)),
              flush=True)

        # ══ 3. "清选中"那一步单独量 ═════════════════════════════
        bundle = instrument(ctrl)
        start = time.perf_counter()
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        cleared = (time.perf_counter() - start) * 1000
        stat = bundle["stat"]
        restore(ctrl, bundle)
        print("\n── 清掉全表选中（%d 行）──" % SIZE)
        print("  合计 %.1f ms" % cleared)
        report(stat, "清选中期间的控件调用")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        for _ in range(10):
            wx.YieldIfNeeded()
