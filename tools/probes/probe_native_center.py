r"""测：`wx.ListCtrl` 的**原生列居中**（`wx.LIST_FORMAT_CENTER`）在这台机器上能不能用。

## 为什么值得测

频次列的"居中"现在是**补前导空格**实现的（`app._center_text`）：

```python
pad = (column_px - text_px) // space_px // 2      # ← 两次整除
```

两个整除的误差会累积，而且空格宽度是**量化单位** —— 只能对齐到一个空格的
整数倍，最多差半个空格（本机 ≈ 3~4 物理像素）。用户实测"切换中英文时
偏移特别明显"（中文列宽 89 是奇数，误差最大）。

如果原生居中可用，这一切都可以删掉：不补空格、不算宽度、没有量化误差。

## 项目历史上的结论（要复核）

文档里写着"`LVM_SETCOLUMN` 在这台机器上不可用（一律返回 0）"，
所以当年放弃了原生居中。**但那测的是"改已存在列"的格式**（`LVM_SETCOLUMN`），
而 `InsertColumn` 走的是**另一条消息**（`LVM_INSERTCOLUMN`）——
它在创建时就带上 format，完全可能支持。

## 判据

| # | 判据 |
|---|---|
| 1 | `InsertColumn(format=CENTER)` 之后，用 `LVM_GETCOLUMN` 回读 fmt 真的是 CENTER |
| 2 | 阳性对照：左对齐列仍是 LEFT、右对齐列是 RIGHT（三种能区分，不是全被设成一种） |
| 3 | **渲染层**：居中列里"文字像素的中点"比左对齐列更靠列中心 |
"""
from __future__ import annotations

import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

app = wx.App(redirect=False)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


# ── 用 ctypes 回读列的 fmt（wx 的 GetColumn 给的是 ListItem，没有 format）──
LVM_FIRST = 0x1000
LVM_GETCOLUMN = LVM_FIRST + 25
LVCF_FMT = 0x0001


class LVCOLUMNW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint32),
        ("fmt", ctypes.c_int32),
        ("cx", ctypes.c_int32),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int32),
        ("iSubItem", ctypes.c_int32),
        ("iImage", ctypes.c_int32),
        ("iOrder", ctypes.c_int32),
        ("cxMin", ctypes.c_int32),
        ("cxDefault", ctypes.c_int32),
        ("cxIdeal", ctypes.c_int32),
    ]


def read_format(ctrl, column: int) -> int:
    """用 `LVM_GETCOLUMN` 问系统"这一列的 fmt 是什么"。"""
    user32 = ctypes.windll.user32
    lvc = LVCOLUMNW()
    lvc.mask = LVCF_FMT
    lvc.iSubItem = column
    ok = user32.SendMessageW(ctrl.GetHandle(), LVM_GETCOLUMN, column,
                             ctypes.byref(lvc))
    return lvc.fmt if ok else -1


def text_span(ctrl, column: int, row: int) -> tuple[int, int] | None:
    """在列宽范围内找"非背景像素"的左右边界（判"文字落在哪"）。

    用 `wx.ClientDC` 直接抓控件客户区（**不是屏幕**，所以不会被别的窗口污染）。
    """
    dc = wx.ClientDC(ctrl)
    rect = ctrl.GetItemRect(row, wx.LIST_RECT_LABEL) if hasattr(wx, "LIST_RECT_LABEL") else None
    # 列的水平范围（从表头拿）
    x0 = 0
    for i in range(column):
        x0 += ctrl.GetColumnWidth(i)
    w = ctrl.GetColumnWidth(column)
    screen = wx.Bitmap(w, 24)
    mem = wx.MemoryDC(screen)
    try:
        mem.Blit(0, 0, w, 24, dc, x0, rect.y if rect else 20)
    except Exception:
        mem.SelectObject(wx.NullBitmap)
        return None
    img = screen.ConvertToImage()
    mem.SelectObject(wx.NullBitmap)
    xs = []
    for x in range(w):
        for y in range(img.GetHeight()):
            r, g, b = img.GetRed(x, y), img.GetGreen(x, y), img.GetBlue(x, y)
            if (r, g, b) != (255, 255, 255) and max(r, g, b) - min(r, g, b) < 40:
                xs.append(x)
                break
    if not xs:
        return None
    return min(xs), max(xs)


