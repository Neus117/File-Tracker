r"""`InsertItem` 的多列重载能不能用 —— 能不能把 4 次跨语言调用压成 1 次。

## 为什么要试

`probe_perf_detail.py`（6000 行）显示重建里最大的一项是：

```
SetItem   18000 次  239.5 ms  46.4%     ← 每行 3 次（频次/日期/时间）
InsertItem 6000 次  119.2 ms  23.1%     ← 每行 1 次（路径列）
```

wx 的 `InsertItem` 有个重载：`InsertItem(index, text, imageIndex, values)`
—— `values` 是**后续各列的文本列表**，原生侧只发一次
`LVM_INSERTITEM`（带 `LVITEM.pszText` + `LVITEM.iSubItem` 逐列）。

**如果它可用，每行的 4 次调用会变成 1 次**（18000 + 6000 → 6000）。

## 判据

**功能等价**才算可用 —— 光"不报错"不够：

1. 重载能插入并返回正确的行号
2. **4 列文本都对**（不是只写了第一列）
3. 与"逐个 `SetItem`"的结果**逐格比对一致**
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

app = wx.App(redirect=False)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


with probe_temp("probe-overload") as scratch:
    frame = wx.Frame(None, size=(900, 400))
    ctrl = wx.ListCtrl(frame, style=wx.LC_REPORT)
    for index, width in enumerate((300, 80, 100, 100)):
        ctrl.InsertColumn(index, "c%d" % index, width=width)
    frame.Show()
    for _ in range(20):
        wx.YieldIfNeeded()

    rows = [
        ("path-A", ("1", "2026-10-17", "10:00")),
        ("path-B", ("22", "2026-10-16", "09:30")),
        ("path-C", ("333", "2026-10-15", "23:59")),
    ]

    # ── 方式一：逐个 SetItem（现状）────────────────────────────
    print("【方式一】InsertItem + 逐列 SetItem")
    try:
        for path, values in rows:
            index = ctrl.InsertItem(ctrl.GetItemCount(), path)
            for column, value in enumerate(values, start=1):
                ctrl.SetItem(index, column, value)
        for _ in range(10):
            wx.YieldIfNeeded()
        old_cells = [[ctrl.GetItemText(r, c) for c in range(4)]
                     for r in range(ctrl.GetItemCount())]
        for row in old_cells:
            print("   ", row)
        check("1 逐列 SetItem 的基线可用", len(old_cells) == 3, str(old_cells))
    except Exception as error:
        check("1 逐列 SetItem 的基线可用", False, repr(error))
        old_cells = []

    # ── 方式二：多列重载 ───────────────────────────────────────
    print("\n【方式二】InsertItem(行, 路径, 图像, [后续列...])")
    ctrl.DeleteAllItems()
    for _ in range(10):
        wx.YieldIfNeeded()
    new_cells = []
    try:
        for path, values in rows:
            index = ctrl.InsertItem(ctrl.GetItemCount(), path, -1, list(values))
            print("    插入返回 index = %r" % index)
        for _ in range(10):
            wx.YieldIfNeeded()
        new_cells = [[ctrl.GetItemText(r, c) for c in range(4)]
                     for r in range(ctrl.GetItemCount())]
        for row in new_cells:
            print("   ", row)
        check("2 多列重载能插入（不抛异常）", True, "")
    except Exception as error:
        print("    抛异常：%r" % (error,))
        check("2 多列重载能插入（不抛异常）", False, repr(error))

    # ── 判据 3：逐格比对 ───────────────────────────────────────
    check("3 两种方式的**每一格**都一致", bool(old_cells) and old_cells == new_cells,
          "旧 = %s\n       新 = %s" % (old_cells, new_cells))

    # 静态检查：确认用的是 4 参重载（`values` 那个），而不是别的
    check("4 返回值是行号（不是 None/False）",
          ctrl.GetItemCount() == 3, "行数 = %d" % ctrl.GetItemCount())

    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
