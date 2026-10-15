"""测量 M3 剩下的那一半：**记录数增长时到底慢不慢**。

## 为什么现在才量

M3 原文是"无上限、无裁剪、全量渲染"，里面其实有**两个**问题：

① 每次打开重建两遍 —— 已修（`_render_rows` 2→1，列宽量测 5→1 并加采样上限）
② 记录数**没有上限** —— 这一半还没动

②要不要动、怎么动，取决于"几千条时到底有多慢"。
所以先量，不猜。

判据用**墙钟**（这里关心的是用户感受），但同一个规模重复几次取中位数
——单次测量在本机负载下会飘。
"""
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

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

SIZES = (200, 1000, 3000, 6000)
REPEATS = 3

print("  规模      建窗口   一次「打开」重建     列表行数")
print("  " + "-" * 56)

with probe_temp("probe-scale") as scratch:
    for size in SIZES:
        db = os.path.join(scratch, f"p{size}.db")
        cfg = os.path.join(scratch, f"c{size}.json")
        app_mod.default_db_path = lambda p=db: p
        app_mod.default_config_path = lambda c=cfg: c

        seed = app_mod.PathStore(db)
        for i in range(size):
            seed.record_access(os.path.join(scratch, f"folder-{i:05d}"))
        seed.close()

        t0 = time.perf_counter()
        frame = app_mod.FileTracker()
        frame.Show()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.01)
        open_ms = (time.perf_counter() - t0) * 1000

        samples = []
        for repeat in range(REPEATS):
            target = os.path.join(scratch, f"folder-{repeat * 7:05d}")
            sw = time.perf_counter()
            frame.record_accessed_path(target)
            for _ in range(20):
                wx.YieldIfNeeded()
            samples.append((time.perf_counter() - sw) * 1000)

        rows = frame.list_ctrl.GetItemCount()
        print(f"  {size:6}    {open_ms:6.0f} ms   "
              f"{statistics.median(samples):7.0f} ms (中位数 {REPEATS} 次)   {rows}")

        frame.store.close()
        frame.Destroy()
        for _ in range(10):
            wx.YieldIfNeeded()

print()
print("  说明：")
print("  * 「建窗口」= 启动到界面就绪，用户只感受一次")
print("  * 「一次重建」= 双击/回车一条记录之后的完整刷新，**每次都付**")
print("  * 列宽量测已有 200 行采样上限，所以那一项与规模无关；")
print("    随规模涨的是 `wx.ListCtrl` 的逐行插入（非虚拟列表）。")