with probe_temp("probe-native-center") as scratch:
    frame = wx.Frame(None, size=(700, 300))
    panel = wx.Panel(frame)
    ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_NONE)

    formats = {0: wx.LIST_FORMAT_LEFT,
               1: wx.LIST_FORMAT_CENTER,
               2: wx.LIST_FORMAT_RIGHT}
    inserted = {}
    for index, fmt in formats.items():
        inserted[index] = ctrl.InsertColumn(index, "col%d" % index, format=fmt, width=160)

    for row in range(3):
        ctrl.InsertItem(row, "L%d" % row)
        ctrl.SetItem(row, 1, "%d" % (row + 7))
        ctrl.SetItem(row, 2, "R%d" % row)

    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(ctrl, 1, wx.EXPAND)
    panel.SetSizer(sizer)
    frame.Show()
    for _ in range(30):
        wx.YieldIfNeeded()
    ctrl.Refresh()
    ctrl.Update()

    print("=== InsertColumn 返回值 ===")
    for index, ok in inserted.items():
        print("  列%d -> %s" % (index, ok))

    print("\n=== LVM_GETCOLUMN 回读的 fmt ===")
    names = {wx.LIST_FORMAT_LEFT: "LEFT", wx.LIST_FORMAT_CENTER: "CENTER",
             wx.LIST_FORMAT_RIGHT: "RIGHT"}
    got = {}
    for index in range(3):
        fmt = read_format(ctrl, index)
        got[index] = fmt
        print("  列%d 期望 %-6s 回读 0x%04X (%s)"
              % (index, names[formats[index]], fmt & 0xFFFF,
                 names.get(fmt & 0xFFFF, "?")))

    check("1 第 2 列（居中）的回读 fmt 有 CENTER 位",
          got[1] >= 0 and bool((got[1] & wx.LIST_FORMAT_CENTER) == wx.LIST_FORMAT_CENTER),
          "回读 0x%04X，CENTER = 0x%04X" % (got[1] & 0xFFFF, wx.LIST_FORMAT_CENTER))
    check("2 阳性对照：左对齐列不是 CENTER；右对齐列是 RIGHT（三种能区分）",
          not bool((got[0] & wx.LIST_FORMAT_CENTER) == wx.LIST_FORMAT_CENTER)
          and bool((got[2] & wx.LIST_FORMAT_RIGHT) == wx.LIST_FORMAT_RIGHT),
          "左 0x%04X / 右 0x%04X" % (got[0] & 0xFFFF, got[2] & 0xFFFF))

    # ── 渲染层：居中列的文字应当比左对齐列更靠中间 ──────────────
    print("\n=== 渲染层：文字像素范围（每列宽 160）===")
    spans = {}
    for index in range(3):
        span = text_span(ctrl, index, 0)
        spans[index] = span
        print("  列%d %s" % (index, span))
    if spans[0] and spans[1]:
        left_margin = spans[1][0] - 0        # 居中列的左边距
        print("  居中列左边距 = %d；左对齐列左边距 = %d" % (left_margin, spans[0][0]))
        check("3 居中列的文字比左对齐列**更靠右**（说明原生居中真的生效）",
              spans[1][0] > spans[0][0] + 2,
              "居中 %d vs 左对齐 %d" % (spans[1][0], spans[0][0]))
    else:
        check("3 渲染层取到文字像素", False, "spans = %r" % (spans,))

    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()

print()
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败"
      % (len(results), sum(1 for ok, _, _ in results if ok),
         sum(1 for ok, _, _ in results if not ok)))
