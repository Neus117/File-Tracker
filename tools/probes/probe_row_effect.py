"""量"空图列表抬行高"这一招的**副作用**。

## 用户要求

"改动后一定要验是否破坏了原有功能"——所以光量行高变没变不够，
还得量它**动了别的什么**。

## 量四件事

| # | 量什么 | 怎么量 | 期望 |
|---|---|---|---|
| 1 | 行高 | `GetItemRect(0).height` | **变大** |
| 2 | 路径文字的横向起点 | `GetSubItemRect(0, 0)` | 可能右移（**固有代价**） |
| 3 | 数据是否还在 | 逐行 `GetItemText` 与库对比 | **一条不少、一字不差** |
| 4 | 列数与列宽 | `GetColumnCount` / `GetColumnWidth` | 列数不变；路径列宽自适应 |

第 3 条是"有没有破坏功能"的核心判据——**行高是外观，数据完整性不是**。
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

from file_tracker import win32

#: 先量"不挂图列表"的基线，再量挂了之后——同一进程里来回切
with probe_temp("probe-row-effect") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    names = [os.path.join(scratch, f"folder-{i:03d}") for i in range(15)]
    for n in names:
        seed.record_access(n)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    ctrl = frame.list_ctrl
    handle = ctrl.GetHandle()

    def subitem_rect(row: int, col: int, code=None) -> wx.Rect:
        """取子项矩形。

        ⚠️ `GetSubItemRect` 是**出参式**的：
        `GetSubItemRect(item, subItem, rect, code=...) -> bool`，
        直接调用会报 `not enough arguments`。

        ⚠️ **`code` 决定量到的是哪一块**：
        `LIST_RECT_BOUNDS`（默认）给整格，起点恒为该列左边缘——
        **它看不到图标位的内缩**，所以拿它判"文字有没有右移"是量错了对象。
        `LIST_RECT_LABEL` 给**文字区**，那才是要看的那一块。
        """
        rect = wx.Rect()
        if code is None:
            ctrl.GetSubItemRect(row, col, rect)
        else:
            ctrl.GetSubItemRect(row, col, rect, code)
        return rect

    def snapshot(tag: str) -> dict:
        for _ in range(8):
            wx.YieldIfNeeded()
        rows = ctrl.GetItemCount()
        bounds = subitem_rect(0, 0) if rows else wx.Rect(-1, -1, -1, -1)
        label = (subitem_rect(0, 0, wx.LIST_RECT_LABEL) if rows
                 else wx.Rect(-1, -1, -1, -1))
        return {
            "tag": tag,
            "row_h": ctrl.GetItemRect(0).height if rows else 0,
            "text_h": ctrl.GetTextExtent("Ag")[1],
            "bounds_x": bounds.x,
            "label_x": label.x,
            "label_w": label.width,
            "cols": ctrl.GetColumnCount(),
            "col0_w": ctrl.GetColumnWidth(0),
            "texts": [ctrl.GetItemText(r, 0) for r in range(rows)],
        }

    after = snapshot("挂了空图列表（当前实现）")

    # **真的摘掉图列表**再量基线。
    #
    # ⚠️ 实测教训有两条，都值得记：
    #
    # ① 第一版这里写的是 `SetImageList(wx.ImageList(1, 1), ...)` ——
    #    那仍然挂着一张 1px 的图，**不是对照**：两组都挂着，
    #    行高与文字区当然一模一样，结论会变成"改了没效果"。
    # ② 改成 `SetImageList(None, ...)` 之后**行高也没有降回去** ——
    #    Windows 会把已经算好的行高缓存住，进程内摘掉图列表不会让它缩回。
    #
    # **所以进程内来回切不是可靠对照。** 可靠的对照是**跨版本**：
    # 加这套机制之前，同一探针量到的是 **39px**；现在是 **46px**。
    # 下面对比列里的"基线"只当参考，不要拿它当结论。
    ctrl.SetImageList(None, wx.IMAGE_LIST_SMALL)
    for _ in range(8):
        wx.YieldIfNeeded()
    before = snapshot("基线（图列表高 1）")

    print(f"  行数 = {len(after['texts'])}")
    print()
    print(f"  {'':22}{'基线':>10}{'现在':>10}{'差':>8}")
    print("  " + "-" * 52)
    for key, label in (("row_h", "行高"),
                       ("text_h", "文字高"),
                       ("bounds_x", "整格左边界 x"),
                       ("label_x", "**文字区**左边界 x"),
                       ("label_w", "**文字区**宽度"),
                       
                       ("cols", "列数"),
                       ("col0_w", "路径列宽")):
        a, b = before[key], after[key]
        print(f"  {label:22}{a:>10}{b:>10}{b - a:>+8}")

    print()
    print("  ── 数据完整性（这是「有没有破坏功能」的核心判据）──")
    same = before["texts"] == after["texts"]
    print(f"    挂图列表前后，逐行文本完全一致 = {same}")
    listed = set(after["texts"])
    missing = [n for n in names if n not in listed]
    print(f"    库里 {len(names)} 条，界面显示 {len(listed)} 条，缺 {len(missing)} 条")
    if missing:
        for m in missing[:3]:
            print(f"      缺: {m}")

    print()
    print("  ── 结论 ──")
    print(f"    行高 {before['row_h']} → {after['row_h']}"
          f"（{after['row_h'] - before['row_h']:+d}px）")
    shift = after["label_x"] - before["label_x"]
    if shift:
        print(f"    ⚠️ 路径文字右移 {shift}px —— 这是空图列表的固有代价")
    else:
        print(f"    ✅ 路径文字没有右移（文字区左边界 {before['label_x']}px，两边一样）")
    print(f"    文字区宽度 {before['label_w']} -> {after['label_w']}px")
    print(f"    数据：{'✅ 一条不少、一字不差' if same and not missing else '❌ 有差异'}")

    frame.store.close()
    frame.Destroy()
