r"""验：表头的**排序三角位置**与**标题是否居中**（用户 2026-10-17 的要求）。

## 这个探针**不推算几何，只拦截真实绘制**

前几版探针自己复刻了 `header._on_paint` 的公式，结果实现一改（字符三角
→ 绘制三角、加标题居中），探针就报出不可能的值（"留白 −4"）。

**探针复刻实现公式是脆弱的。** 所以这里改成拦截 `DrawText` / `DrawPolygon`，
拿**真正画出来的坐标**：

* 标题：`DrawText` 的 x
* 三角：`DrawPolygon` 的三个点 ⇒ 取 x 的范围

## 判据

| # | 判据 |
|---|---|
| 1 | 三角的右缘 **≤ 该列右边界**（任何语言/DPI 下都不越过分隔线） |
| 2 | 非最右列：三角右缘到分隔线**有留白**（不贴着线） |
| 3 | 最右列（时间）：留白**很小**（它右边没有分隔线要避让） |
| 4 | `访问日期` 的**标题**居中（左右留白差 ≤ 4 像素） |
| 5 | 阳性对照：日期列的**数据**仍左对齐（用户明确要求"数据不要居中"） |
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

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

app = wx.App(redirect=False)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=20, pause=0.004):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


class PaintSpy:
    """拦截真实绘制调用，记下每一段文字 / 每个多边形的坐标。"""

    def __init__(self):
        self.texts = []       # (text, x, width)
        self.polygons = []    # (x_min, x_max)
        self._orig_text = wx.DC.DrawText
        self._orig_poly = wx.DC.DrawPolygon

    def __enter__(self):
        spy = self

        def draw_text(dc, text, x, y, *a, **k):
            spy.texts.append((text, x, dc.GetTextExtent(text).width))
            return spy._orig_text(dc, text, x, y, *a, **k)

        def draw_polygon(dc, points, x=0, y=0, *a, **k):
            xs = [p.x for p in points]
            spy.polygons.append((min(xs), max(xs)))
            return spy._orig_poly(dc, points, x, y, *a, **k)

        wx.DC.DrawText = draw_text
        wx.DC.DrawPolygon = draw_polygon
        return self

    def __exit__(self, *exc):
        wx.DC.DrawText = self._orig_text
        wx.DC.DrawPolygon = self._orig_poly
        return False

    def clear(self):
        self.texts.clear()
        self.polygons.clear()


with probe_temp("probe-header-final") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    try:
        header = frame.header
        for language, name in ((lang.PREFERENCE_ENGLISH, "英文"),
                               (lang.PREFERENCE_CHINESE, "中文")):
            lang.apply(language)
            frame.retranslate()
            frame.adjust_column_widths()
            pump(20)
            labels = app_mod.column_labels()

            # 列边界（从表头自己的 widths 累积——这是绘制用的同一份数据）
            bounds, acc = [], 0
            for w in header.widths:
                bounds.append((acc, acc + w))
                acc += w

            with PaintSpy() as spy:
                header.Refresh()
                header.Update()
                pump(8)

            print("\n【%s】" % name)
            print("  列边界：" + "  ".join("%s[%d,%d)" % (labels[i][:4], b[0], b[1])
                                          for i, b in enumerate(bounds) if i < len(labels)))
            print("  实际绘制（标题）：")
            for text, x, w in spy.texts:
                print("    %-10r x=%-5d 宽=%-4d 右缘=%-5d" % (text, x, w, x + w))
            # **三角现在是字符**（`▼` / `▲`，用户要求换回：自绘的有锯齿），
            # 所以从 DrawText 里筛出来 —— 而不是找 DrawPolygon。
            arrow_boxes = list(spy.polygons) or [
                (x, x + w) for text, x, w in spy.texts
                if text in ("\u25bc", "\u25b2")
            ]
            for xmin, xmax in arrow_boxes:
                print("    三角       x=%-5d 右缘=%-5d" % (xmin, xmax))

            # ── 判据 1/2：三角在列内、且不贴着分隔线 ──────────────
            # 注：2026-10-17 之后只有三列（日期并进了时间列），
            # 最右列是 `COLUMN_TIME`。
            time_title = labels[app_mod.COLUMN_TIME]
            time_bound = bounds[app_mod.COLUMN_TIME]

            for xmin, xmax in arrow_boxes:
                center = (xmin + xmax) // 2
                owner = next((i for i, (lo, hi) in enumerate(bounds) if lo <= center < hi), None)
                if owner is None:
                    continue
                lo, hi = bounds[owner]
                slack = hi - xmax
                title = labels[owner] if owner < len(labels) else "?"
                check("1 [%s] 三角（%s 列）右缘不越过列边界" % (name, title),
                      xmax <= hi, "右缘 %d vs 列右界 %d" % (xmax, hi))
                if owner != app_mod.COLUMN_TIME:
                    check("2 [%s] 三角（%s 列）与分隔线有留白（≥ 4）" % (name, title),
                          slack >= 4, "留白 = %d" % slack)

            # ── 判据 3：**若排序列是最右列**，它的留白应该很小 ──────
            if header._sort_column == app_mod.COLUMN_TIME:
                rightmost = max((xmax for xmin, xmax in arrow_boxes), default=None)
                if rightmost is not None:
                    slack = time_bound[1] - rightmost
                    check("3 [%s] 最右列（%s）作为排序列时留白很小（≤ 16）"
                          % (name, time_title),
                          0 <= slack <= 16, "留白 = %d" % slack)
                else:
                    check("3 [%s] 最右列作为排序列时画出了三角" % name, False, "没抓到三角")

            # 注：判据 4/5（"访问日期标题居中 / 数据不居中"）已删除 ——
            # 那一列在 2026-10-17 并入时间列，`centered_titles` 也随之清空。
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(10)

print()
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败"
      % (len(results), sum(1 for ok, _, _ in results if ok),
         sum(1 for ok, _, _ in results if not ok)))
