r"""测：**路径列数据左侧加内边距**有哪条路可走。

## 用户的要求（2026-10-17）

> "访问路径（path）列的数据左边增加一点间距，怎么实现
>   （直接加空格还是其他方式）你来定。"

## 候选方案与风险

| 方案 | 做法 | 风险 |
|---|---|---|
| **A. 加前导空格** | `" " + path` | **会污染 `GetItemText`** —— `row_path()` / `find_path()` / `_selected_paths()` 全都按"控件里的文本 == 路径"工作，加了空格它们就都错了 |
| **B. `LVM_SETITEMINDENT`** | 原生"项缩进" | 每条记录都要设一次（6000 行 = 6000 次）；且要确认这台机器支持 |
| **C. 列宽不匹配** | 让列宽大于内容 | 不改数据，但也不产生左边距 |

## 判据

| # | 判据 |
|---|---|
| 1 | `LVM_SETITEMINDENT` 被系统接受（返回值非 0 / 回读得到设进去的值） |
| 2 | 设了之后 `GetItemText` **仍然是干净路径**（不加空格 ⇒ 不影响逻辑层） |
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


LVM_FIRST = 0x1000
LVM_SETITEMINDENT = LVM_FIRST + 75
LVM_GETITEMINDENT = None   # 没有这个回读消息，只能靠"返回值非 0"判断
LVIF_INDENT = 0x0010


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint32),
        ("iItem", ctypes.c_int32),
        ("iSubItem", ctypes.c_int32),
        ("state", ctypes.c_uint32),
        ("stateMask", ctypes.c_uint32),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int32),
        ("iImage", ctypes.c_int32),
        ("lParam", ctypes.c_void_p),
        ("iIndent", ctypes.c_int32),
        ("iGroupId", ctypes.c_int32),
        ("cColumns", ctypes.c_uint32),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int32),
    ]


with probe_temp("probe-path-indent") as scratch:
    frame = wx.Frame(None, size=(700, 260))
    panel = wx.Panel(frame)
    ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_NONE)
    ctrl.InsertColumn(0, "Path", width=400)
    ctrl.InsertItem(0, "D:\\Folder\\File.txt")
    ctrl.InsertItem(1, "D:\\Another")
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(ctrl, 1, wx.EXPAND)
    panel.SetSizer(sizer)
    frame.Show()
    for _ in range(30):
        wx.YieldIfNeeded()

    user32 = ctypes.windll.user32
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.c_ssize_t, ctypes.c_void_p]

    indent_px = 12
    accepted = []
    for row in range(2):
        info = LVITEMW()
        info.mask = LVIF_INDENT
        info.iItem = row
        info.iIndent = indent_px
        got = user32.SendMessageW(ctrl.GetHandle(), LVM_SETITEMINDENT, 0,
                                  ctypes.byref(info))
        accepted.append(got)
        print("  LVM_SETITEMINDENT(row=%d, indent=%d) 返回 %r"
              % (row, indent_px, got))

    check("1 `LVM_SETITEMINDENT` 被系统接受（返回非 0）",
          all(bool(a) for a in accepted),
          "返回值 = %r（0 通常表示不支持）" % (accepted,))

    # 判据 2：文本必须仍然是干净路径
    texts = [ctrl.GetItemText(r) for r in range(2)]
    check("2 设了缩进之后 `GetItemText` 仍是干净路径（无前导空格）",
          texts == ["D:\\Folder\\File.txt", "D:\\Another"],
          "读回 = %r" % (texts,))

    # 阳性对照：再设一个大一点的缩进，看它是否"接受"——如果任何值都返回非 0，
    # 说明这个返回值不可信（可能是"总是成功"的假信号）
    info = LVITEMW()
    info.mask = LVIF_INDENT
    info.iItem = 0
    info.iIndent = 200
    got_big = user32.SendMessageW(ctrl.GetHandle(), LVM_SETITEMINDENT, 0,
                                  ctypes.byref(info))
    print("  对照：indent=200 返回 %r" % (got_big,))
    check("3 阳性对照：不同 indent 的返回值一致（说明返回值不是恒真的假信号）",
          bool(got_big) == bool(accepted[0]),
          "indent=12 -> %r，indent=200 -> %r" % (accepted[0], got_big))

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
