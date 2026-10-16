r"""性能基准：把"一条操作要多久"逐项量出来，并**分规模**看增长趋势。

## 为什么要重写一个（而不是直接用 `probe_scale_profile.py`）

那个探针量的是**旧路径**（只有"重建"一条）。2026-10-17 加了多选之后
多出了几条**每次鼠标移动都会跑**的路径，它们此前从未被量过：

| 新路径 | 触发频率 | 为什么可疑 |
|---|---|---|
| `_apply_selection_highlight` | 每次悬停/选中变化 | 要遍历选中集 |
| `_select_range`（拖拽） | **拖动时每一帧** | 每次都 `Select()` 全表一遍 |
| `selected_paths()` / `selected_rows()` | 每次右键、每次打开 | `GetNextItem` 逐个走 |
| `_render_rows` 恢复选中 | 每次重建 | `_index_of_path` 是**线性扫描** |

## 判据

每个操作给出**绝对耗时**与**随行数的增长倍数**。增长明显超线性的，
就是下一轮要优化的点（本项目的历史：`InsertItem` 是 0.26 ms/行，近线性）。

跑法：

```bash
python tools/probes/probe_perf_baseline.py
python tools/probes/probe_perf_baseline.py --sizes 200 1000 3000
```
"""
from __future__ import annotations

import ctypes
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

SIZES = [200, 1000, 3000, 6000]
if "--sizes" in sys.argv:
    index = sys.argv.index("--sizes")
    SIZES = [int(value) for value in sys.argv[index + 1:]] or SIZES

measurements: dict[str, dict[int, float]] = {}


def record(name: str, size: int, seconds: float) -> None:
    measurements.setdefault(name, {})[size] = seconds


def pump(rounds=8):
    for _ in range(rounds):
        wx.YieldIfNeeded()


def timed(label: str, size: int, action, *, rounds: int = 1) -> float:
    """跑 `rounds` 次取**平均**（避免单次抖动把结论带偏）。"""
    best = None
    total = 0.0
    for _ in range(rounds):
        start = time.perf_counter()
        action()
        total += time.perf_counter() - start
    best = total / rounds
    record(label, size, best)
    return best


with probe_temp("probe-perf") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(40)
    ctrl = frame.list_ctrl

    try:
        for size in SIZES:
            # **每档规模都从库开始重造**（去掉上一档的残留）
            frame.store.clear()
            rows = [os.path.join(scratch, "s%05d" % i) for i in range(size)]
            for path in rows:
                frame.store.record_access(path)
            selection_paths = rows[: min(size, 200)]

            # ── 1. 读库 + 排序（纯 Python/DB 侧）─────────────────
            timed("1 读库+排序(无渲染)", size,
                  lambda: frame._ordered_records(), rounds=3)

            # ── 2. 整表重建（`_render_rows`，历史主瓶颈）─────────
            def rebuild():
                frame._rows = frame._ordered_records()
                frame._render_rows()
            timed("2 整表重建 _render_rows", size, rebuild, rounds=2)
            pump(4)

            # ── 3. 高亮重画（悬停/选中变化时跑）────────────────
            def repaint():
                frame._paint_key = None
                frame._apply_selection_highlight()
            ctrl.Select(0, True)
            timed("3 高亮重画(单选)", size, repaint, rounds=3)

            # ── 4. 多选 200 条后的高亮重画 ──────────────────────
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            for path in selection_paths:
                row = frame._index_of_path(path)
                if row >= 0:
                    ctrl.Select(row, True)

            def repaint_multi():
                frame._paint_key = None
                frame._apply_selection_highlight()
            timed("4 高亮重画(多选 %d)" % len(selection_paths), size,
                  repaint_multi, rounds=3)

            # ── 5. 取选中集（右键/打开时跑）─────────────────────
            timed("5 取选中集 selected_paths", size,
                  lambda: frame.selected_paths(), rounds=3)

            # ── 6. 按路径找行号（重建恢复选中时跑）──────────────
            timed("6 _index_of_path × 1", size,
                  lambda: frame._index_of_path(rows[size // 2]), rounds=3)

            # ── 7. 拖拽一帧（_select_range 全表一遍）────────────
            def one_drag_frame():
                frame._select_range(10, min(10 + size // 10, size - 1))
            timed("7 拖拽一帧 _select_range", size, one_drag_frame, rounds=3)
            pump(4)

            # ── 8. 多选删除后的重建（用户刚报的那条路）──────────
            def delete_and_rebuild():
                frame._remove_paths(selection_paths[:20])
            timed("8 删 20 条+重建", size, delete_and_rebuild, rounds=1)
            pump(4)
            # 删掉的那些补回去，好让下一个规模从干净状态开始
            for path in selection_paths[:20]:
                frame.store.record_access(path)

        # ── 输出 ────────────────────────────────────────────────
        print("\n单位：毫秒（越小越好）")
        header = "操作".ljust(28) + "".join(
            ("%9d" % size) for size in SIZES) + "   增长(末/首)"
        print(header)
        print("-" * len(header))
        for name in sorted(measurements, key=lambda key: int(key.split()[0])):
            per_size = measurements[name]
            cells = []
            for size in SIZES:
                value = per_size.get(size)
                cells.append(("%9.1f" % (value * 1000)) if value is not None
                             else "%9s" % "-")
            first = per_size.get(SIZES[0])
            last = per_size.get(SIZES[-1])
            ratio = ("%6.1f×" % (last / first)) if first and last else "     -"
            print(name.ljust(28) + "".join(cells) + "  " + ratio)

        print("\n── 判读 ──")
        print("  增长倍数 ≈ 行数倍数 ⇒ 线性（正常）")
        print("  增长倍数 **明显高于**行数倍数 ⇒ 超线性，优先优化")
        print("  行数倍数 = %.1f×" % (SIZES[-1] / SIZES[0]))
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
