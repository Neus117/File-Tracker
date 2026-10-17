r"""低时间成本体检：图标绘制耗时 + 设置对话框构造 + 代码体积。

## 为什么单独写一个

`probe_perf_detail.py` 跑的是"6000 行主列表重建"，要起窗口、灌数据，
几秒起步。而本轮的改动全在**图标绘制**上 —— 那是"开一次设置窗口"
才会发生的几十次调用，用大探针测它属于杀鸡用牛刀。

这里只量三件事，全程 **< 10 秒**：

1. **单个图标的图元生成耗时**（纯 Python 几何，不起窗口）
2. **`_draw_icon` 的绘制耗时**（真起窗口，画 2000 次）
3. **`SettingsDialog` 构造耗时**（含全部 8 个图标的一次绘制）

第 1 项不需要窗口，所以先跑它 —— 即使后面失败也有结论。
"""
from __future__ import annotations

import ctypes
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.widgets as W

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def timeit(fn, repeat: int) -> tuple[float, float]:
    """返回 (中位数微秒, 总毫秒)。中位数比平均更抗首次调用的冷启动。"""
    samples = []
    start_all = time.perf_counter()
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e6)
    total_ms = (time.perf_counter() - start_all) * 1000.0
    return statistics.median(samples), total_ms


# ---------------------------------------------------------------- ① 纯几何
print("=== ① 图元生成（纯 Python，不需要窗口）===")
PAINTERS = (
    ("icon_monitor", W.icon_monitor),
    ("icon_sun", W.icon_sun),
    ("icon_moon", W.icon_moon),
    ("icon_path", W.icon_path),
    ("icon_count", W.icon_count),
    ("icon_time", W.icon_time),
    ("icon_arrow_up", W.icon_arrow_up),
    ("icon_arrow_down", W.icon_arrow_down),
)
COLOUR = wx.Colour(30, 30, 30) if False else "#1E1E1E"   # 纯几何不碰 wx
geometry_total = 0.0
for name, fn in PAINTERS:
    med, total = timeit(lambda: fn(100.0, 100.0, 24.0, COLOUR), 2000)
    geometry_total += total
    print("  %-16s 中位 %6.1f µs / 2000 次共 %6.2f ms" % (name, med, total))
print("  ⇒ 八个图标各生成一次：约 %.3f ms" % (geometry_total / 2000.0))

# ---------------------------------------------------------------- ② 绘制
app = wx.App(redirect=False)

with probe_temp("perf-icons") as scratch:
    frame = wx.Frame(None, size=(400, 300))
    panel = wx.Panel(frame)
    frame.Show()
    for _ in range(20):
        wx.YieldIfNeeded()

    scene = wx.GraphicsContext.Create(wx.MemoryDC(wx.Bitmap(64, 64)))
    print()
    print("=== ② `_draw_icon` 绘制（真 GC，每个 500 次）===")
    draw_total = 0.0
    for name, fn in PAINTERS:
        def run(fn=fn):
            W._draw_icon(scene, fn, 32.0, 32.0, 24.0,
                         wx.Colour("#1E1E1E"), wx.Colour("#FFFFFF"))
        med, total = timeit(run, 500)
        draw_total += total
        print("  %-16s 中位 %6.1f µs / 500 次共 %6.2f ms" % (name, med, total))
    print("  ⇒ 八个图标各画一次：约 %.3f ms" % (draw_total / 500.0))

    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

# ---------------------------------------------------------------- ③ 对话框
with probe_temp("perf-dialog") as scratch:
    import file_tracker.app as app_mod
    from file_tracker.widgets import SettingsDialog

    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    store = app_mod.PathStore(db)
    store.close()
    frame = app_mod.FileTracker()
    frame.open_folder = lambda p: True
    frame.SetSize((1000, 520))
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()

    print()
    print("=== ③ `SettingsDialog` 构造（含 8 个图标）===")
    built = []

    def build():
        dlg = SettingsDialog(frame, frame.theme, "zh", sort_key="path",
                             sort_reverse=True, theme_preference="light")
        built.append(dlg)

    med, total = timeit(build, 5)
    for dlg in built:
        try:
            dlg.Destroy()
        except Exception:
            pass
    print("  中位 %.1f ms / 5 次共 %.1f ms" % (med / 1000.0, total))

    try:
        frame.store.close()
    except Exception:
        pass
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

print()
print("完成")
